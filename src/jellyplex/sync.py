import logging
import pathlib
import re
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional, Set, Tuple, Type

from .library import (
    ACCEPTED_ASSOCIATED_SUFFIXES,
    ACCEPTED_VIDEO_SUFFIXES,
    MovieInfo,
    VideoInfo,
    MediaLibrary,
)
from .jellyfin import (
    JellyfinLibrary,
)
from .plex import (
    PlexLibrary,
)
import glob as pyglob
from . import utils

log = logging.getLogger(__name__)



@dataclass
class LibraryStats:
    movies_total: int = 0
    movies_processed: int = 0
    items_removed: int = 0


def resolve_movie_folder(source_lib: MediaLibrary, partial_path: str) -> Optional[pathlib.Path]:
    """Resolves a partial path to a valid folder in the source library."""
    path = pathlib.Path(partial_path)

    # If path exists and is absolute or relative to cwd
    if path.exists() and path.is_dir():
        # Check if it is inside source_lib
        try:
            # This checks if path is subpath of source_lib.base_dir
            # We resolve to handle symlinks or relative paths
            if source_lib.base_dir.resolve() in path.resolve().parents or source_lib.base_dir.resolve() == path.resolve():
                return path
        except Exception:
            pass

    # Try matching by folder name
    # This handles Docker path remapping
    folder_name = path.name
    candidate = source_lib.base_dir / folder_name
    if candidate.exists() and candidate.is_dir():
        return candidate

    return None


def scan_media_library(
    source: MediaLibrary,
    target: MediaLibrary,
    *,
    dry_run: bool = False,
    delete: bool = False,
    stats: Optional[LibraryStats] = None,
) -> Generator[Tuple[pathlib.Path, pathlib.Path, MovieInfo], None, None]:
    """Iterate over the source library and determine all movie folders.
    Yields a tuple for each movie folder:
        (source: pathlib.Path, destination: pathlib.Path, movie: MovieInfo)
    """
    if source is target or source.base_dir == target.base_dir:
        raise ValueError("Can not transfer library into itself")

    stats = stats or LibraryStats()
    movies_to_sync: Dict[str, Optional[Tuple[pathlib.Path, MovieInfo]]] = {}
    conflicting_source_dirs: Dict[str, List[str]] = {}

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
            log.error(f"Conflicting folders: {', '.join(quoted)} → '{dst}'")
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
    stats: Optional[AssetStats] = None,
) -> AssetStats:
    if not source_path.is_dir():
        raise ValueError(f"{source_path!s} is not a folder")

    if not target_path.exists():
        if dry_run:
            log.info("MKDIR  %s", target_path)
        else:
            target_path.mkdir(parents=True, exist_ok=True)

    stats = stats if stats else AssetStats()
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


