from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .discover import FlatDiscoverer
from .jellyfin import JellyfinLibraryReader, JellyfinLibraryWriter
from .library import (
    ACCEPTED_VIDEO_SUFFIXES,
    CollectingReporter,
    FileEvent,
    IgnoredEntry,
    LibraryReader,
    LibraryWriter,
    LoggingReporter,
    MovieClash,
    Reporter,
    dedupe_drops,
)
from .materializer import FileMaterializer, HardlinkMaterializer, MoveMaterializer
from .planner import Planner
from .plex import PlexLibraryReader, PlexLibraryWriter
from .realize import Realizer, RealizeStats

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


@dataclass
class LibraryStats:
    movies_total: int = 0
    movies_processed: int = 0
    items_removed: int = 0
    items_linked: int = 0
    movie_items_removed: int = 0
    ignored: list[IgnoredEntry] = field(default_factory=list)
    strays_in_target: list[str] = field(default_factory=list)
    events: list[FileEvent] = field(default_factory=list)
    clashes: list[MovieClash] = field(default_factory=list)


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
    with the same value is the lint/normalize mode. Returns None and logs an
    error if a needed format can't be determined.
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

    resolved = _resolve_formats(source_path, source_format, target_format)
    if resolved is None:
        return 1
    source_short, target_short = resolved

    source_reader_cls, _ = _LIBRARY_TYPES[source_short]
    _, target_writer_cls = _LIBRARY_TYPES[target_short]
    source_reader = source_reader_cls(source_path)
    target_writer = target_writer_cls(target_path)

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

    if not source_reader.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source_reader.base_dir)
        return 1

    if not target_writer.base_dir.is_dir():
        if create:
            target_writer.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target_writer.base_dir)
            return 1

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

    realize_stats = RealizeStats()
    if plan.folder_clashes:
        # Match pre-0.3 behaviour: log the clashes and skip the whole sync.
        # Without this guard a partial sync could leave the target in a
        # half-translated state when the user expected a hard failure.
        for fc in plan.folder_clashes:
            quoted = [f"'{s}'" for s in fc.source_folder_names]
            log.error(
                "Conflicting folders: %s → '%s'",
                ", ".join(quoted),
                fc.target_folder_name,
            )
        log.info("You have to solve the conflicts first to proceed")
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

    return 0


# ---------------------------------------------------------------------------
# diff: read-only comparison of source and target
# ---------------------------------------------------------------------------


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
    movies_only_in_source: tuple[MovieOnlyInSource, ...] = ()
    movies_only_in_target: tuple[str, ...] = ()
    differing_movies: tuple[DiffEntry, ...] = ()
    drops: tuple = ()
    ignored: tuple[IgnoredEntry, ...] = ()

    @property
    def has_differences(self) -> bool:
        return bool(
            self.movies_only_in_source
            or self.movies_only_in_target
            or self.differing_movies
        )


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
    import sys

    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    out = out or sys.stdout
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    resolved = _resolve_formats(source_path, source_format, target_format)
    if resolved is None:
        return 2
    source_short, target_short = resolved

    source_reader_cls, _ = _LIBRARY_TYPES[source_short]
    _, target_writer_cls = _LIBRARY_TYPES[target_short]
    source_reader = source_reader_cls(source_path)
    target_writer = target_writer_cls(target_path)

    if not source_reader.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source_reader.base_dir)
        return 2
    if not target_writer.base_dir.is_dir():
        log.error("Target directory '%s' does not exist", target_writer.base_dir)
        return 2

    # 0.3 pipeline: Planner.plan() + compare(plan). The reporter
    # accumulates translation drops while the Planner walks the source;
    # compare() doesn't observe drops (it only reads the target), so we
    # stitch them onto the DiffResult afterwards.
    from .compare import compare as _compare_plan

    reporter = CollectingReporter()
    planner = Planner(
        reader=source_reader,
        writer=target_writer,
        reporter=reporter,
    )
    plan = planner.plan()
    result = _compare_plan(plan)
    result.drops = tuple(reporter.drops)

    if as_json:
        from .json_output import write_diff_json

        write_diff_json(out, result, source_short, target_short, source_path, target_path)
    else:
        _print_diff(result, source_short, target_short, source_path, target_path, out)
    return 1 if result.has_differences else 0


