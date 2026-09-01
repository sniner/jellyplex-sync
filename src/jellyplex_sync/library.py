from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .model import MovieInfo, VideoInfo

log = logging.getLogger(__name__)


ACCEPTED_VIDEO_SUFFIXES = {".mkv", ".m4v"}


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


class Reporter(Protocol):
    def drop(self, drop: Drop) -> None: ...


class LoggingReporter:
    """Logs drops and keeps going. The default mode.

    Drops go to DEBUG by default — on a real library, every
    `[remux]`, `[amazon]`, `[BluRay]` etc. label that can't translate
    to a Jellyfin version label produces one drop per affected file,
    which drowns the log under normal use. Set `verbose=True` to bump
    drops to INFO so they appear alongside the regular sync output
    (this is what `--verbose` on the CLI does).
    """

    def __init__(self, *, verbose: bool = False) -> None:
        self._drop_level = logging.INFO if verbose else logging.DEBUG

    def drop(self, drop: Drop) -> None:
        log.log(
            self._drop_level,
            "dropped %s %s=%r: %s",
            drop.kind,
            drop.key or "",
            drop.value,
            drop.reason,
        )


class StrictReporter:
    """Raises DropError on the first Drop. Use when callers want sync
    to abort rather than silently lose information."""

    def drop(self, drop: Drop) -> None:
        key = f"{drop.key}=" if drop.key else ""
        raise DropError(f"{drop.kind} {key}{drop.value!r}: {drop.reason}")


@dataclass
class CollectingReporter:
    """Accumulates drops for later inspection."""

    drops: list[Drop] = field(default_factory=list)

    def drop(self, drop: Drop) -> None:
        self.drops.append(drop)


class NullReporter:
    """Discards drops. For rendering steps whose losses are recorded
    elsewhere — e.g. a Writer re-rendering a name whose drops the Plan
    already carries."""

    def drop(self, drop: Drop) -> None:
        pass


# ---------------------------------------------------------------------------
# Reader / Writer protocols
# ---------------------------------------------------------------------------


class LibraryReader(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def parse_movie(self, path: pathlib.Path) -> MovieInfo | None: ...

    def parse_movie_name(self, name: str) -> MovieInfo | None: ...

    def parse_video(self, path: pathlib.Path) -> VideoInfo: ...


class LibraryWriter(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def movie_name(self, movie: MovieInfo, reporter: Reporter) -> str: ...

    def video_name(
        self,
        movie: MovieInfo,
        video: VideoInfo,
        reporter: Reporter,
        *,
        hash_suffix: str | None = None,
    ) -> str: ...


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
class MovieClash:
    """Two or more source files in the same movie folder produce the
    same target video filename — usually because the lossy P→J
    translation drops disambiguating labels (e.g. `[1080p].mkv` and
    `[1080p] [remux].mkv` both collapse to `- BD.mkv`). The movie is
    skipped wholesale (no file gets linked) since we can't pick a
    winner. Surface this in the summary and JSON so the user can rename
    one side and re-run."""

    movie_folder: str
    target_filename: str
    source_filenames: tuple[str, ...]


@dataclass
class FolderClash:
    """Two or more source folders translate to the same target folder
    name. All affected source folders are skipped wholesale — same
    behaviour as MovieClash, just one level up (folder vs. file)."""

    target_folder_name: str
    source_folder_names: tuple[str, ...]


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

    `action="link"` covers every creation, copies included — the verb is
    part of the stable JSON schema, so it stays materializer-neutral in
    meaning even though it reads hardlink-flavoured. A rename (e.g. to
    "create") waits for the next deliberate schema break.
    """

    action: str  # "link" | "replace" | "skip" | "remove"
    target: pathlib.Path
    source: pathlib.Path | None = None
    context: str | None = None
