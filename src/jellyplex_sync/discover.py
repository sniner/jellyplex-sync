"""Source discovery: how candidate movie groups are found on disk.

A `SourceDiscoverer` is the layer that decides what a "movie folder"
looks like in a given source library — without knowing anything about
the format (Plex vs. Jellyfin). It yields `DiscoveredGroup`s; the
Planner then asks the Reader to interpret each one as a movie.

The split exists so the rest of the pipeline can be reused with
different source layouts: today's two-level `<root>/<folder>/<files>`
is `TwoLevelDiscoverer`; future layouts (a flat dump, deeply nested
trees, mixed-content folders) plug in as additional implementations
without touching the Reader, Writer, Planner or Realizer.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .library import ACCEPTED_VIDEO_SUFFIXES, IgnoredEntry, LibraryReader
from .model import MovieInfo


@dataclass(frozen=True)
class DiscoveredGroup:
    """A folder that the discoverer thinks could be a logical unit. The
    Reader will be asked to interpret it; if interpretation fails the
    Planner adds an IgnoredEntry. Contents are pre-classified by the
    discoverer because future discoverers (e.g. MixedDiscoverer) need
    to inspect video files to decide group boundaries — putting the
    classification here keeps that knowledge in one place."""

    source_path: pathlib.Path
    video_files: tuple[pathlib.Path, ...] = ()
    asset_dirs: tuple[pathlib.Path, ...] = ()
    loose_files: tuple[pathlib.Path, ...] = ()


class SourceDiscoverer(Protocol):
    def discover(
        self,
        root: pathlib.Path,
        *,
        ignored: list[IgnoredEntry] | None = None,
    ) -> Iterable[DiscoveredGroup]: ...


class TwoLevelDiscoverer:
    """The classic `<library>/<movie-folder>/<files>` layout. Yields one
    DiscoveredGroup per top-level subdirectory of `root`. Top-level
    files are added to `ignored` because they can't belong to any movie
    in this layout.

    Sorts entries lexicographically so plans are reproducible across
    runs — useful for diffing two plan outputs or for tests."""

    def discover(
        self,
        root: pathlib.Path,
        *,
        ignored: list[IgnoredEntry] | None = None,
    ) -> Iterable[DiscoveredGroup]:
        for entry in sorted(root.glob("*")):
            if not entry.is_dir():
                if ignored is not None:
                    ignored.append(IgnoredEntry(entry, "not a directory"))
                continue
            videos: list[pathlib.Path] = []
            assets: list[pathlib.Path] = []
            loose: list[pathlib.Path] = []
            for child in entry.glob("*"):
                if child.name.startswith("."):
                    # OS/sync junk (.DS_Store, .stversions, ...). Skipped
                    # in both file and folder form, matching legacy behaviour.
                    continue
                if child.is_file() and child.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
                    videos.append(child)
                elif child.is_file():
                    loose.append(child)
                elif child.is_dir():
                    assets.append(child)
            yield DiscoveredGroup(
                source_path=entry,
                video_files=tuple(sorted(videos)),
                asset_dirs=tuple(sorted(assets)),
                loose_files=tuple(sorted(loose)),
            )


def _movie_key(movie: MovieInfo) -> tuple:
    """Hashable grouping key derived from a MovieInfo. Two videos that
    parse to the same title, year, and provider IDs end up in the same
    group — labels and other ephemeral fields are excluded because they
    vary per video, not per movie."""
    return (movie.title, movie.year, tuple(sorted(movie.attributes.items())))


class FlatDiscoverer:
    """Discovers movies from individual video files, regardless of
    directory structure. Every video file under `root` is parsed via
    the supplied Reader to determine which movie it belongs to; files
    with the same title, year, and provider IDs are grouped together.

    Designed for staging-area workflows where video files are dumped
    without the standard one-folder-per-movie layout. Scans
    recursively, so half-sorted structures (files in random
    subdirectories) are handled too.

    Takes a `LibraryReader` because grouping requires format-aware
    parsing — a deliberate trade-off: the TwoLevelDiscoverer is
    format-agnostic (folders are the grouping), but flat sources
    need filename parsing to find group boundaries.

    Loose files and asset directories are not collected — in a flat
    staging area there's no folder to assign them to. The target media
    server can download its own metadata after the sync."""

    def __init__(self, reader: LibraryReader) -> None:
        self._reader = reader

    def discover(
        self,
        root: pathlib.Path,
        *,
        ignored: list[IgnoredEntry] | None = None,
    ) -> Iterable[DiscoveredGroup]:
        groups: dict[tuple, list[pathlib.Path]] = {}
        source_paths: dict[tuple, pathlib.Path] = {}

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() not in ACCEPTED_VIDEO_SUFFIXES:
                if ignored is not None:
                    ignored.append(IgnoredEntry(path, "not a video file"))
                continue

            synthetic_folder = pathlib.Path(root / path.stem)
            movie = self._reader.parse_movie(synthetic_folder)
            if movie is None:
                if ignored is not None:
                    ignored.append(IgnoredEntry(path, "unparseable video filename"))
                continue

            key = _movie_key(movie)
            groups.setdefault(key, []).append(path)
            if key not in source_paths:
                source_paths[key] = synthetic_folder

        for key, video_files in groups.items():
            yield DiscoveredGroup(
                source_path=source_paths[key],
                video_files=tuple(sorted(video_files)),
                asset_dirs=(),
                loose_files=(),
            )
