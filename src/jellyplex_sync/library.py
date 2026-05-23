from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from .model import MovieInfo, VideoInfo

log = logging.getLogger(__name__)


ACCEPTED_VIDEO_SUFFIXES = {".mkv", ".m4v"}
RESOLUTION_PATTERN = re.compile(r"\d{3,4}[pi]$")


# ---------------------------------------------------------------------------
# Reporter: how Writers tell the caller about lossy decisions
# ---------------------------------------------------------------------------


@dataclass
class Drop:
    kind: Literal["label", "attribute"]
    key: str | None
    value: str
    reason: str


def dedupe_drops(drops: list[Drop] | tuple[Drop, ...]) -> list[Drop]:
    """Collapse drops with identical (kind, key, value, reason) to one,
    preserving first-occurrence order. Use at display time — the
    Reporter itself stays lossless so a caller that wants per-file
    multiplicity can still get it."""
    seen: set[tuple[str, str | None, str, str]] = set()
    out: list[Drop] = []
    for d in drops:
        sig = (d.kind, d.key, d.value, d.reason)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(d)
    return out


class DropError(ValueError):
    """Raised by StrictReporter when the Writer reports a Drop."""


@runtime_checkable
class Reporter(Protocol):
    def drop(self, drop: Drop) -> None: ...
    def info(self, message: str) -> None: ...


class LoggingReporter:
    """Logs drops at warning level and keeps going. The default mode."""

    def drop(self, drop: Drop) -> None:
        log.warning(
            "dropped %s %s=%r: %s",
            drop.kind,
            drop.key or "",
            drop.value,
            drop.reason,
        )

    def info(self, message: str) -> None:
        log.info(message)


class StrictReporter:
    """Raises DropError on the first Drop. Use when callers want sync
    to abort rather than silently lose information."""

    def drop(self, drop: Drop) -> None:
        key = f"{drop.key}=" if drop.key else ""
        raise DropError(f"{drop.kind} {key}{drop.value!r}: {drop.reason}")

    def info(self, message: str) -> None:
        log.info(message)


@dataclass
class CollectingReporter:
    """Accumulates drops and info messages for later inspection.
    Used by report-only flows like the planned `--diff` mode."""

    drops: list[Drop] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def drop(self, drop: Drop) -> None:
        self.drops.append(drop)

    def info(self, message: str) -> None:
        self.messages.append(message)


# ---------------------------------------------------------------------------
# Reader / Writer protocols
# ---------------------------------------------------------------------------


class LibraryReader(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def parse_movie(self, path: pathlib.Path) -> MovieInfo | None: ...

    def parse_video(self, path: pathlib.Path) -> VideoInfo: ...


class LibraryWriter(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def movie_name(self, movie: MovieInfo, reporter: Reporter) -> str: ...

    def video_name(
        self, movie: MovieInfo, video: VideoInfo, reporter: Reporter
    ) -> str: ...


def movie_path(writer: LibraryWriter, movie: MovieInfo, reporter: Reporter) -> pathlib.Path:
    return writer.base_dir / writer.movie_name(movie, reporter)


def video_path(
    writer: LibraryWriter,
    movie: MovieInfo,
    video: VideoInfo,
    reporter: Reporter,
) -> pathlib.Path:
    return movie_path(writer, movie, reporter) / writer.video_name(movie, video, reporter)


@dataclass
class IgnoredEntry:
    """A top-level entry in the source library that the scanner skipped.

    Surfaced in the sync summary and the diff output so a user planning a
    migration can see what would NOT be carried over before deleting the
    source.
    """

    path: pathlib.Path
    reason: str


@dataclass
class FileEvent:
    """A per-file action recorded during sync — the granular companion to
    the aggregate counters in LibraryStats.

    `action` is the verb regardless of dry-run vs real-run; the run-level
    `dry_run` flag distinguishes "did" from "would". This keeps jq filters
    portable between the two modes.

    `source` is None for `remove` (no source — the file is being deleted).
    `context` is set only for `remove` to say which scope the stray came
    from: "library_stray" | "movie_stray" | "asset_stray".
    """

    action: str  # "link" | "replace" | "skip" | "remove"
    target: pathlib.Path
    source: pathlib.Path | None = None
    context: str | None = None


def scan(
    reader: LibraryReader,
    ignored: list[IgnoredEntry] | None = None,
) -> Generator[tuple[pathlib.Path, MovieInfo], None, None]:
    """Walk a library and yield (folder, movie) for every parseable movie folder.

    If `ignored` is provided, top-level entries the scanner skips (stray
    files at the library root, folders whose names don't parse) are
    appended to it.
    """
    for entry in reader.base_dir.glob("*"):
        if not entry.is_dir():
            if ignored is not None:
                ignored.append(IgnoredEntry(entry, "not a directory"))
            continue
        movie = reader.parse_movie(entry)
        if not movie:
            log.warning("Ignoring folder with unparsable name: %s", entry.name)
            if ignored is not None:
                ignored.append(IgnoredEntry(entry, "unparseable folder name"))
            continue
        yield entry, movie
