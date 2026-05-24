"""File materialization strategies.

A `FileMaterializer` knows how to make a target path reflect a source path.
The first (and currently only) implementation, `HardlinkMaterializer`, uses
filesystem hardlinks — the behavior jellyplex-sync has always had. Copy
backends arrive in a later step of Paket 4.

The seam exists so the CLI can swap materialization strategies (`--copy`,
`--force-copy`) without the sync orchestration needing to know how the
bytes get there.
"""

from __future__ import annotations

import logging
import pathlib
import shutil
from typing import Protocol

from .library import FileEvent

log = logging.getLogger(__name__)


class FileMaterializer(Protocol):
    name: str

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        """Make `dst` reflect `src`. Return True if a (re)materialization
        happened, False if `dst` already held the right content.
        Implementations are responsible for deciding what "already right"
        means (e.g. same inode for hardlinks, size+mtime match for copies).

        If `events` is provided, appends a `FileEvent` describing the
        action taken (`link` / `replace` / `skip`)."""
        ...


class HardlinkMaterializer:
    """Default backend. Creates a hardlink at `dst` pointing to `src`'s inode.

    Requires `src` and `dst` to live on the same filesystem; that's the
    constraint that motivates the copy backends.
    """

    name = "hardlink"

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        if dst.exists():
            if dst.samefile(src):
                if verbose:
                    log.info("Target '%s' already linked", dst.name)
                if events is not None:
                    events.append(FileEvent(action="skip", target=dst, source=src))
                return False
            log.info("Replacing '%s' → '%s'", src.name, dst.name)
            if dry_run:
                log.info("DELETE %s", dst)
            else:
                dst.unlink()
            if events is not None:
                events.append(FileEvent(action="replace", target=dst, source=src))
        else:
            if events is not None:
                events.append(FileEvent(action="link", target=dst, source=src))
        if dry_run:
            log.info("LINK   %s", dst)
        else:
            log.info("Linking '%s' → '%s'", src.name, dst.name)
            dst.hardlink_to(src)
        return True


class CopyMaterializer:
    """Copy bytes from `src` to `dst`. Works across filesystems.

    On re-runs, skips files whose target already has the same size *and*
    mtime as the source. That heuristic covers the realistic case where
    a previous sync run copied the file and neither side has changed
    since. If the source was modified (mtime advanced) or its size
    changed, the target gets replaced. Use `ForceCopyMaterializer`
    instead to bypass the check entirely.
    """

    name = "copy"

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        if dst.exists() and _same_size_and_mtime(src, dst):
            if verbose:
                log.info("Target '%s' is up to date", dst.name)
            if events is not None:
                events.append(FileEvent(action="skip", target=dst, source=src))
            return False
        return _copy(
            src, dst, dry_run=dry_run, replaces_existing=dst.exists(), events=events
        )


class ForceCopyMaterializer:
    """Copy bytes from `src` to `dst` unconditionally.

    No size/mtime check; the target is always rewritten. Use when the
    `CopyMaterializer` heuristic isn't trustworthy in your environment
    (e.g. mtimes were tampered with, or you want absolute certainty
    that the bytes on disk match the source).
    """

    name = "force-copy"

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        _ = verbose  # force-copy always logs the copy; verbose flag has no effect
        return _copy(
            src, dst, dry_run=dry_run, replaces_existing=dst.exists(), events=events
        )


class MoveMaterializer:
    """Copy bytes from `src` to `dst`, then delete `src` on success.

    Designed for staging-area workflows where the source is a temporary
    dump and the target is the permanent library. Once the target file
    is safely written (via `shutil.copy2`), the source is removed.

    Re-run safety: if the target already exists with matching size and
    mtime, the source is assumed to have been moved in a previous run
    (or the copy was already successful) and is left alone.

    If the source no longer exists but the target does, the file is
    treated as already moved and silently skipped.
    """

    name = "move"

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        if not src.exists():
            if dst.exists():
                if verbose:
                    log.info("Already moved '%s'", dst.name)
                if events is not None:
                    events.append(FileEvent(action="skip", target=dst))
                return False
            log.warning("Source '%s' does not exist, skipping", src)
            return False

        if dst.exists() and _same_size_and_mtime(src, dst):
            if verbose:
                log.info("Target '%s' is up to date, removing source", dst.name)
            if events is not None:
                events.append(FileEvent(action="skip", target=dst, source=src))
            if not dry_run:
                src.unlink()
            return False

        result = _copy(
            src, dst, dry_run=dry_run, replaces_existing=dst.exists(), events=events
        )
        if result and not dry_run:
            src.unlink()
            log.info("Removed source '%s'", src.name)
        return result


def _same_size_and_mtime(a: pathlib.Path, b: pathlib.Path) -> bool:
    a_stat = a.stat()
    b_stat = b.stat()
    return a_stat.st_size == b_stat.st_size and a_stat.st_mtime == b_stat.st_mtime


def _copy(
    src: pathlib.Path,
    dst: pathlib.Path,
    *,
    dry_run: bool,
    replaces_existing: bool,
    events: list[FileEvent] | None = None,
) -> bool:
    if replaces_existing:
        if dry_run:
            log.info("DELETE %s", dst)
        else:
            log.info("Replacing '%s' → '%s'", src.name, dst.name)
            dst.unlink()
        if events is not None:
            events.append(FileEvent(action="replace", target=dst, source=src))
    else:
        if events is not None:
            events.append(FileEvent(action="link", target=dst, source=src))
    if dry_run:
        log.info("COPY   %s", dst)
    else:
        log.info("Copying '%s' → '%s'", src.name, dst.name)
        # copy2 preserves mtime/atime/permissions so the CopyMaterializer's
        # size+mtime skip logic actually works on the next run.
        shutil.copy2(src, dst)
    return True
