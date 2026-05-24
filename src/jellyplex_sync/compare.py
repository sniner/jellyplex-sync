"""Plan-vs.-actual comparison: derive a DiffResult from a Plan.

The classic `diff` subcommand answers "is the target in sync with what
the source would produce?" In the 0.3 pipeline this becomes trivially
expressible: build the Plan (no I/O on target), then compare it to
whatever currently sits on the target filesystem.

The shape of `DiffResult` is preserved from sync.py so the public CLI
output and `--json` schema don't move. `drops` is left empty here —
they belong to the Reporter the caller fed to the Planner; the caller
can stitch them onto the DiffResult if they want them in the document.
"""

from __future__ import annotations

import pathlib

from .plan import Plan
from .sync import DiffEntry, DiffResult, MovieOnlyInSource


def compare(plan: Plan) -> DiffResult:
    """Compare `plan` against the actual contents of `plan.target_root`.

    Pure: reads the target filesystem, returns a DiffResult, mutates
    nothing. Walks one level deep into each movie folder — same depth
    as the pre-0.3 diff implementation."""
    planned_folder_names = {m.target_folder.name for m in plan.movies}
    planned_by_name = {m.target_folder.name: m for m in plan.movies}

    actual: dict[str, set[str]] = {}
    if plan.target_root.is_dir():
        for entry in plan.target_root.iterdir():
            if not entry.is_dir():
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
        tgt_only = tuple(sorted(actual[name] - expected_files))
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
        ignored=tuple(plan.ignored),
    )


def _planned_target_folder(plan: Plan, name: str) -> pathlib.Path | None:
    """Helper: find the absolute target folder for a planned-movie name,
    if any. Convenience for callers that want to print full paths."""
    for m in plan.movies:
        if m.target_folder.name == name:
            return m.target_folder
    return None
