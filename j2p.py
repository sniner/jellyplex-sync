#!/usr/bin/python3

import argparse
import logging
import pathlib
import re
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional, Tuple


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


MOVIE_PATTERNS = [
    re.compile(r"^(?P<title>.+?) \((?P<year>\d{4})\) - \[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?) \((?P<year>\d{4})\) \[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?) \((?P<year>\d{4})\)$"),
    re.compile(r"^(?P<title>.+?) \[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)$"),
]
JELLYFIN_ID_PATTERN = re.compile(r"\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]")

ACCEPTED_VIDEO_SUFFIXES = set([".mkv", ".m4v"])


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
    def parse_movie_name(self, name: str) -> Optional[MovieInfo]:
        ...

    def parse_movie_path(self, path: pathlib.Path) -> Optional[MovieInfo]:
        return self.parse_movie_name(path.name)

    @abstractmethod
    def parse_video_name(self, name: str) -> Optional[VideoInfo]:
        ...

    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        return self.parse_video_name(path.name)

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
    def parse_movie_name(self, name: str) -> Optional[MovieInfo]:
        for regex in MOVIE_PATTERNS:
            match = regex.match(name)
            if match:
                title = match.group('title').strip()
                year = match.group('year') if 'year' in match.groupdict() else None
                provider_id = match.group('provider_id') if 'provider_id' in match.groupdict() else None
                provider = movie_id = None
                if provider_id:
                    provider, movie_id = provider_id.split('-', 1)
                    provider = provider.rstrip('id')
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

    def parse_video_name(self, name: str) -> Optional[VideoInfo]:
        path = pathlib.Path(name)
        base_name = path.stem
        parts = base_name.split(" - ")
        if len(parts) > 1:
            # Do no take the media id for an edition
            if JELLYFIN_ID_PATTERN.match(parts[-1]):
                return VideoInfo(
                    extension=path.suffix,
                )
            else:
                return VideoInfo(
                    extension=path.suffix,
                    edition=parts[-1].lstrip('[').rstrip(']'),
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
        return f"{' '.join(parts)}{video.extension}"

    def parse_movie_name(self, name: str) -> Optional[MovieInfo]:
        raise NotImplementedError("parse_movie_name not implemented")

    def parse_video_name(self, name: str) -> Optional[VideoInfo]:
        raise NotImplementedError("parse_video_name not implemented")


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


def process_assets_folder(
    source_path: pathlib.Path,
    target_path: pathlib.Path,
    *,
    verbose: bool = False,
):
    if not source_path.is_dir():
        raise ValueError(f"{source_path!s} is not a folder")

    target_path.mkdir(parents=True, exist_ok=True)

    synced_items = {}

    # Hardlink missing files and dive into subfolders
    for entry in source_path.iterdir():
        dest = target_path / entry.name
        if entry.is_dir():
            process_assets_folder(entry, dest, verbose=verbose)
        elif entry.is_file():
            if dest.exists():
                if dest.samefile(entry):
                    if verbose:
                        log.debug("Target file '%s' already exists, skipping", entry.name)
                else:
                    dest.unlink()
                    dest.hardlink_to(entry)
            else:
                dest.hardlink_to(entry)
        synced_items[entry.name] = dest

    # Remove stray items
    for entry in target_path.iterdir():
        if entry.name in synced_items:
            continue
        log.info("Removing stray item '%s' in target folder", entry.name)
        remove_item(entry)


def process_movie(
    source: MediaLibrary,
    target: MediaLibrary,
    source_path: pathlib.Path,
    movie: MovieInfo,
    *,
    verbose: bool = False,
) -> int:
    target_path = target.movie_path(movie)
    log.info(f"Processing '{source_path.name}' → '{target_path.name}'")

    videos_to_sync: Dict[str, Tuple[pathlib.Path, pathlib.Path]] = {}
    assets_to_sync: Dict[str, Tuple[pathlib.Path, pathlib.Path]] = {}

    # Scan for video files and assets
    for entry in source_path.glob("*"):
        if entry.is_file() and entry.suffix.lower() in ACCEPTED_VIDEO_SUFFIXES:
            video = source.parse_video_name(entry.name)
            video_path = target.video_path(movie, video or VideoInfo(extension=entry.suffix.lower()))
            video_name = video_path.name
            if video_name in videos_to_sync:
                log.error("Conflicting video file '%s'. Aborting.", entry.name)
                return 0
            videos_to_sync[video_name] = (entry, video_path)
        elif entry.is_dir():
            dir_name = entry.name
            # TODO: Just a quick fix for selecting and manipulating directories
            if dir_name.startswith(".") or dir_name == "source":
                log.debug("Ignoring asset folder '%s'", dir_name)
                continue
            target_dir_name = dir_name
            if dir_name == "extras":
                # FIXME: will hurt if both 'extras' and 'other' exists in source folder
                target_dir_name = "other"
            assets_to_sync[target_dir_name] = (entry, target_path / target_dir_name)

    target_path.mkdir(parents=True, exist_ok=True)

    # Hardlink missing video files
    for _video_name, item in videos_to_sync.items():
        if item[1].exists():
            if item[1].samefile(item[0]):
                if verbose:
                    log.info("Target video file '%s' already exists", item[1].name)
            else:
                log.info("Replacing video file '%s' → '%s'", item[0].name, item[1].name)
                item[1].unlink()
                item[1].hardlink_to(item[0])
        else:
            log.info("Linking video file '%s' → '%s'", item[0].name, item[1].name)
            item[1].hardlink_to(item[0])

    # Remove stray items
    for entry in target_path.iterdir():
        if entry.name in videos_to_sync or entry.name in assets_to_sync:
            continue
        log.info("Removing stray item '%s' in movie folder", entry.name)
        remove_item(entry)

    # Sync assets folders
    for _, item in assets_to_sync.items():
        process_assets_folder(item[0], item[1], verbose=verbose)

    return 0


def sync(
    src: str,
    dst: str,
    *,
    delete: bool = False,
    create: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> int:
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    source = JellyfinLibrary(pathlib.Path(src).resolve())
    target = PlexLibrary(pathlib.Path(dst).resolve())

    log.info(f"Source library: {source.base_dir}")
    log.info(f"Target library: {target.base_dir}")

    if not source.base_dir.is_dir():
        log.error("Source directory '%s' does not exist", source.base_dir)
        return 1

    if not target.base_dir.is_dir():
        if create:
            target.base_dir.mkdir(parents=True)
        else:
            log.error("Target directory '%s' does not exist", target.base_dir)
            return 1

    for s, _t, m in scan_media_library(source, target, delete=delete):
        process_movie(source, target, s, m, verbose=verbose)

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
