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
from typing import Protocol

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
    ) -> bool:
        """Make `dst` reflect `src`. Return True if a (re)materialization
        happened, False if `dst` already held the right content.
        Implementations are responsible for deciding what "already right"
        means (e.g. same inode for hardlinks, size+mtime match for copies)."""
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
    ) -> bool:
        if dst.exists():
            if dst.samefile(src):
                if verbose:
                    log.info("Target '%s' already linked", dst.name)
                return False
            log.info("Replacing '%s' → '%s'", src.name, dst.name)
            if dry_run:
                log.info("DELETE %s", dst)
            else:
                dst.unlink()
        if dry_run:
            log.info("LINK   %s", dst)
        else:
            log.info("Linking '%s' → '%s'", src.name, dst.name)
            dst.hardlink_to(src)
        return True
