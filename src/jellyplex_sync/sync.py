"""The use-case layer: sync, diff, plan, and import as callable functions.

Each function is the library-level counterpart of one CLI subcommand:
resolve the endpoints (formats.py), run the Planner, then act — the
Realizer for sync/import, compare() for diff, plain rendering for plan.
Text output lives in report.py, JSON in json_output.py.
"""

from __future__ import annotations

import logging
import pathlib
import sys
from dataclasses import dataclass, field

# Backward-compatible re-exports: these lived here before 0.4.
from .compare import DiffEntry as DiffEntry
from .compare import DiffResult as DiffResult
from .compare import MovieOnlyInSource as MovieOnlyInSource
from .compare import compare
from .discover import FlatDiscoverer
from .formats import guess_library_type as guess_library_type
from .formats import resolve_endpoints
from .json_output import write_diff_json, write_plan_json
from .library import (
    FileEvent,
    IgnoredEntry,
    LoggingReporter,
    MovieClash,
    NullReporter,
    Reporter,
)
from .materializer import FileMaterializer, HardlinkMaterializer, MoveMaterializer
from .planner import Planner
from .realize import Realizer, RealizeStats
from .report import print_diff, print_plan

log = logging.getLogger(__name__)


# Exit codes of sync() and import_media(), documented in the README.
_EXIT_OK = 0
_EXIT_SETUP_ERROR = 1
_EXIT_FOLDER_CLASH = 2
_EXIT_REMOVE_ERRORS = 3


@dataclass
class LibraryStats:
    movies_total: int = 0
    movies_processed: int = 0
    items_removed: int = 0
    items_linked: int = 0
    movie_items_removed: int = 0
    remove_errors: int = 0
    ignored: list[IgnoredEntry] = field(default_factory=list)
    strays_in_target: list[str] = field(default_factory=list)
    events: list[FileEvent] = field(default_factory=list)
    clashes: list[MovieClash] = field(default_factory=list)


