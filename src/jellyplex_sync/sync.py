from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Generator
from dataclasses import dataclass

from . import utils
from .jellyfin import JellyfinLibraryReader, JellyfinLibraryWriter
from .library import (
    ACCEPTED_VIDEO_SUFFIXES,
    LibraryReader,
    LibraryWriter,
    LoggingReporter,
    Reporter,
    movie_path,
    scan,
    video_path,
)
from .materializer import FileMaterializer, HardlinkMaterializer
from .model import MovieInfo
from .plex import PlexLibraryReader, PlexLibraryWriter

log = logging.getLogger(__name__)


_LIBRARY_TYPES: dict[str, tuple[type[LibraryReader], type[LibraryWriter]]] = {
    PlexLibraryReader.shortname(): (PlexLibraryReader, PlexLibraryWriter),
    JellyfinLibraryReader.shortname(): (JellyfinLibraryReader, JellyfinLibraryWriter),
}


@dataclass
class LibraryStats:
    movies_total: int = 0
    movies_processed: int = 0
    items_removed: int = 0


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

    for entry, movie in scan(source):
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
            if delete:
                if dry_run:
                    log.info("DELETE %s", entry)
                else:
                    log.info("Removing stray item '%s' in target library", entry.name)
                    utils.remove(entry)
                stats.items_removed += 1
            else:
                if not dry_run:
                    log.info("Stray item '%s' found", entry.name)


@dataclass
class AssetStats:
    files_total: int = 0
    files_linked: int = 0
    items_removed: int = 0


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
                verbose=verbose,
                stats=stats,
                dry_run=dry_run,
            )
        elif entry.is_file():
            if materializer.materialize(entry, dest, dry_run=dry_run, verbose=verbose):
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
            else:
                utils.remove(entry)
            stats.items_removed += 1

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
            utils.remove(entry)
        removed += 1
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
    reporter = reporter or LoggingReporter()
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
                log.error("Conflicting video file '%s'. Aborting.", entry.name)
                return MovieStats()
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
        if materializer.materialize(src_video, dst_video, dry_run=dry_run, verbose=verbose):
            stats.videos_linked += 1

    for src_file, dst_file in loose_to_sync.values():
        if materializer.materialize(src_file, dst_file, dry_run=dry_run, verbose=verbose):
            stats.loose_files_linked += 1

    if delete:
        keep = set(videos_to_sync) | set(assets_to_sync) | set(loose_to_sync)
        stats.items_removed += _remove_strays(
            target_path, target.base_dir, keep, dry_run=dry_run,
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


def sync(
    source: str,
    target: str,
    *,
    dry_run: bool = False,
    delete: bool = False,
    create: bool = False,
    verbose: bool = False,
    debug: bool = False,
    convert_to: str | None = None,
    reporter: Reporter | None = None,
    materializer: FileMaterializer | None = None,
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    reporter = reporter or LoggingReporter()
    materializer = materializer or HardlinkMaterializer()
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    if not convert_to or convert_to == "auto":
        source_type = guess_library_type(source_path)
        if not source_type:
            log.error(
                "Unable to determine source library type, please provide --convert-to option"
            )
            return 1
        source_short = source_type.shortname()
        target_short = "plex" if source_short == "jellyfin" else "jellyfin"
    elif convert_to in _LIBRARY_TYPES:
        target_short = convert_to
        source_short = "plex" if target_short == "jellyfin" else "jellyfin"
    else:
        raise ValueError("Unknown value for parameter 'convert_to'")

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

    lib_stats = LibraryStats()
    items_linked = 0
    items_removed = 0

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
        items_linked += s.asset_items_linked + s.videos_linked + s.loose_files_linked
        items_removed += s.asset_items_removed + s.items_removed

    items_removed += lib_stats.items_removed

    summary = (
        f"Summary: {lib_stats.movies_processed} of {lib_stats.movies_total} movies synced, "
        f"{items_linked} files updated, "
        f"{items_removed} files removed."
    )
    log.info(summary)

    return 0
