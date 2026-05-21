from __future__ import annotations

import logging
import pathlib
import re
from collections.abc import Generator
from dataclasses import dataclass

from . import utils
from .jellyfin import (
    JellyfinLibrary,
)
from .library import (
    ACCEPTED_VIDEO_SUFFIXES,
    MediaLibrary,
    MovieInfo,
)
from .plex import (
    PlexLibrary,
)

log = logging.getLogger(__name__)


@dataclass
class LibraryStats:
    movies_total: int = 0
    movies_processed: int = 0
    items_removed: int = 0


def scan_media_library(
    source: MediaLibrary,
    target: MediaLibrary,
    *,
    dry_run: bool = False,
    delete: bool = False,
    stats: LibraryStats | None = None,
) -> Generator[tuple[pathlib.Path, pathlib.Path, MovieInfo], None, None]:
    """Iterate over the source library and determine all movie folders.
    Yields a tuple for each movie folder:
        (source: pathlib.Path, destination: pathlib.Path, movie: MovieInfo)
    """
    if source is target or source.base_dir == target.base_dir:
        raise ValueError("Can not transfer library into itself")

    stats = stats or LibraryStats()
    movies_to_sync: dict[str, tuple[pathlib.Path, MovieInfo] | None] = {}
    conflicting_source_dirs: dict[str, list[str]] = {}

    # Inspect source libary for movie folders to sync
    for entry, movie in source.scan():
        target_name = target.movie_name(movie)
        if target_name in movies_to_sync:
            if target_name not in conflicting_source_dirs:
                item = movies_to_sync[target_name]
                conflicting_source_dirs[target_name] = [item[0].name] if item else []
            conflicting_source_dirs[target_name].append(entry.name)
            movies_to_sync[target_name] = None
        else:
            movies_to_sync[target_name] = (entry, movie)
        stats.movies_total += 1

    # If there are any conflicts we bail out now
    if conflicting_source_dirs:
        for dst, src in conflicting_source_dirs.items():
            quoted = [f"'{s}'" for s in src]
            log.error("Conflicting folders: %s → '%s'", ", ".join(quoted), dst)
        log.info("You have to solve the conflicts first to proceed")
        return

    # Yield items for sync
    for target_name, item in movies_to_sync.items():
        if not item:
            continue
        stats.movies_processed += 1
        yield item[0], target.base_dir / target_name, item[1]

    # Remove stray items in target library
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
    dry_run: bool = False,
    delete: bool = False,
    verbose: bool = False,
    stats: AssetStats | None = None,
) -> AssetStats:
    if not source_path.is_dir():
        raise ValueError(f"{source_path!s} is not a folder")

    if not target_path.exists():
        if dry_run:
            log.info("MKDIR  %s", target_path)
        else:
            target_path.mkdir(parents=True, exist_ok=True)

    stats = stats or AssetStats()
    synced_items = {}

    # Hardlink missing files and dive into subfolders
    for entry in source_path.iterdir():
        dest = target_path / entry.name
        if entry.is_dir():
            process_assets_folder(entry, dest, verbose=verbose, stats=stats, dry_run=dry_run)
        elif entry.is_file():
            if dest.exists():
                if dest.samefile(entry):
                    if verbose:
                        log.debug("Target file '%s' already exists, skipping", entry.name)
                else:
                    if dry_run:
                        log.info("RELINK %s", entry)
                    else:
                        dest.unlink()
                        dest.hardlink_to(entry)
                    stats.files_linked += 1
            else:
                if dry_run:
                    log.info("LINK   %s", dest)
                else:
                    dest.hardlink_to(entry)
                stats.files_linked += 1
            stats.files_total += 1
        synced_items[entry.name] = dest

    if delete and target_path.is_dir():
        # Remove stray items
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


def _ensure_dir(path: pathlib.Path, *, dry_run: bool) -> None:
    if path.exists():
        return
    if dry_run:
        log.info("MKDIR  %s", path)
    else:
        path.mkdir(parents=True, exist_ok=True)