def sync(
    source: str,
    target: str,
    *,
    dry_run: bool = False,
    delete: bool = False,
    create: bool = False,
    verbose: bool = False,
    debug: bool = False,
    source_format: str | None = None,
    target_format: str | None = None,
    reporter: Reporter | None = None,
    materializer: FileMaterializer | None = None,
    stats: LibraryStats | None = None,
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    reporter = reporter or LoggingReporter(verbose=verbose)
    materializer = materializer or HardlinkMaterializer()
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    endpoints = resolve_endpoints(source_path, target_path, source_format, target_format)
    if endpoints is None:
        return _EXIT_SETUP_ERROR
    source_reader = endpoints.source_reader
    target_writer = endpoints.target_writer
    source_short = endpoints.source_format
    target_short = endpoints.target_format

    if dry_run:
        log.info("SOURCE %s", source_reader.base_dir)
        log.info("TARGET %s", target_writer.base_dir)
        log.info("CONVERTING %s TO %s", source_short.capitalize(), target_short.capitalize())
    else:
        log.info(
            "Syncing '%s' (%s) to '%s' (%s)",
            source_reader.base_dir,
            source_short.capitalize(),
            target_writer.base_dir,
            target_short.capitalize(),
        )

    if not target_writer.base_dir.is_dir():
        if create:
            target_writer.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target_writer.base_dir)
            return _EXIT_SETUP_ERROR

    lib_stats = stats if stats is not None else LibraryStats()

    # 0.3 pipeline: build the Plan, then apply it. The Planner's default
    # HashFallbackDisambiguator auto-resolves video-level clashes by
    # appending a short hash of the source filename — sync always
    # succeeds, the user gets a warning rather than a hard failure.
    planner = Planner(
        reader=source_reader,
        writer=target_writer,
        reporter=reporter,
    )
    plan = planner.plan()

    rc = _EXIT_OK
    realize_stats = RealizeStats()
    if plan.folder_clashes:
        # Log the clashes and skip the whole sync. Without this guard a
        # partial sync could leave the target in a half-translated state
        # when the user expected a hard failure.
        for fc in plan.folder_clashes:
            quoted = [f"'{s}'" for s in fc.source_folder_names]
            log.error(
                "Conflicting folders: %s → '%s'",
                ", ".join(quoted),
                fc.target_folder_name,
            )
        log.info("Nothing was synced. Rename one side of each conflict, then re-run")
        rc = _EXIT_FOLDER_CLASH
    else:
        Realizer(materializer=materializer).apply(
            plan,
            dry_run=dry_run,
            delete=delete,
            verbose=verbose,
            stats=realize_stats,
        )

    # Map plan + realize stats back onto the caller-visible LibraryStats.
    # movies_total counts every candidate scanned, including clashing
    # folders (which the planner already skipped).
    folder_clash_count = sum(len(fc.source_folder_names) for fc in plan.folder_clashes)
    lib_stats.movies_total += len(plan.movies) + folder_clash_count
    lib_stats.movies_processed += realize_stats.movies_processed
    lib_stats.items_linked += realize_stats.files_linked
    # The legacy split items_removed vs movie_items_removed exists for
    # historical reasons only — every consumer adds them back together.
    # New code lands the whole total in items_removed; movie_items_removed
    # stays at 0.
    lib_stats.items_removed += realize_stats.files_removed
    lib_stats.remove_errors += realize_stats.remove_errors
    lib_stats.ignored.extend(plan.ignored)
    lib_stats.strays_in_target.extend(realize_stats.strays_in_target)
    lib_stats.events.extend(realize_stats.events)
    lib_stats.clashes.extend(plan.clashes)

    total_removed = lib_stats.items_removed + lib_stats.movie_items_removed
    ignored_count = len(lib_stats.ignored)
    stray_count = len(lib_stats.strays_in_target)
    # Strays that were *kept* (only meaningful without --delete; with --delete
    # they were removed and already counted in total_removed).
    strays_kept = stray_count if not delete else 0

    summary = (
        f"Summary: {lib_stats.movies_processed} of {lib_stats.movies_total} movies synced, "
        f"{lib_stats.items_linked} files updated, "
        f"{total_removed} files removed, "
        f"{ignored_count} ignored, "
        f"{strays_kept} strays kept in target, "
        f"{len(lib_stats.clashes)} skipped due to clash."
    )
    log.info(summary)

    if lib_stats.ignored:
        log.info("Ignored root-level item(s) — these are NOT in the target:")
        for item in lib_stats.ignored:
            log.info("  '%s' (%s)", item.path.name, item.reason)

    if strays_kept:
        log.warning(
            "%d item(s) in target are not in the source library. "
            "Pass --delete to remove them (target then becomes a clean mirror).",
            strays_kept,
        )

    if lib_stats.clashes:
        log.warning(
            "%d movie(s) skipped because two or more source files map to the "
            "same target name (lossy P→J translation collapsed disambiguating "
            "labels). Rename one side and re-run.",
            len(lib_stats.clashes),
        )

    if lib_stats.remove_errors:
        log.warning(
            "%d item(s) could not be removed and remain in the target — fix "
            "what blocks them (see the warnings above) and re-run with --delete.",
            lib_stats.remove_errors,
        )
        if rc == _EXIT_OK:
            rc = _EXIT_REMOVE_ERRORS

    return rc


def diff(
    source: str,
    target: str,
    *,
    debug: bool = False,
    source_format: str | None = None,
    target_format: str | None = None,
    out=None,
    as_json: bool = False,
) -> int:
    """Compare a source library against an existing target library.

    Read-only: never touches the filesystem. Exit codes follow the Unix
    `diff` convention — 0 if no differences, 1 if differences are found,
    2 if there's a setup error. With `as_json=True`, emits the machine-
    readable JSON document instead of the human-readable text report.
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    out = out or sys.stdout
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    endpoints = resolve_endpoints(source_path, target_path, source_format, target_format)
    if endpoints is None:
        return 2

    if not endpoints.target_writer.base_dir.is_dir():
        log.error(
            "Target directory '%s' does not exist", endpoints.target_writer.base_dir
        )
        return 2

    # 0.3 pipeline: Planner.plan() + compare(plan). The Plan records the
    # translation drops itself, so compare() carries them into the
    # DiffResult — no reporter side-channel needed.
    planner = Planner(
        reader=endpoints.source_reader,
        writer=endpoints.target_writer,
        reporter=NullReporter(),
    )
    plan = planner.plan()
    result = compare(plan)

    if as_json:
        write_diff_json(
            out,
            result,
            endpoints.source_format,
            endpoints.target_format,
            source_path,
            target_path,
        )
    else:
        print_diff(
            result,
            endpoints.source_format,
            endpoints.target_format,
            source_path,
            target_path,
            out,
        )
    return 1 if result.has_differences else 0


def plan(
    source: str,
    target: str,
    *,
    debug: bool = False,
    source_format: str | None = None,
    target_format: str | None = None,
    out=None,
    as_json: bool = False,
) -> int:
    """Build the Plan a sync would execute and print it. Read-only on
    both source and target. Exit code is 0 if a Plan was produced,
    2 if there was a setup error (paths or format resolution). Clashes
    and translation losses are reported but don't change the exit code
    — they're informative, not failures."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    out = out or sys.stdout
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    endpoints = resolve_endpoints(source_path, target_path, source_format, target_format)
    if endpoints is None:
        return 2
    # The target dir doesn't need to exist for `plan` — the whole point
    # is to ask "what WOULD happen" before any sync sets up the target.

    planner = Planner(
        reader=endpoints.source_reader,
        writer=endpoints.target_writer,
        reporter=NullReporter(),
    )
    built_plan = planner.plan()

    if as_json:
        write_plan_json(out, built_plan)
    else:
        print_plan(built_plan, out)
    return 0


