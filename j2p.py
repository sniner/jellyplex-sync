#!/usr/bin/python3

import argparse
import logging
import pathlib
import re
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional, Set, Tuple


log = logging.getLogger(__name__)


@dataclass
class MovieInfo:
    """Metadata for the whole movie"""
    title: str
    year: Optional[str] = None
    provider: Optional[str] = None
    movie_id: Optional[str] = None

@dataclass
class VideoInfo:
    """Metadata for a single video file"""
    extension: str
    edition: Optional[str] = None
    resolution: Optional[str] = None
    tags: Optional[Set[str]] = None


RESOLUTION_PATTERN = re.compile(r"\d{3,4}[pi]")

JELLYFIN_ID_PATTERN = re.compile(r"\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]")
JELLYFIN_MOVIE_PATTERNS = [
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)\s* - \s*\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)\s+\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)$"),
    re.compile(r"^(?P<title>.+?)\s+\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)$"),
]

PLEX_MOVIE_PATTERN = re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)")
PLEX_META_BLOCK_PATTERN = re.compile(r"(\{([A-Za-z]+)-([^}]+)\})")
PLEX_META_INFO_PATTERN = re.compile(r"(\[([^]]+)\])")
PLEX_METADATA_PROVIDER = {"imdb", "tmdb", "tvdb"}

ACCEPTED_VIDEO_SUFFIXES = {".mkv", ".m4v"}

RESOLUTION_TABLE = [
    re.compile(r"4k"),
    re.compile(r"BD"),
    re.compile(r"DVD"),
    RESOLUTION_PATTERN,
]


class MediaLibrary(ABC):
    def __init__(self, base_dir: pathlib.Path):
        self.base_dir = base_dir

    @abstractmethod
    def movie_name(self, movie: MovieInfo) -> str:
        ...

    def movie_path(self, movie: MovieInfo) -> pathlib.Path:
        return self.base_dir / self.movie_name(movie)

    @abstractmethod
    def video_name(self, movie: MovieInfo, video: VideoInfo) -> str:
        ...

    def video_path(self, movie: MovieInfo, video: VideoInfo) -> pathlib.Path:
        return self.movie_path(movie) / self.video_name(movie, video)

    @abstractmethod
    def parse_movie_path(self, path: pathlib.Path) -> Optional[MovieInfo]:
        ...

    @abstractmethod
    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        ...

    def scan(self) -> Generator[Tuple[pathlib.Path, MovieInfo], None, None]:
        for entry in self.base_dir.glob("*"):
            if not entry.is_dir():
                continue

            movie = self.parse_movie_path(entry)
            if not movie:
                log.warning("Ignoring folder with unparsable name: %s", entry.name)
                continue

            yield entry, movie


class JellyfinLibrary(MediaLibrary):
    def parse_movie_path(self, path: pathlib.Path) -> Optional[MovieInfo]:
        name = path.name
        for regex in JELLYFIN_MOVIE_PATTERNS:
            match = regex.match(name)
            if match:
                title = match.group("title").strip()
                year = match.group("year") if "year" in match.groupdict() else None
                provider_id = match.group("provider_id") if "provider_id" in match.groupdict() else None
                provider = movie_id = None
                if provider_id:
                    provider, movie_id = provider_id.split("-", 1)
                    provider = provider.rstrip("id")
                return MovieInfo(title=title, year=year, provider=provider, movie_id=movie_id)
        return None

    def movie_name(self, movie: MovieInfo) -> str:
        parts = [movie.title]
        if movie.year:
            parts.append(f"({movie.year})")
        if movie.provider and movie.movie_id:
            parts.append(f"[{movie.provider}id-{movie.movie_id}]")
        return " ".join(parts)

    def video_name(self, movie: MovieInfo, video: VideoInfo) -> str:
        parts = [self.movie_name(movie)]
        if video.edition:
            parts.append(f"- {video.edition}")
        return f"{' '.join(parts)}{video.extension}"

    @staticmethod
    def _map_edition_or_resolution(text: str) -> Tuple[Optional[str], Optional[str]]:
        """Parses a text label from a filename and returns a resolution if
        matched (e.g., BD, 4K); otherwise, treats it as a custom edition
        (e.g., Director's Cut). This reflects a personal naming convention.
        """
        for regex in RESOLUTION_TABLE:
            match = regex.match(text)
            if match:
                return None, text
        return text, None

    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        base_name = path.stem
        parts = base_name.split(" - ")  # <spc><dash><spc> is required by Jellyfin
        if len(parts) > 1:
            # Do no take the media id for an edition
            if JELLYFIN_ID_PATTERN.match(parts[-1]):
                return VideoInfo(
                    extension=path.suffix,
                )
            else:
                possible_edition = parts[-1].strip().lstrip("[").rstrip("]")
                edition, res = self._map_edition_or_resolution(possible_edition)
                return VideoInfo(
                    extension=path.suffix,
                    edition=edition,
                    resolution=res,
                )
        return None


