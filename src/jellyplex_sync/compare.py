"""Plan-vs.-actual comparison: derive a DiffResult from a Plan.

The classic `diff` subcommand answers "is the target in sync with what
the source would produce?" In the 0.3 pipeline this becomes trivially
expressible: build the Plan (no I/O on target), then compare it to
whatever currently sits on the target filesystem.

`drops` come straight from the Plan — since the Plan records every
translation loss on its PlannedFiles, the DiffResult can carry them
without a side-channel to the Planner's reporter.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .library import Drop, IgnoredEntry, find_marked
from .plan import Plan, collect_drops


@dataclass
class DiffEntry:
    """Per-movie diff between expected target and actual target contents."""

    target_movie_name: str
    only_in_source: tuple[str, ...] = ()
    only_in_target: tuple[str, ...] = ()


@dataclass
class MovieOnlyInSource:
    """A source movie that has no counterpart in the target. Stores both
    names so the diff output can show the user what they wrote (the
    source folder) AND what it would become on the other side (the
    expected target name) — pre-0.2.2 only the target name was shown,
    which read as a stray for users browsing their source tree."""

    source_folder: str
    expected_target: str


@dataclass
class DiffResult:
    """`marked_in_source` and `marked_in_target` are the folders left out
    of the comparison because they contain the ignore marker. They are
    no difference: a sync leaves them alone as well."""

    movies_only_in_source: tuple[MovieOnlyInSource, ...] = ()
    movies_only_in_target: tuple[str, ...] = ()
    differing_movies: tuple[DiffEntry, ...] = ()
    drops: tuple[Drop, ...] = ()
    ignored: tuple[IgnoredEntry, ...] = ()
    marked_in_source: tuple[pathlib.Path, ...] = ()
    marked_in_target: tuple[pathlib.Path, ...] = ()

    @property
    def has_differences(self) -> bool:
        return bool(
            self.movies_only_in_source or self.movies_only_in_target or self.differing_movies
        )


def compare(plan: Plan) -> DiffResult:
    """Compare `plan` against the actual contents of `plan.target_root`.

    Pure: reads the target filesystem, returns a DiffResult, mutates
    nothing. Walks one level deep into each movie folder — same depth
    as the pre-0.3 diff implementation."""
    planned_folder_names = {m.target_folder.name for m in plan.movies}
    planned_by_name = {m.target_folder.name: m for m in plan.movies}
    marked_folder_names = {
        p.relative_to(plan.target_root).parts[0]
        for p in plan.marked_in_target
        if p != plan.target_root
    }

    actual: dict[str, set[str]] = {}
    if plan.target_root.is_dir():
        for entry in plan.target_root.iterdir():
            if not entry.is_dir() or entry.name in marked_folder_names:
                continue
            actual[entry.name] = {sub.name for sub in entry.iterdir()}

    only_in_source_names = sorted(planned_folder_names - actual.keys())
    only_in_source = tuple(
        MovieOnlyInSource(
            source_folder=planned_by_name[name].source_path.name,
            expected_target=name,
        )
        for name in only_in_source_names
    )

    only_in_target = tuple(sorted(actual.keys() - planned_folder_names))

    differing: list[DiffEntry] = []
    for name in sorted(planned_folder_names & actual.keys()):
        pm = planned_by_name[name]
        expected_files = (
            {pf.target_name for pf in pm.videos}
            | {pf.target_name for pf in pm.loose_files}
            | {a.folder_name for a in pm.assets}
        )
        src_only = tuple(sorted(expected_files - actual[name]))
        # Same rule as the Realizer: an entry that is or holds a marked
        # folder would not be removed, so it is no difference.
        tgt_only = tuple(
            sorted(
                sub
                for sub in actual[name] - expected_files
                if not _holds_marker(plan.target_root / name / sub)
            )
        )
        if src_only or tgt_only:
            differing.append(
                DiffEntry(
                    target_movie_name=name,
                    only_in_source=src_only,
                    only_in_target=tgt_only,
                )
            )

    return DiffResult(
        movies_only_in_source=only_in_source,
        movies_only_in_target=only_in_target,
        differing_movies=tuple(differing),
        drops=collect_drops(plan),
        ignored=tuple(plan.ignored),
        marked_in_source=plan.marked_in_source,
        marked_in_target=plan.marked_in_target,
    )


def _holds_marker(path: pathlib.Path) -> bool:
    return not path.is_symlink() and bool(find_marked(path))
