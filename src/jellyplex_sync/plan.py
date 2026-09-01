"""The Plan: a what-would-happen snapshot produced by the Planner.

A Plan is an immutable, format-neutral description of every file that
would be created in the target library if the sync ran. It is the
single source of truth for what the Realizer should do, what the
Comparator should expect, and what the JSON output reports.

Plans are pure data — building one never touches the target filesystem.
That property is what makes them auditable, serialisable, comparable
across runs, and safely shareable between phases.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Literal

from .library import Drop, FolderClash, IgnoredEntry, MovieClash
from .model import MovieInfo


@dataclass(frozen=True)
class DisambiguationNote:
    """Annotation left by the Disambiguator on a PlannedFile whose name
    deviates from what the Writer would have produced naively. Surfaces
    in --json and in the human-readable `plan` output so the user can
    see why a name looks different."""

    strategy: str
    detail: str


@dataclass(frozen=True)
class PlannedFile:
    """A single file action: link `source` to `target_name` in the
    parent context (the movie folder for videos/loose files, the asset
    folder for asset files). `target_name` is a leaf name — never
    contains a path separator. `drops` are the translation losses of
    rendering this name (filled for videos; loose files and assets
    pass through untranslated)."""

    source: pathlib.Path
    target_name: str
    drops: tuple[Drop, ...] = ()
    disambiguation: DisambiguationNote | None = None


Kind = Literal["video", "asset", "loose"]


@dataclass(frozen=True)
class PlannedAsset:
    """An asset subdirectory inside a movie folder. May contain nested
    asset subfolders. Asset and loose-file names pass through unchanged
    from the source — there's nothing to translate."""

    source: pathlib.Path
    folder_name: str
    files: tuple[PlannedFile, ...] = ()
    subfolders: tuple[PlannedAsset, ...] = ()


@dataclass(frozen=True)
class PlannedMovie:
    """Everything the Planner foresees for one movie folder. Video
    names are guaranteed unique within `videos` (the Disambiguator
    handles collisions before the PlannedMovie is sealed).

    `protected_files` holds the target filenames of videos the
    Disambiguator could NOT resolve. Those videos are absent from
    `videos`, but a previous run may have created a file under the
    collapsed name — the Realizer must not treat it as a stray, or
    `--delete` would destroy data of a movie reported as "skipped"."""

    source_path: pathlib.Path
    target_folder: pathlib.Path
    movie: MovieInfo
    videos: tuple[PlannedFile, ...] = ()
    loose_files: tuple[PlannedFile, ...] = ()
    assets: tuple[PlannedAsset, ...] = ()
    folder_drops: tuple[Drop, ...] = ()
    protected_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    """The full sync plan for one source/target pair.

    `protected_folders` holds the target folder names of source movies
    that could not be planned at all (folder clashes, or every video
    unresolved) — they are absent from `movies`, but the Realizer must
    not treat an existing target folder of that name as a stray."""

    source_root: pathlib.Path
    target_root: pathlib.Path
    source_format: str
    target_format: str
    movies: tuple[PlannedMovie, ...] = ()
    ignored: tuple[IgnoredEntry, ...] = ()
    clashes: tuple[MovieClash, ...] = ()
    folder_clashes: tuple[FolderClash, ...] = ()
    protected_folders: tuple[str, ...] = ()


def collect_drops(plan: Plan) -> tuple[Drop, ...]:
    """Every Drop recorded in the Plan, in plan order: per movie the
    folder drops first, then each video's drops. This is the same
    sequence the Planner's reporter saw while the Plan was built."""
    drops: list[Drop] = []
    for movie in plan.movies:
        drops.extend(movie.folder_drops)
        for video in movie.videos:
            drops.extend(video.drops)
    return tuple(drops)