class PlexLibrary(MediaLibrary):
    def movie_name(self, movie: MovieInfo) -> str:
        parts = [movie.title]
        if movie.year:
            parts.append(f"({movie.year})")
        if movie.provider and movie.movie_id:
            parts.append(f"{{{movie.provider}-{movie.movie_id}}}")
        return " ".join(parts)

    def video_name(self, movie: MovieInfo, video: VideoInfo) -> str:
        parts = [self.movie_name(movie)]
        if video.edition:
            parts.append(f"{{edition-{video.edition}}}")
        if video.resolution:
            parts.append(f"[{video.resolution}]")
        return f"{' '.join(parts)}{video.extension}"

    def _parse_meta_blocks(self, name: str) -> Generator[Tuple[str, str, str], None, None]:
        # Find all '{KEY-VALUE}' instances
        for blk, key, val in PLEX_META_BLOCK_PATTERN.findall(name):
            yield key, val, blk

    def _parse_info_blocks(self, name: str) -> Generator[Tuple[str, str], None, None]:
        # Find all '[METADATA]' instances
        for blk, info in PLEX_META_INFO_PATTERN.findall(name):
            yield info, blk

    def parse_movie_path(self, path: pathlib.Path) -> Optional[MovieInfo]:
        name = path.name

        # Find metadata provider and movie id
        leftover = name
        provider = movie_id = None
        for key, val, blk in self._parse_meta_blocks(name):
            p = key.lower()
            if p in PLEX_METADATA_PROVIDER:
                provider = p.strip()
                movie_id = val.strip()
            leftover = leftover.replace(blk, "")

        # Remove additional metadata
        for info, blk in self._parse_info_blocks(leftover):
            leftover = leftover.replace(blk, "")

        # Cleanup remaining text
        leftover = re.sub(r"\s+", " ", leftover)
        leftover = leftover.strip()

        # Parse movie title and year
        match = PLEX_MOVIE_PATTERN.match(leftover)
        if match:
            title = match.group("title").strip()
            year = match.group("year") if "year" in match.groupdict() else None
        else:
            title = leftover
            year = None

        return MovieInfo(
            title=title,
            year=year,
            provider=provider,
            movie_id=movie_id
        )

    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        name = path.stem
        leftover = name

        # Find edition
        edition: Optional[str] = None
        for key, val, blk in self._parse_meta_blocks(name):
            if key.lower() == "edition":
                edition = val
            leftover = leftover.replace(blk, "")

        # Find additional metadata
        tags: Set[str] = set()
        resolution: Optional[str] = None
        for info, blk in self._parse_info_blocks(leftover):
            tag = info.strip()
            if RESOLUTION_PATTERN.match(tag):
                resolution = tag
            else:
                tags.add(tag)
            leftover = leftover.replace(blk, "")

        # Cleanup remaining text
        leftover = re.sub(r"\s+", " ", leftover)
        leftover = leftover.strip()

        return VideoInfo(
            edition=edition,
            extension=path.suffix,
            resolution=resolution,
            tags=tags if tags else None,
        )


def remove_item(item: pathlib.Path) -> None:
    if item.is_file() or item.is_symlink():
        item.unlink()
    elif item.is_dir():
        shutil.rmtree(item)


