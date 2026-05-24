from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Callable, Generator
from dataclasses import dataclass, field

from . import utils
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
    movie_path,
    scan,
    video_path,
)
from .materializer import FileMaterializer, HardlinkMaterializer
from .model import MovieInfo
from .plex import PlexLibraryReader, PlexLibraryWriter

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


def scan_media_library(
    source: LibraryReader,
    target: LibraryWriter,
    *,
    reporter: Reporter | None = None,
    dry_run: bool = False,
    delete: bool = False,
    stats: LibraryStats | None = None,
) -> Generator[tuple[pathlib.Path, pathlib.Path, MovieInfo], None, None]:
    """Iterate over the source library and determine all movie folders.
    Yields a tuple for each movie folder:
        (source: pathlib.Path, destination: pathlib.Path, movie: MovieInfo)
    """
    if source.base_dir == target.base_dir:
        raise ValueError("Can not transfer library into itself")

    reporter = reporter or LoggingReporter()
    stats = stats or LibraryStats()
    movies_to_sync: dict[str, tuple[pathlib.Path, MovieInfo] | None] = {}
    conflicting_source_dirs: dict[str, list[str]] = {}

    for entry, movie in scan(source, ignored=stats.ignored):
        target_name = target.movie_name(movie, reporter)
        if target_name in movies_to_sync:
            if target_name not in conflicting_source_dirs:
                item = movies_to_sync[target_name]
                conflicting_source_dirs[target_name] = [item[0].name] if item else []
            conflicting_source_dirs[target_name].append(entry.name)
            movies_to_sync[target_name] = None
        else:
            movies_to_sync[target_name] = (entry, movie)
        stats.movies_total += 1

    if conflicting_source_dirs:
        for dst, src in conflicting_source_dirs.items():
            quoted = [f"'{s}'" for s in src]
            log.error("Conflicting folders: %s → '%s'", ", ".join(quoted), dst)
        log.info("You have to solve the conflicts first to proceed")
        return

    for target_name, item in movies_to_sync.items():
        if not item:
            continue
        stats.movies_processed += 1
        yield item[0], target.base_dir / target_name, item[1]

    for entry in target.base_dir.iterdir():
        if entry.name not in movies_to_sync:
            stats.strays_in_target.append(entry.name)
            if delete:
                if dry_run:
                    log.info("DELETE %s", entry)
                else:
                    log.info("Removing stray item '%s' in target library", entry.name)
                stats.items_removed += utils.remove(entry, dry_run=dry_run).files
                stats.events.append(
                    FileEvent(action="remove", target=entry, context="library_stray")
                )
            else:
                if not dry_run:
                    log.info("Stray item '%s' found", entry.name)


@dataclass
class AssetStats:
    files_total: int = 0
    files_linked: int = 0
    items_removed: int = 0
    events: list[FileEvent] = field(default_factory=list)


def process_assets_folder(
    source_path: pathlib.Path,
    target_path: pathlib.Path,
    *,
    materializer: FileMaterializer | None = None,
    dry_run: bool = False,
    delete: bool = False,
    verbose: bool = False,
    stats: AssetStats | None = None,
) -> AssetStats:
    if not source_path.is_dir():
        raise ValueError(f"{source_path!s} is not a folder")

    materializer = materializer or HardlinkMaterializer()

    if not target_path.exists():
        if dry_run:
            log.info("MKDIR  %s", target_path)
        else:
            target_path.mkdir(parents=True, exist_ok=True)

    stats = stats or AssetStats()
    synced_items = {}

    for entry in source_path.iterdir():
        dest = target_path / entry.name
        if entry.is_dir():
            process_assets_folder(
                entry,
                dest,
                materializer=materializer,
                delete=delete,
                verbose=verbose,
                stats=stats,
                dry_run=dry_run,
            )
        elif entry.is_file():
            if materializer.materialize(
                entry, dest, dry_run=dry_run, verbose=verbose, events=stats.events,
            ):
                stats.files_linked += 1
            stats.files_total += 1
        synced_items[entry.name] = dest

    if delete and target_path.is_dir():
        for entry in target_path.iterdir():
            if entry.name in synced_items:
                continue
            log.info("Removing stray item '%s' in target folder", entry.name)
            if dry_run:
                log.info("DELETE %s", entry.name)
            stats.items_removed += utils.remove(entry, dry_run=dry_run).files
            stats.events.append(
                FileEvent(action="remove", target=entry, context="asset_stray")
            )

    return stats