def process_movie(
    source: MediaLibrary,
    target: MediaLibrary,
    source_path: pathlib.Path,
    movie: MovieInfo,
    *,
    dry_run: bool = False,
    delete: bool = False,
    verbose: bool = False,
    update_filenames: bool = False,
) -> MovieStats:
    target_path = target.movie_path(movie)

    if verbose:
        log.info(f"Processing '{source_path.name}' → '{target_path.name}'")

    stats = MovieStats()

    videos_to_sync: Dict[str, Tuple[pathlib.Path, pathlib.Path]] = {}
    assets_to_sync: Dict[str, Tuple[pathlib.Path, pathlib.Path]] = {}

    # Scan for video files and assets
    for entry in source_path.glob("*"):
        if entry.is_file() and entry.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
            video = source.parse_video_path(entry)
            video_path = target.video_path(movie, video or VideoInfo(extension=entry.suffix.lower()))
            video_name = video_path.name
            if video_name in videos_to_sync:
                log.error("Conflicting video file '%s'. Aborting.", entry.name)
                return MovieStats()
            videos_to_sync[video_name] = (entry, video_path)
            stats.videos_total += 1

            # Find associated files
            base_stem = entry.stem
            target_stem = video_path.stem
            # Use glob.escape because filename may contain brackets which are special chars in glob
            for associated_entry in source_path.glob(f"{pyglob.escape(base_stem)}.*"):
                if associated_entry == entry:
                    continue
                # Associated extensions we want to sync
                if associated_entry.suffix.lower() not in ACCEPTED_ASSOCIATED_SUFFIXES:
                    continue

                # Construct target name: replace base_stem with target_stem
                # Example: Movie.mkv -> Movie.en.srt
                # Target:  Movie-Edition.mkv -> Movie-Edition.en.srt
                suffix_part = associated_entry.name[len(base_stem):]
                target_associated_name = f"{target_stem}{suffix_part}"
                target_associated_path = target_path / target_associated_name

                if target_associated_name in assets_to_sync:
                    # Should not happen usually given unique mapping
                    continue

                assets_to_sync[target_associated_name] = (associated_entry, target_associated_path)

        elif entry.is_dir():
            dir_name = entry.name
            # TODO: Just a quick fix for selecting and manipulating directories
            if dir_name.startswith("."):
                log.debug("Ignoring asset folder '%s'", dir_name)
                continue
            assets_to_sync[dir_name] = (entry, target_path / dir_name)

    if not target_path.exists():
        if dry_run:
            log.info("MKDIR  %s", target_path)
        else:
            target_path.mkdir(parents=True, exist_ok=True)

    # Pre-scan target directory to build a map of existing inodes
    # This optimizes stale candidate detection by avoiding repeated directory scans
    existing_inodes: Dict[int, pathlib.Path] = {}
    if target_path.exists():
        for candidate in target_path.iterdir():
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in ACCEPTED_VIDEO_SUFFIXES:
                continue
            try:
                existing_inodes[candidate.stat().st_ino] = candidate
            except OSError:
                # File might have been deleted or permission denied
                pass

    # Hardlink missing video files
    for _video_name, item in videos_to_sync.items():
        if item[1].exists():
            if item[1].samefile(item[0]):
                if verbose:
                    log.info("Target video file '%s' already exists", item[1].name)
                continue
            else:
                log.info("Replacing video file '%s' → '%s'", item[0].name, item[1].name)
                if dry_run:
                    log.info("DELETE %s", item[1])
                else:
                    item[1].unlink()
        else:
            # Check if any existing file in the target folder is a hardlink to the source file
            # This happens if the filename has changed (e.g. edition added)
            stale_candidate: Optional[pathlib.Path] = None
            try:
                source_inode = item[0].stat().st_ino
                if source_inode in existing_inodes:
                    stale_candidate = existing_inodes[source_inode]
            except OSError:
                 # Source file might have been removed during processing
                 pass

            if stale_candidate:
                # We found a file that is hardlinked to source but has wrong name
                # Verify if editions match
                intended_video = target.parse_video_path(item[1])
                candidate_video = target.parse_video_path(stale_candidate)

                if intended_video and candidate_video and intended_video.edition == candidate_video.edition:
                    if update_filenames:
                        if dry_run:
                            log.info("RENAME %s -> %s", stale_candidate.name, item[1].name)
                        else:
                            log.info("Renamed '%s' -> '%s'", stale_candidate.name, item[1].name)
                            try:
                                stale_candidate.rename(item[1])
                            except OSError as e:
                                log.error("Failed to rename video file '%s': %s", stale_candidate, e)
                                continue

                        # Rename associated files
                        stale_stem = stale_candidate.stem
                        target_stem = item[1].stem
                        for assoc_file in item[1].parent.iterdir():
                            if assoc_file == stale_candidate or assoc_file == item[1]:
                                continue
                            if not assoc_file.is_file():
                                continue
                            if assoc_file.suffix.lower() not in ACCEPTED_ASSOCIATED_SUFFIXES:
                                continue

                            # Match by stem prefix
                            if assoc_file.name.startswith(stale_stem + "."):
                                suffix_part = assoc_file.name[len(stale_stem):]
                                new_assoc_name = f"{target_stem}{suffix_part}"
                                new_assoc_path = item[1].parent / new_assoc_name

                                if dry_run:
                                    log.info("RENAME %s -> %s", assoc_file.name, new_assoc_name)
                                else:
                                    log.info("Renamed '%s' -> '%s'", assoc_file.name, new_assoc_name)
                                    try:
                                        assoc_file.rename(new_assoc_path)
                                    except OSError as e:
                                        log.warning("Failed to rename associated file '%s': %s", assoc_file.name, e)

                        # Remove from inode map to avoid processing again
                        if source_inode in existing_inodes:
                            del existing_inodes[source_inode]
                        continue
                    else:
                        log.warning("Stale hardlink '%s' should be '%s'. Use --update-filenames to fix.", stale_candidate.name, item[1].name)
                        continue

        if dry_run:
            log.info("LINK   %s", item[1])
        else:
            log.info("Linking video file '%s' → '%s'", item[0].name, item[1].name)
            item[1].hardlink_to(item[0])
        stats.videos_linked += 1

    if delete and target_path.is_dir():
        # Remove stray items
        for entry in target_path.iterdir():
            if entry.name in videos_to_sync or entry.name in assets_to_sync:
                continue
            if dry_run:
                log.info("DELETE %s", entry)
            else:
                log.info(
                    "Removing stray item '%s' in movie folder '%s'",
                    entry.name,
                    target_path.relative_to(target.base_dir),
                )
                utils.remove(entry)
            stats.items_removed += 1

    # Sync assets folders and associated files
    for _, item in assets_to_sync.items():
        if item[0].is_dir():
            s = process_assets_folder(item[0], item[1], delete=delete, verbose=verbose, dry_run=dry_run)
            stats.asset_items_total += s.files_total
            stats.asset_items_linked += s.files_linked
            stats.asset_items_removed += s.items_removed
        elif item[0].is_file():
            # Handle associated files
            if item[1].exists():
                if item[1].samefile(item[0]):
                    if verbose:
                        log.debug("Target asset file '%s' already exists, skipping", item[1].name)
                else:
                    if dry_run:
                        log.info("RELINK %s", item[0])
                    else:
                        item[1].unlink()
                        item[1].hardlink_to(item[0])
                    stats.asset_items_linked += 1
            else:
                if dry_run:
                    log.info("LINK   %s", item[1])
                else:
                    item[1].hardlink_to(item[0])
                stats.asset_items_linked += 1
            stats.asset_items_total += 1

    return stats