def import_media(
    source: str,
    target: str,
    *,
    dry_run: bool = False,
    create: bool = False,
    verbose: bool = False,
    debug: bool = False,
    source_format: str | None = None,
    target_format: str | None = None,
    reporter: Reporter | None = None,
    materializer: FileMaterializer | None = None,
    stats: LibraryStats | None = None,
) -> int:
    """Import video files from a staging area into a structured library.

    Unlike `sync`, this uses `FlatDiscoverer` (groups by filename
    parsing, not folder structure) and defaults to `MoveMaterializer`
    (copy + delete source). The source can be a flat dump of video
    files, a partially organised directory tree, or a mix.

    Does not touch existing content in the target — it only adds.
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    reporter = reporter or LoggingReporter(verbose=verbose)
    materializer = materializer or MoveMaterializer()
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    endpoints = resolve_endpoints(source_path, target_path, source_format, target_format)
    if endpoints is None:
        return _EXIT_SETUP_ERROR
    source_reader = endpoints.source_reader
    target_writer = endpoints.target_writer
    source_short = endpoints.source_format
    target_short = endpoints.target_format

    if dry_run:
        log.info("SOURCE %s (staging)", source_reader.base_dir)
        log.info("TARGET %s", target_writer.base_dir)
        log.info("IMPORTING %s → %s", source_short.capitalize(), target_short.capitalize())
    else:
        log.info(
            "Importing from '%s' (%s) into '%s' (%s)",
            source_reader.base_dir,
            source_short.capitalize(),
            target_writer.base_dir,
            target_short.capitalize(),
        )

    if not target_writer.base_dir.is_dir():
        if create:
            target_writer.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target_writer.base_dir)
            return _EXIT_SETUP_ERROR

    lib_stats = stats if stats is not None else LibraryStats()

    planner = Planner(
        reader=source_reader,
        writer=target_writer,
        discoverer=FlatDiscoverer(source_reader),
        reporter=reporter,
    )
    plan = planner.plan()

    realize_stats = RealizeStats()
    Realizer(materializer=materializer).apply(
        plan,
        dry_run=dry_run,
        delete=False,
        verbose=verbose,
        stats=realize_stats,
    )

    lib_stats.movies_total += len(plan.movies)
    lib_stats.movies_processed += realize_stats.movies_processed
    lib_stats.items_linked += realize_stats.files_linked
    lib_stats.ignored.extend(plan.ignored)
    lib_stats.events.extend(realize_stats.events)
    lib_stats.clashes.extend(plan.clashes)

    verb = "moved" if isinstance(materializer, MoveMaterializer) else "copied"
    summary = (
        f"Summary: {lib_stats.movies_processed} movies imported, "
        f"{lib_stats.items_linked} files {verb}, "
        f"{len(lib_stats.ignored)} ignored, "
        f"{len(lib_stats.clashes)} skipped due to clash."
    )
    log.info(summary)

    if lib_stats.ignored:
        log.info("Ignored item(s) in source (not imported):")
        for item in lib_stats.ignored:
            log.info("  '%s' (%s)", item.path.name, item.reason)

    if lib_stats.clashes:
        log.warning(
            "%d movie(s) skipped because two or more source files map to the "
            "same target name. Rename and re-run.",
            len(lib_stats.clashes),
        )

    return _EXIT_OK
