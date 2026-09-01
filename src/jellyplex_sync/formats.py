"""Library-format registry, detection, and endpoint setup.

One place answers "which Reader/Writer pair handles this run?": the
registry maps a format shortname to its factories, `guess_library_type`
sniffs a library on disk, and `resolve_endpoints` turns the CLI-level
format arguments into a ready-to-use Reader/Writer pair. Every
subcommand starts its run here.
"""

from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from .jellyfin import JellyfinLibraryReader, JellyfinLibraryWriter
from .library import ACCEPTED_VIDEO_SUFFIXES, LibraryReader, LibraryWriter
from .plex import PlexLibraryReader, PlexLibraryWriter

log = logging.getLogger(__name__)


# Factory pair per shortname. Typed as Callable rather than `type[Protocol]`
# because Protocol classes don't declare __init__, and pyright treats
# `type[LibraryReader](path)` as a zero-arg call. The factory shape is
# what we actually need at the call site: hand it a base_dir, get a
# Reader / Writer back.
_ReaderFactory = Callable[[pathlib.Path], LibraryReader]
_WriterFactory = Callable[[pathlib.Path], LibraryWriter]

_LIBRARY_TYPES: dict[str, tuple[_ReaderFactory, _WriterFactory]] = {
    PlexLibraryReader.shortname(): (PlexLibraryReader, PlexLibraryWriter),
    JellyfinLibraryReader.shortname(): (JellyfinLibraryReader, JellyfinLibraryWriter),
}


def guess_library_type(path: pathlib.Path) -> type[LibraryReader] | None:
    """Best-effort detection of the on-disk library format.

    Returns the matching `LibraryReader` class, or `None` if the heuristic
    can't decide.
    """
    plex_hints: int = 0
    jellyfin_hints: int = 0
    for entry in path.rglob("*"):
        if entry.suffix.lower() not in ACCEPTED_VIDEO_SUFFIXES:
            continue
        fname = entry.stem
        if re.search(r"\[[a-z]+id-[^\]]+\]", fname, flags=re.IGNORECASE):
            return JellyfinLibraryReader
        if re.search(r"\{[a-z]+-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibraryReader
        if re.search(r"\{edition-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibraryReader
        variant = fname.split(" - ")
        if len(variant) > 1 and re.search(r"\(\d{4}\)", variant[-1]) is None:
            jellyfin_hints += 1
        if re.search(r"\[\d{3,4}[pi]\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
        if re.search(r"\[[a-z0-9\.\,]+\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
    if plex_hints > jellyfin_hints:
        return PlexLibraryReader
    elif jellyfin_hints > plex_hints:
        return JellyfinLibraryReader
    return None


def _opposite(short: str) -> str:
    return "plex" if short == "jellyfin" else "jellyfin"


def _resolve_formats(
    source_path: pathlib.Path,
    source_format: str | None,
    target_format: str | None,
) -> tuple[str, str] | None:
    """Pick source and target shortnames from --source-format/--target-format.

    Either side may be "auto" (or None): the source is then sniffed from disk,
    and the target defaults to the opposite of the source. Both sides explicit
    with the same value is the lint/normalize mode.

    Two error channels, deliberately distinct: an explicit format string that
    names no known format raises ValueError — that is a caller bug (the CLI
    can't produce it, argparse restricts the choices). An undetectable
    on-disk layout returns None after logging — that is an environment
    condition the caller handles as a setup error.
    """
    src = source_format if source_format and source_format != "auto" else None
    tgt = target_format if target_format and target_format != "auto" else None

    for label, value in (("source_format", src), ("target_format", tgt)):
        if value is not None and value not in _LIBRARY_TYPES:
            raise ValueError(f"Unknown value for parameter {label!r}: {value!r}")

    if src is None:
        source_type = guess_library_type(source_path)
        if not source_type:
            log.error(
                "Unable to determine source library type, please provide --source-format"
            )
            return None
        src = source_type.shortname()

    if tgt is None:
        tgt = _opposite(src)

    return src, tgt


def _check_source_dir(path: pathlib.Path) -> bool:
    """Log an error and return False unless `path` is an existing directory.

    Must run before format resolution: sniffing a nonexistent path yields
    "unable to determine library type", which sends the user chasing the
    wrong problem when the path is simply mistyped.
    """
    if path.is_dir():
        return True
    if path.exists():
        log.error("Source path '%s' is not a directory", path)
    else:
        log.error("Source directory '%s' does not exist", path)
    return False


@dataclass
class Endpoints:
    """The resolved source/target pair for one run — what every
    subcommand needs before any work can start."""

    source_reader: LibraryReader
    target_writer: LibraryWriter
    source_format: str
    target_format: str


def resolve_endpoints(
    source_path: pathlib.Path,
    target_path: pathlib.Path,
    source_format: str | None,
    target_format: str | None,
) -> Endpoints | None:
    """Common setup for every subcommand: check the source directory,
    resolve both formats, and build the Reader/Writer pair. Returns
    None after logging an error if the source directory is missing or
    the format can't be determined; target-side checks stay with the
    caller because each subcommand treats the target differently.
    """
    if not _check_source_dir(source_path):
        return None
    resolved = _resolve_formats(source_path, source_format, target_format)
    if resolved is None:
        return None
    src, tgt = resolved
    reader_cls, _ = _LIBRARY_TYPES[src]
    _, writer_cls = _LIBRARY_TYPES[tgt]
    return Endpoints(
        source_reader=reader_cls(source_path),
        target_writer=writer_cls(target_path),
        source_format=src,
        target_format=tgt,
    )