def determine_library_type(path: pathlib.Path) -> Optional[Type[MediaLibrary]]:
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
    convert_to: Optional[str] = None,
    update_filenames: bool = False,
    partial_path: Optional[str] = None,
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)

    if not convert_to or convert_to == "auto":
        source_type = determine_library_type(source_path)
        if not source_type:
            log.error("Unable to determine source library type, please provide --convert-to option")
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
        log.info("CONVERTING %s TO %s", source_lib.shortname().capitalize(), target_lib.shortname().capitalize())
    else:
        log.info("Syncing '%s' (%s) to '%s' (%s)",
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

    stat_movies: int = 0
    stat_items_linked: int = 0
    stat_items_removed: int = 0
    lib_stats = LibraryStats()

    if partial_path:
        # Partial sync logic
        movie_folder = resolve_movie_folder(source_lib, partial_path)
        if not movie_folder:
            log.error(f"Could not resolve movie folder for partial path: {partial_path}")
            return 1

        movie_info = source_lib.parse_movie_path(movie_folder)
        if not movie_info:
            log.warning(f"Could not parse movie info from folder: {movie_folder}")
            # We skip this as we cannot process it without parsed info
        else:
            s = process_movie(
                source_lib,
                target_lib,
                movie_folder,
                movie_info,
                delete=delete,
                verbose=verbose,
                dry_run=dry_run,
                update_filenames=update_filenames,
            )
            stat_movies += 1
            stat_items_linked += s.asset_items_linked + s.videos_linked
            stat_items_removed += s.asset_items_removed + s.items_removed
    else:
        for src, _, movie in scan_media_library(source_lib, target_lib, delete=delete, dry_run=dry_run, stats=lib_stats):
            s = process_movie(
                source_lib,
                target_lib,
                src,
                movie,
                delete=delete,
                verbose=verbose,
                dry_run=dry_run,
                update_filenames=update_filenames,
            )
            stat_movies += 1
            stat_items_linked += s.asset_items_linked + s.videos_linked
            stat_items_removed += s.asset_items_removed + s.items_removed

        stat_items_removed += lib_stats.items_removed

    summary = (
        f"Summary: {stat_movies} movies found, "
        f"{stat_items_linked} files updated, "
        f"{stat_items_removed} files removed."
    )
    logging.info(summary)

    return 0