def _print_diff(
    result: DiffResult,
    source_short: str,
    target_short: str,
    source_path: pathlib.Path,
    target_path: pathlib.Path,
    out,
) -> None:
    print(
        f"Comparing source '{source_path}' ({source_short.capitalize()}) "
        f"against target '{target_path}' ({target_short.capitalize()})",
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

    if result.drops:
        distinct = dedupe_drops(list(result.drops))
        print(f"Translation losses ({len(distinct)} distinct):", file=out)
        for d in distinct:
            key = f"{d.key}=" if d.key else ""
            print(f"  ! {d.kind} {key}{d.value!r}: {d.reason}", file=out)
        print(file=out)

    if result.ignored:
        print(f"Ignored in source ({len(result.ignored)}):", file=out)
        for i in result.ignored:
            print(f"  ! '{i.path.name}': {i.reason}", file=out)
        print(file=out)

    if not result.has_differences:
        print("In sync. No differences found.", file=out)


# ---------------------------------------------------------------------------
# plan: build a Plan without acting on it
# ---------------------------------------------------------------------------


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
    import sys

    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    out = out or sys.stdout
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    resolved = _resolve_formats(source_path, source_format, target_format)
    if resolved is None:
        return 2
    source_short, target_short = resolved

    source_reader_cls, _ = _LIBRARY_TYPES[source_short]
    _, target_writer_cls = _LIBRARY_TYPES[target_short]
    source_reader = source_reader_cls(source_path)
    target_writer = target_writer_cls(target_path)

    if not source_reader.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source_reader.base_dir)
        return 2
    # The target dir doesn't need to exist for `plan` — the whole point
    # is to ask "what WOULD happen" before any sync sets up the target.

    reporter = CollectingReporter()
    planner = Planner(
        reader=source_reader,
        writer=target_writer,
        reporter=reporter,
    )
    built_plan = planner.plan()

    if as_json:
        from .json_output import write_plan_json

        write_plan_json(out, built_plan, drops=tuple(reporter.drops))
    else:
        _print_plan(built_plan, tuple(reporter.drops), out)
    return 0


def _print_plan(
    built_plan,
    drops: tuple,
    out,
) -> None:
    print(
        f"Plan for source '{built_plan.source_root}' "
        f"({built_plan.source_format.capitalize()}) → target "
        f"'{built_plan.target_root}' ({built_plan.target_format.capitalize()})",
        file=out,
    )
    print(file=out)

    if built_plan.movies:
        print(f"Movies ({len(built_plan.movies)}):", file=out)
        for m in built_plan.movies:
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

    if built_plan.folder_clashes:
        print(f"Folder clashes ({len(built_plan.folder_clashes)}):", file=out)
        for fc in built_plan.folder_clashes:
            srcs = ", ".join(f"'{s}'" for s in fc.source_folder_names)
            print(f"  ! {srcs} → '{fc.target_folder_name}'", file=out)
        print(file=out)

    if built_plan.clashes:
        print(f"Movie clashes ({len(built_plan.clashes)}):", file=out)
        for c in built_plan.clashes:
            srcs = ", ".join(f"'{s}'" for s in c.source_filenames)
            print(
                f"  ! in '{c.movie_folder}': {srcs} → '{c.target_filename}'",
                file=out,
            )
        print(file=out)

    if drops:
        distinct = dedupe_drops(list(drops))
        print(f"Translation losses ({len(distinct)} distinct):", file=out)
        for d in distinct:
            key = f"{d.key}=" if d.key else ""
            print(f"  ! {d.kind} {key}{d.value!r}: {d.reason}", file=out)
        print(file=out)

    if built_plan.ignored:
        print(f"Ignored in source ({len(built_plan.ignored)}):", file=out)
        for i in built_plan.ignored:
            print(f"  ! '{i.path.name}': {i.reason}", file=out)
        print(file=out)

    if not (
        built_plan.movies
        or built_plan.folder_clashes
        or built_plan.clashes
        or built_plan.ignored
    ):
        print("Empty plan. Nothing to sync.", file=out)


def _count_asset_files(asset) -> int:
    return len(asset.files) + sum(_count_asset_files(sf) for sf in asset.subfolders)


# ---------------------------------------------------------------------------
# import: move files from a staging area into a structured library
# ---------------------------------------------------------------------------


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

    resolved = _resolve_formats(source_path, source_format, target_format)
    if resolved is None:
        return 1
    source_short, target_short = resolved

    source_reader_cls, _ = _LIBRARY_TYPES[source_short]
    _, target_writer_cls = _LIBRARY_TYPES[target_short]
    source_reader = source_reader_cls(source_path)
    target_writer = target_writer_cls(target_path)

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

    if not source_reader.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source_reader.base_dir)
        return 1

    if not target_writer.base_dir.is_dir():
        if create:
            target_writer.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target_writer.base_dir)
            return 1

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

    return 0