@dataclass
class MovieStats:
    videos_total: int = 0
    videos_linked: int = 0
    items_removed: int = 0
    asset_items_total: int = 0
    asset_items_linked: int = 0
    asset_items_removed: int = 0
    loose_files_total: int = 0
    loose_files_linked: int = 0
    events: list[FileEvent] = field(default_factory=list)
    clash: MovieClash | None = None


def _ensure_dir(path: pathlib.Path, *, dry_run: bool) -> None:
    if path.exists():
        return
    if dry_run:
        log.info("MKDIR  %s", path)
    else:
        path.mkdir(parents=True, exist_ok=True)


def _remove_strays(
    target_path: pathlib.Path,
    base_dir: pathlib.Path,
    keep: set[str],
    *,
    dry_run: bool,
    events: list[FileEvent] | None = None,
) -> int:
    if not target_path.is_dir():
        return 0
    removed = 0
    for entry in target_path.iterdir():
        if entry.name in keep:
            continue
        if dry_run:
            log.info("DELETE %s", entry)
        else:
            log.info(
                "Removing stray item '%s' in movie folder '%s'",
                entry.name,
                target_path.relative_to(base_dir),
            )
        removed += utils.remove(entry, dry_run=dry_run).files
        if events is not None:
            events.append(FileEvent(action="remove", target=entry, context="movie_stray"))
    return removed


def process_movie(
    source: LibraryReader,
    target: LibraryWriter,
    source_path: pathlib.Path,
    movie: MovieInfo,
    *,
    materializer: FileMaterializer | None = None,
    reporter: Reporter | None = None,
    dry_run: bool = False,
    delete: bool = False,
    verbose: bool = False,
) -> MovieStats:
    materializer = materializer or HardlinkMaterializer()
    reporter = reporter or LoggingReporter(verbose=verbose)
    target_path = movie_path(target, movie, reporter)

    if verbose:
        log.info("Processing '%s' → '%s'", source_path.name, target_path.name)

    stats = MovieStats()
    videos_to_sync: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}
    assets_to_sync: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}
    loose_to_sync: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}

    for entry in source_path.glob("*"):
        if entry.name.startswith("."):
            # OS/sync-tool junk (.DS_Store, .stversions, …) — skipped in both
            # file and folder form, consistent with historical dot-folder
            # handling.
            log.debug("Ignoring dot-entry '%s'", entry.name)
            continue
        if entry.is_file() and entry.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
            video = source.parse_video(entry)
            dst_video_path = video_path(target, movie, video, reporter)
            if dst_video_path.name in videos_to_sync:
                other_entry, _ = videos_to_sync[dst_video_path.name]
                log.error(
                    "Conflicting video files '%s' and '%s' in movie '%s' "
                    "both target '%s' — skipping movie.",
                    other_entry.name,
                    entry.name,
                    source_path.name,
                    dst_video_path.name,
                )
                return MovieStats(
                    clash=MovieClash(
                        movie_folder=source_path.name,
                        target_filename=dst_video_path.name,
                        source_filenames=(other_entry.name, entry.name),
                    )
                )
            videos_to_sync[dst_video_path.name] = (entry, dst_video_path)
            stats.videos_total += 1
        elif entry.is_file():
            # Loose top-level files (poster, nfo, subtitles, user notes) are
            # synced 1:1 with their original name. Pre-0.2.0 they were
            # silently dropped, which made jellyplex-sync unsafe for
            # migrations.
            loose_to_sync[entry.name] = (entry, target_path / entry.name)
            stats.loose_files_total += 1
        elif entry.is_dir():
            assets_to_sync[entry.name] = (entry, target_path / entry.name)

    _ensure_dir(target_path, dry_run=dry_run)

    for src_video, dst_video in videos_to_sync.values():
        if materializer.materialize(
            src_video, dst_video, dry_run=dry_run, verbose=verbose, events=stats.events,
        ):
            stats.videos_linked += 1

    for src_file, dst_file in loose_to_sync.values():
        if materializer.materialize(
            src_file, dst_file, dry_run=dry_run, verbose=verbose, events=stats.events,
        ):
            stats.loose_files_linked += 1

    if delete:
        keep = set(videos_to_sync) | set(assets_to_sync) | set(loose_to_sync)
        stats.items_removed += _remove_strays(
            target_path, target.base_dir, keep, dry_run=dry_run, events=stats.events,
        )

    for src_asset, dst_asset in assets_to_sync.values():
        s = process_assets_folder(
            src_asset,
            dst_asset,
            materializer=materializer,
            delete=delete,
            verbose=verbose,
            dry_run=dry_run,
        )
        stats.asset_items_total += s.files_total
        stats.asset_items_linked += s.files_linked
        stats.asset_items_removed += s.items_removed
        stats.events.extend(s.events)

    return stats


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

    for src, _, movie in scan_media_library(
        source_reader,
        target_writer,
        reporter=reporter,
        delete=delete,
        dry_run=dry_run,
        stats=lib_stats,
    ):
        s = process_movie(
            source_reader,
            target_writer,
            src,
            movie,
            materializer=materializer,
            reporter=reporter,
            delete=delete,
            verbose=verbose,
            dry_run=dry_run,
        )
        lib_stats.items_linked += s.asset_items_linked + s.videos_linked + s.loose_files_linked
        lib_stats.movie_items_removed += s.asset_items_removed + s.items_removed
        lib_stats.events.extend(s.events)
        if s.clash is not None:
            lib_stats.clashes.append(s.clash)

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

    result = _compute_diff(source_reader, target_writer)
    if as_json:
        from .json_output import write_diff_json

        write_diff_json(out, result, source_short, target_short, source_path, target_path)
    else:
        _print_diff(result, source_short, target_short, source_path, target_path, out)
    return 1 if result.has_differences else 0


