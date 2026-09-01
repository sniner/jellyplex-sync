"""Human-readable text reports for the diff and plan subcommands.

The machine-readable counterpart lives in json_output.py; both render
the same data structures (DiffResult, Plan) and compute nothing.
"""

from __future__ import annotations

import pathlib
from typing import TextIO

from .compare import DiffResult
from .library import Drop, dedupe_drops
from .plan import Plan, PlannedAsset, collect_drops


def print_diff(
    result: DiffResult,
    source_format: str,
    target_format: str,
    source_path: pathlib.Path,
    target_path: pathlib.Path,
    out: TextIO,
) -> None:
    print(
        f"Comparing source '{source_path}' ({source_format.capitalize()}) "
        f"against target '{target_path}' ({target_format.capitalize()})",
        file=out,
    )
    print(file=out)

    if result.movies_only_in_source:
        print(f"Movies only in source ({len(result.movies_only_in_source)}):", file=out)
        for m in result.movies_only_in_source:
            print(f"  + '{m.source_folder}'", file=out)
            print(f"      → would be '{m.expected_target}'", file=out)
        print(file=out)

    if result.movies_only_in_target:
        print(f"Movies only in target ({len(result.movies_only_in_target)}):", file=out)
        for name in result.movies_only_in_target:
            print(f"  - {name}", file=out)
        print(file=out)

    if result.differing_movies:
        print(f"Movies with file differences ({len(result.differing_movies)}):", file=out)
        for entry in result.differing_movies:
            print(f"  ~ {entry.target_movie_name}", file=out)
            for f in entry.only_in_source:
                print(f"      + {f}", file=out)
            for f in entry.only_in_target:
                print(f"      - {f}", file=out)
        print(file=out)

    _print_drops(result.drops, out)

    if result.ignored:
        print(f"Ignored in source ({len(result.ignored)}):", file=out)
        for i in result.ignored:
            print(f"  ! '{i.path.name}': {i.reason}", file=out)
        print(file=out)

    if not result.has_differences:
        print("In sync. No differences found.", file=out)


def print_plan(plan: Plan, out: TextIO) -> None:
    print(
        f"Plan for source '{plan.source_root}' "
        f"({plan.source_format.capitalize()}) → target "
        f"'{plan.target_root}' ({plan.target_format.capitalize()})",
        file=out,
    )
    print(file=out)

    if plan.movies:
        print(f"Movies ({len(plan.movies)}):", file=out)
        for m in plan.movies:
            print(f"  ~ '{m.source_path.name}' → '{m.target_folder.name}'", file=out)
            for v in m.videos:
                line = f"      '{v.source.name}' → '{v.target_name}'"
                if v.disambiguation is not None:
                    line += f"  [{v.disambiguation.strategy}]"
                print(line, file=out)
            if m.loose_files:
                names = ", ".join(f"'{f.target_name}'" for f in m.loose_files)
                print(f"      loose: {names}", file=out)
            for a in m.assets:
                count = _count_asset_files(a)
                suffix = "file" if count == 1 else "files"
                print(f"      assets: '{a.folder_name}' ({count} {suffix})", file=out)
        print(file=out)

    if plan.folder_clashes:
        print(f"Folder clashes ({len(plan.folder_clashes)}):", file=out)
        for fc in plan.folder_clashes:
            srcs = ", ".join(f"'{s}'" for s in fc.source_folder_names)
            print(f"  ! {srcs} → '{fc.target_folder_name}'", file=out)
        print(file=out)

    if plan.clashes:
        print(f"Movie clashes ({len(plan.clashes)}):", file=out)
        for c in plan.clashes:
            srcs = ", ".join(f"'{s}'" for s in c.source_filenames)
            print(
                f"  ! in '{c.movie_folder}': {srcs} → '{c.target_filename}'",
                file=out,
            )
        print(file=out)

    _print_drops(collect_drops(plan), out)

    if plan.ignored:
        print(f"Ignored in source ({len(plan.ignored)}):", file=out)
        for i in plan.ignored:
            print(f"  ! '{i.path.name}': {i.reason}", file=out)
        print(file=out)

    if not (plan.movies or plan.folder_clashes or plan.clashes or plan.ignored):
        print("Empty plan. Nothing to sync.", file=out)


def _print_drops(drops: tuple[Drop, ...], out: TextIO) -> None:
    if not drops:
        return
    distinct = dedupe_drops(list(drops))
    print(f"Translation losses ({len(distinct)} distinct):", file=out)
    for d in distinct:
        key = f"{d.key}=" if d.key else ""
        print(f"  ! {d.kind} {key}{d.value!r}: {d.reason}", file=out)
    print(file=out)


def _count_asset_files(asset: PlannedAsset) -> int:
    return len(asset.files) + sum(_count_asset_files(sf) for sf in asset.subfolders)
