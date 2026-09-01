"""Disambiguation: turn potentially-colliding target names into unique ones.

A Disambiguator is the layer that owns the answer to "what happens when
two source videos in the same movie folder want to write to the same
target filename?" — a real concern for the lossy Plex→Jellyfin
translation, where `[1080p] [remux].mkv` and `[1080p].mkv` both collapse
to `- BD.mkv`.

Translation losses are part of the answer: each accepted video's Drops
are collected per file and returned in the DisambiguationResult, so the
Planner can record them on the PlannedFile. The disambiguator itself
reports nothing — the Plan is the channel.

Two implementations ship today:

- `NaiveDisambiguator` preserves the pre-0.3 behaviour: if two videos
  collide, the whole movie is unresolvable and gets reported as a
  `MovieClash`. Useful for strict modes where the user wants the abort.

- `HashFallbackDisambiguator` is the always-succeeds default: on
  collision, it asks the Writer for the same names again with a short
  hash of the source filename appended. Source filenames are
  filesystem-unique within their folder, so a hash derived from them
  is unique too (modulo a vanishingly small SHA-256 collision).
"""

from __future__ import annotations

import hashlib
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from .library import CollectingReporter, Drop, LibraryWriter, MovieClash
from .model import MovieInfo, VideoInfo
from .plan import DisambiguationNote


@dataclass(frozen=True)
class DisambiguationResult:
    """Outcome of disambiguating one movie's videos.

    `names` maps each accepted source path to its final target filename;
    `notes` records why a name deviates from the Writer's naive output
    (None if the naive name was already unique); `drops` carries the
    translation losses of each accepted video's rendering. `unresolved`
    lists any clashes the disambiguator could not solve — affected
    sources are absent from `names`, `notes`, and `drops`."""

    names: dict[pathlib.Path, str]
    notes: dict[pathlib.Path, DisambiguationNote | None]
    drops: dict[pathlib.Path, tuple[Drop, ...]] = field(default_factory=dict)
    unresolved: tuple[MovieClash, ...] = ()


class Disambiguator(Protocol):
    def disambiguate(
        self,
        movie: MovieInfo,
        videos: list[tuple[VideoInfo, pathlib.Path]],
        writer: LibraryWriter,
        *,
        movie_folder: str,
    ) -> DisambiguationResult: ...


def _render(
    writer: LibraryWriter,
    movie: MovieInfo,
    info: VideoInfo,
    *,
    hash_suffix: str | None = None,
) -> tuple[str, tuple[Drop, ...]]:
    """Render one video name and capture the drops of that rendering."""
    collector = CollectingReporter()
    name = writer.video_name(movie, info, collector, hash_suffix=hash_suffix)
    return name, tuple(collector.drops)


class NaiveDisambiguator:
    """Calls `writer.video_name()` once per video. If two videos produce
    the same name, those videos are excluded from the result and
    reported as a `MovieClash` — matching pre-0.3 behaviour where the
    whole movie was skipped on clash."""

    def disambiguate(
        self,
        movie: MovieInfo,
        videos: list[tuple[VideoInfo, pathlib.Path]],
        writer: LibraryWriter,
        *,
        movie_folder: str,
    ) -> DisambiguationResult:
        rendered: dict[pathlib.Path, str] = {}
        rendered_drops: dict[pathlib.Path, tuple[Drop, ...]] = {}
        for info, source in videos:
            rendered[source], rendered_drops[source] = _render(writer, movie, info)

        groups: dict[str, list[pathlib.Path]] = defaultdict(list)
        for source, name in rendered.items():
            groups[name].append(source)

        names: dict[pathlib.Path, str] = {}
        notes: dict[pathlib.Path, DisambiguationNote | None] = {}
        drops: dict[pathlib.Path, tuple[Drop, ...]] = {}
        unresolved: list[MovieClash] = []
        for name, sources in groups.items():
            if len(sources) == 1:
                names[sources[0]] = name
                notes[sources[0]] = None
                drops[sources[0]] = rendered_drops[sources[0]]
            else:
                unresolved.append(
                    MovieClash(
                        movie_folder=movie_folder,
                        target_filename=name,
                        source_filenames=tuple(s.name for s in sources),
                    )
                )
        return DisambiguationResult(
            names=names, notes=notes, drops=drops, unresolved=tuple(unresolved)
        )


class HashFallbackDisambiguator:
    """On collision, re-renders the colliding videos with a short hash of
    their source filename appended. Source filenames are unique within a
    folder (FS guarantee), so the rendered names are unique modulo a
    SHA-256 collision in the truncated prefix — negligible at the
    default 8 hex chars (~10⁻⁹ for typical folder sizes).

    The hash strategy lives on a per-file `DisambiguationNote` so the
    --json output and `plan` subcommand can surface "this name was
    hashed because of a clash" without the user having to compare names
    by hand."""

    def __init__(self, *, hash_length: int = 8):
        if hash_length < 4 or hash_length > 64:
            raise ValueError("hash_length must be between 4 and 64 hex chars")
        self._hash_length = hash_length

    def disambiguate(
        self,
        movie: MovieInfo,
        videos: list[tuple[VideoInfo, pathlib.Path]],
        writer: LibraryWriter,
        *,
        movie_folder: str,
    ) -> DisambiguationResult:
        naive: dict[pathlib.Path, str] = {}
        naive_drops: dict[pathlib.Path, tuple[Drop, ...]] = {}
        for info, source in videos:
            naive[source], naive_drops[source] = _render(writer, movie, info)

        groups: dict[str, list[tuple[VideoInfo, pathlib.Path]]] = defaultdict(list)
        for info, source in videos:
            groups[naive[source]].append((info, source))

        names: dict[pathlib.Path, str] = {}
        notes: dict[pathlib.Path, DisambiguationNote | None] = {}
        drops: dict[pathlib.Path, tuple[Drop, ...]] = {}
        unresolved: list[MovieClash] = []

        for naive_name, group in groups.items():
            if len(group) == 1:
                _info, source = group[0]
                names[source] = naive_name
                notes[source] = None
                drops[source] = naive_drops[source]
                continue

            rendered: dict[pathlib.Path, str] = {}
            rendered_drops: dict[pathlib.Path, tuple[Drop, ...]] = {}
            for info, source in group:
                h = _short_hash(source.name, self._hash_length)
                rendered[source], rendered_drops[source] = _render(
                    writer, movie, info, hash_suffix=h
                )

            if len(set(rendered.values())) != len(rendered):
                # Hash itself collided — pathological, but still surface
                # it cleanly rather than silently corrupting the plan.
                unresolved.append(
                    MovieClash(
                        movie_folder=movie_folder,
                        target_filename=naive_name,
                        source_filenames=tuple(s.name for _, s in group),
                    )
                )
                continue

            for _info, source in group:
                names[source] = rendered[source]
                notes[source] = DisambiguationNote(
                    strategy="hash_suffix",
                    detail=f"hash from source filename '{source.name}'",
                )
                drops[source] = rendered_drops[source]

        return DisambiguationResult(
            names=names, notes=notes, drops=drops, unresolved=tuple(unresolved)
        )


def _short_hash(s: str, length: int) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]