def scan_media_library(
    source: MediaLibrary,
    target: MediaLibrary,
    *,
    delete: bool = False,
) -> Generator[Tuple[pathlib.Path, pathlib.Path, MovieInfo], None, None]:
    """Iterate over the source library and determine all movie folders.
    Yields a tuple for each movie folder:
        (source: pathlib.Path, destination: pathlib.Path, movie: MovieInfo)
    """
    if source is target or source.base_dir == target.base_dir:
        raise ValueError("Can not transfer library into itself")

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

    # If there are any conflicts we bail out now
    if conflicting_source_dirs:
        for dst, src in conflicting_source_dirs.items():
            quoted = [f"'{s}'" for s in src]
            log.error(f"Conflicting folders: {', '.join(quoted)} → '{dst}'")
        log.info("You have to solve the conflicts to proceed")
        return

    # Yield items for sync
    for target_name, item in movies_to_sync.items():
        if not item:
            continue
        yield item[0], target.base_dir / target_name, item[1]

    # Remove stray items in target library
    for entry in target.base_dir.iterdir():
        if entry.name not in movies_to_sync:
            if delete:
                log.info("Removing stray item '%s' in target library", entry.name)
                remove_item(entry)
            else:
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
    delete: bool = False,
    verbose: bool = False,
    stats: Optional[AssetStats] = None,
) -> AssetStats:
    if not source_path.is_dir():
        raise ValueError(f"{source_path!s} is not a folder")

    target_path.mkdir(parents=True, exist_ok=True)

    stats = stats if stats else AssetStats()
    synced_items = {}

    # Hardlink missing files and dive into subfolders
    for entry in source_path.iterdir():
        dest = target_path / entry.name
        if entry.is_dir():
            process_assets_folder(entry, dest, verbose=verbose, stats=stats)
        elif entry.is_file():
            if dest.exists():
                if dest.samefile(entry):
                    if verbose:
                        log.debug("Target file '%s' already exists, skipping", entry.name)
                else:
                    dest.unlink()
                    dest.hardlink_to(entry)
                    stats.files_linked += 1
            else:
                dest.hardlink_to(entry)
                stats.files_linked += 1
            stats.files_total += 1
        synced_items[entry.name] = dest

    if delete:
        # Remove stray items
        for entry in target_path.iterdir():
            if entry.name in synced_items:
                continue
            log.info("Removing stray item '%s' in target folder", entry.name)
            remove_item(entry)
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
    delete: bool = False,
    verbose: bool = False,
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
        elif entry.is_dir():
            dir_name = entry.name
            # TODO: Just a quick fix for selecting and manipulating directories
            if dir_name.startswith("."):
                log.debug("Ignoring asset folder '%s'", dir_name)
                continue
            assets_to_sync[dir_name] = (entry, target_path / dir_name)

    target_path.mkdir(parents=True, exist_ok=True)

    # Hardlink missing video files
    for _video_name, item in videos_to_sync.items():
        if item[1].exists():
            if item[1].samefile(item[0]):
                if verbose:
                    log.info("Target video file '%s' already exists", item[1].name)
                continue
            else:
                log.info("Replacing video file '%s' → '%s'", item[0].name, item[1].name)
                item[1].unlink()
        else:
            log.info("Linking video file '%s' → '%s'", item[0].name, item[1].name)
        item[1].hardlink_to(item[0])
        stats.videos_linked += 1

    if delete:
        # Remove stray items
        for entry in target_path.iterdir():
            if entry.name in videos_to_sync or entry.name in assets_to_sync:
                continue
            log.info("Removing stray item '%s' in movie folder", entry.name)
            remove_item(entry)
            stats.items_removed += 1

    # Sync assets folders
    for _, item in assets_to_sync.items():
        s = process_assets_folder(item[0], item[1], delete=delete, verbose=verbose)
        stats.asset_items_total += s.files_total
        stats.asset_items_linked += s.files_linked
        stats.asset_items_removed += s.items_removed

    return stats


def sync(
    source: str,
    target: str,
    *,
    delete: bool = False,
    create: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    source_lib = JellyfinLibrary(pathlib.Path(source).resolve())
    target_lib = PlexLibrary(pathlib.Path(target).resolve())

    log.info(f"Source library: {source_lib.base_dir}")
    log.info(f"Target library: {target_lib.base_dir}")

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

    for src, _, movie in scan_media_library(source_lib, target_lib, delete=delete):
        s = process_movie(source_lib, target_lib, src, movie, delete=delete, verbose=verbose)
        stat_movies += 1
        stat_items_linked += s.asset_items_linked + s.videos_linked
        stat_items_removed += s.asset_items_removed + s.items_removed

    summary = (
        f"Summary: {stat_movies} movies found, "
        f"{stat_items_linked} files updated, "
        f"{stat_items_removed} files removed."
    )
    logging.info(summary)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Plex compatible media library from a Jellyfin library.")
    parser.add_argument("source", help="Jellyfin media library")
    parser.add_argument("target", help="Plex media library")
    parser.add_argument("--delete", action="store_true", help="Remove stray folders from target library")
    parser.add_argument("--create", action="store_true", help="Create missing target library")
    parser.add_argument("--verbose", action="store_true", help="Show more information messages")
    parser.add_argument("--debug", action="store_true", help="Show debug messages")
    args = parser.parse_args()

    result = 0
    try:
        result = sync(
            args.source,
            args.target,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
        )
    except KeyboardInterrupt:
        log.info("INTERRUPTED")
        result = 10
    except Exception as exc:
        log.error("Exception: %s", exc)
        result = 99
    exit(result)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s: %(asctime)s -- %(message)s",
    )

    # If you want to use it as a CLI tool:
    main()
    # For Unraid 'User Scripts' use that:
    # sync(
    #     "/mnt/media/Movies",
    #     "/mnt/media/Plex/Movies",
    #     create=True,
    #     delete=True,
    # )