def _compute_diff(source: LibraryReader, target: LibraryWriter) -> DiffResult:
    reporter = CollectingReporter()
    ignored: list[IgnoredEntry] = []

    expected: dict[str, set[str]] = {}
    source_folder_for: dict[str, str] = {}
    for source_movie_path, movie in scan(source, ignored=ignored):
        target_movie_name = target.movie_name(movie, reporter)
        source_folder_for[target_movie_name] = source_movie_path.name
        expected_files: set[str] = set()
        for entry in source_movie_path.glob("*"):
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
                video = source.parse_video(entry)
                expected_files.add(target.video_name(movie, video, reporter))
            elif entry.is_file() or entry.is_dir():
                expected_files.add(entry.name)
        expected[target_movie_name] = expected_files

    actual: dict[str, set[str]] = {}
    for entry in target.base_dir.iterdir():
        if not entry.is_dir():
            continue
        actual[entry.name] = {sub.name for sub in entry.iterdir()}

    only_source = tuple(
        MovieOnlyInSource(
            source_folder=source_folder_for[name],
            expected_target=name,
        )
        for name in sorted(set(expected) - set(actual))
    )
    only_target = sorted(set(actual) - set(expected))
    differing: list[DiffEntry] = []
    for name in sorted(set(expected) & set(actual)):
        src_only = tuple(sorted(expected[name] - actual[name]))
        tgt_only = tuple(sorted(actual[name] - expected[name]))
        if src_only or tgt_only:
            differing.append(
                DiffEntry(
                    target_movie_name=name,
                    only_in_source=src_only,
                    only_in_target=tgt_only,
                )
            )

    return DiffResult(
        movies_only_in_source=only_source,
        movies_only_in_target=tuple(only_target),
        differing_movies=tuple(differing),
        drops=tuple(reporter.drops),
        ignored=tuple(ignored),
    )


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