def _link_video(
    source: pathlib.Path,
    target: pathlib.Path,
    *,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Hardlink source to target, replacing any existing file at target.

    Returns True if a (re)link happened, False if target already pointed at source.
    """
    if target.exists():
        if target.samefile(source):
            if verbose:
                log.info("Target video file '%s' already exists", target.name)
            return False
        log.info("Replacing video file '%s' → '%s'", source.name, target.name)
        if dry_run:
            log.info("DELETE %s", target)
        else:
            target.unlink()
    if dry_run:
        log.info("LINK   %s", target)
    else:
        log.info("Linking video file '%s' → '%s'", source.name, target.name)
        target.hardlink_to(source)
    return True


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
    source: MediaLibrary,
    target: MediaLibrary,
    source_path: pathlib.Path,
    movie: MovieInfo,
    *,
    dry_run: bool = False,
    delete: bool = False,
    verbose: bool = False,
) -> MovieStats:
    target_path = target.movie_path(movie)

    if verbose:
        log.info("Processing '%s' → '%s'", source_path.name, target_path.name)

    stats = MovieStats()
    videos_to_sync: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}
    assets_to_sync: dict[str, tuple[pathlib.Path, pathlib.Path]] = {}

    for entry in source_path.glob("*"):
        if entry.is_file() and entry.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
            video = source.parse_video_path(entry)
            video_path = target.video_path(movie, video)
            if video_path.name in videos_to_sync:
                log.error("Conflicting video file '%s'. Aborting.", entry.name)
                return MovieStats()
            videos_to_sync[video_path.name] = (entry, video_path)
            stats.videos_total += 1
        elif entry.is_dir():
            # Skip dotfolders (e.g. .DS_Store, .stversions)
            if entry.name.startswith("."):
                log.debug("Ignoring asset folder '%s'", entry.name)
                continue
            assets_to_sync[entry.name] = (entry, target_path / entry.name)

    _ensure_dir(target_path, dry_run=dry_run)

    for src_video, dst_video in videos_to_sync.values():
        if _link_video(src_video, dst_video, dry_run=dry_run, verbose=verbose):
            stats.videos_linked += 1

    if delete:
        keep = set(videos_to_sync) | set(assets_to_sync)
        stats.items_removed += _remove_strays(
            target_path, target.base_dir, keep, dry_run=dry_run,
        )

    for src_asset, dst_asset in assets_to_sync.values():
        s = process_assets_folder(
            src_asset, dst_asset, delete=delete, verbose=verbose, dry_run=dry_run,
        )
        stats.asset_items_total += s.files_total
        stats.asset_items_linked += s.files_linked
        stats.asset_items_removed += s.items_removed

    return stats


def determine_library_type(path: pathlib.Path) -> type[MediaLibrary] | None:
    plex_hints: int = 0
    jellyfin_hints: int = 0
    for entry in path.rglob("*"):
        if entry.suffix.lower() not in ACCEPTED_VIDEO_SUFFIXES:
            continue
        fname = entry.stem
        # Check for provider id
        if re.search(r"\[[a-z]+id-[^\]]+\]", fname, flags=re.IGNORECASE):
            return JellyfinLibrary
        if re.search(r"\{[a-z]+-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibrary
        # Check for Plex edition
        if re.search(r"\{edition-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibrary
        # Check for hints
        variant = fname.split(" - ")
        if len(variant) > 1 and re.search(r"\(\d{4}\)", variant[-1]) is None:
            jellyfin_hints += 1
        if re.search(r"\[\d{3,4}[pi]\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
        if re.search(r"\[[a-z0-9\.\,]+\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
    if plex_hints > jellyfin_hints:
        return PlexLibrary
    elif jellyfin_hints > plex_hints:
        return JellyfinLibrary
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
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    if not convert_to or convert_to == "auto":
        source_type = determine_library_type(source_path)
        if not source_type:
            log.error(
                "Unable to determine source library type, please provide --convert-to option"
            )
            return 1
        target_type = PlexLibrary if source_type == JellyfinLibrary else JellyfinLibrary
    elif convert_to in (JellyfinLibrary.shortname(), PlexLibrary.shortname()):
        target_type = PlexLibrary if convert_to == PlexLibrary.shortname() else JellyfinLibrary
        source_type = PlexLibrary if target_type == JellyfinLibrary else JellyfinLibrary
    else:
        raise ValueError("Unknown value for parameter 'convert_to'")

    source_lib = source_type(source_path)
    target_lib = target_type(target_path)

    if dry_run:
        log.info("SOURCE %s", source_lib.base_dir)
        log.info("TARGET %s", target_lib.base_dir)
        log.info(
            "CONVERTING %s TO %s",
            source_lib.shortname().capitalize(),
            target_lib.shortname().capitalize(),
        )
    else:
        log.info(
            "Syncing '%s' (%s) to '%s' (%s)",
            source_lib.base_dir,
            source_lib.shortname().capitalize(),
            target_lib.base_dir,
            target_lib.shortname().capitalize(),
        )

    if not source_lib.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source_lib.base_dir)
        return 1

    if not target_lib.base_dir.is_dir():
        if create:
            target_lib.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target_lib.base_dir)
            return 1

    lib_stats = LibraryStats()
    items_linked = 0
    items_removed = 0

    for src, _, movie in scan_media_library(
        source_lib, target_lib, delete=delete, dry_run=dry_run, stats=lib_stats
    ):
        s = process_movie(
            source_lib,
            target_lib,
            src,
            movie,
            delete=delete,
            verbose=verbose,
            dry_run=dry_run,
        )
        items_linked += s.asset_items_linked + s.videos_linked
        items_removed += s.asset_items_removed + s.items_removed

    items_removed += lib_stats.items_removed

    summary = (
        f"Summary: {lib_stats.movies_processed} of {lib_stats.movies_total} movies synced, "
        f"{items_linked} files updated, "
        f"{items_removed} files removed."
    )
    log.info(summary)

    return 0
