#!/usr/bin/python3

import argparse
import logging
import pathlib
import re
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Generator, List, Optional, Set, Tuple, Type, Union


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

RESOLUTION_PATTERN = re.compile(r"\d{3,4}[pi]$")


class MediaLibrary(ABC):
    def __init__(self, base_dir: pathlib.Path):
        self.base_dir = base_dir.resolve()

    @classmethod
    @abstractmethod
    def kind(cls) -> str:
        ...

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

# FIXME: It's not only a parser for variant strings anymore ...
class VariantParser(ABC):
    def __init__(self, library: MediaLibrary):
        self.library = library

    @abstractmethod
    def parse(self, variant: str, video: VideoInfo) -> VideoInfo:
        ...

    @abstractmethod
    def video_name(self, movie_name: str, video: VideoInfo) -> str:
        ...


class SimpleVariantParser(VariantParser):
    def parse(self, variant: str, video: VideoInfo) -> VideoInfo:
        return VideoInfo(
            extension=video.extension,
            edition=variant.strip(),
            resolution=video.resolution,
            tags=video.tags,
        )

    def _tags_to_variant(self, video: VideoInfo) -> List[str]:
        if video.resolution:
            return [video.resolution]
        for tag in video.tags or []:
            if tag.upper() == "DVD":
                return ["DVD"]
        return []

    def video_name(self, movie_name: str, video: VideoInfo) -> str:
        parts = [movie_name]
        variant_parts = self._tags_to_variant(video)
        if video.edition:
            variant_parts.append(video.edition)
        if variant_parts:
            parts.append(f"- {' '.join(variant_parts)}")
        return f"{' '.join(parts)}{video.extension}"


@dataclass
class ResParser:
    pattern: re.Pattern
    mapping: Union[Callable[[re.Match[str]], List[str]], List[str]]

class SninerVariantParser(SimpleVariantParser):
    RES_MAP: List[ResParser] = [
        ResParser(re.compile(r"4k([\.\-]([\w\d]+))?$"), lambda m: ["2160p", m.group(2)] if m.group(1) else ["2160p"]),
        ResParser(re.compile(r"BD([\.\-]([\w\d]+))?$"), lambda m: ["1080p", m.group(2)] if m.group(1) else ["1080p"]),
        ResParser(re.compile(r"DVD([\.\-]([\w\d]+))?$"), lambda m: ["", "DVD", m.group(2)] if m.group(1) else ["", "DVD"]),
        ResParser(RESOLUTION_PATTERN, lambda m: [m.group(0)]),
    ]

    def _match_resolution(self, word: str) -> Tuple[Optional[str], Set[str]]:
        tags: List[str] = []
        for mapper in self.RES_MAP:
            match = mapper.pattern.match(word)
            if match:
                if callable(mapper.mapping):
                    tags = mapper.mapping(match)
                else:
                    tags = mapper.mapping
                break

        return tags[0] if tags else None, set(tags[1:])

    def parse(self, variant: str, video: VideoInfo) -> VideoInfo:
        edition: Optional[str] = None

        variant_parts = variant.split(" ")

        res, tags = self._match_resolution(variant_parts[0])
        if res or tags:
            edition = " ".join(variant_parts[1:])
        elif len(variant_parts) > 1:
            res, tags = self._match_resolution(variant_parts[-1])
            if res or tags:
                edition = " ".join(variant_parts[:-1])
            else:
                edition = variant
        else:
            edition = variant

        tags = (video.tags or set()).union(tags)

        return VideoInfo(
            extension=video.extension,
            edition=edition if edition else None,
            resolution=res,
            tags=tags if tags else None,
        )

    def _tags_to_variant(self, video: VideoInfo) -> List[str]:
        variant = super()._tags_to_variant(video)
        if variant:
            m = re.match(r"(\d{3,4})[pi]$", variant[0], flags=re.IGNORECASE)
            if m:
                res = m.group(1)
                if res == "1080":
                    return ["BD"]
                elif res == "2160":
                    return ["4k"]
                elif res in ("480", "576"):
                    return ["DVD"]
        return variant


class JellyfinLibrary(MediaLibrary):
    def __init__(self, base_dir: pathlib.Path, *, variant_parser: Optional[Type[VariantParser]] = None):
        super().__init__(base_dir)
        self.variant_parser = variant_parser(self) if variant_parser else SninerVariantParser(self)

    @classmethod
    def kind(cls) -> str:
        return "jellyfin"

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
        return self.variant_parser.video_name(
            self.movie_name(movie),
            video
        )

    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        base_name = path.stem
        video = VideoInfo(extension=path.suffix)
        parts = base_name.split(" - ")  # <spc><dash><spc> is required by Jellyfin for variants
        if len(parts) > 1:
            # Do no take the media id for an edition
            if JELLYFIN_ID_PATTERN.match(parts[-1]):
                return video
            else:
                # The variant is the substring after the final ' – ' in the filename.
                variant = parts[-1].strip().lstrip("[").rstrip("]")
                return self.variant_parser.parse(variant, video)
        return video


class PlexLibrary(MediaLibrary):
    @classmethod
    def kind(cls) -> str:
       return "plex"

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
        if video.tags:
            tags = [f"[{t}]" for t in video.tags]
            parts.append("".join(tags))
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
                    remove_item(entry)
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
    dry_run: bool = False,
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

    if not target_path.exists():
        if dry_run:
            log.info("MKDIR  %s", target_path)
        else:
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
                if dry_run:
                    log.info("DELETE %s", item[1])
                else:
                    item[1].unlink()
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
                remove_item(entry)
            stats.items_removed += 1

    # Sync assets folders
    for _, item in assets_to_sync.items():
        s = process_assets_folder(item[0], item[1], delete=delete, verbose=verbose, dry_run=dry_run)
        stats.asset_items_total += s.files_total
        stats.asset_items_linked += s.files_linked
        stats.asset_items_removed += s.items_removed

    return stats


def determine_library_type(path: pathlib.Path) -> Optional[str]:
    plex_hints: int = 0
    jellyfin_hints: int = 0
    for entry in path.rglob("*.mkv", case_sensitive=False):
        fname = entry.stem
        # Check for provider id
        if re.search(r"\[[a-z]+id-[^\]]+\]", fname, flags=re.IGNORECASE):
            return JellyfinLibrary.kind()
        if re.search(r"\{[a-z]+-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibrary.kind()
        # Check for Plex edition
        if re.search(r"\{edition-[^\}]+\}", fname, flags=re.IGNORECASE):
            return PlexLibrary.kind()
        # Check for hints
        variant = fname.split(" - ")
        if len(variant) > 1 and re.search(r"\(\d{4}\)", variant[-1]) is None:
            jellyfin_hints += 1
        if re.search(r"\[\d{3,4}[pi\]\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
        if re.search(r"\[[a-z0-9\.\,]+\]", fname, flags=re.IGNORECASE):
            plex_hints += 1
    if plex_hints > jellyfin_hints:
        return PlexLibrary.kind()
    elif jellyfin_hints > plex_hints:
        return JellyfinLibrary.kind()
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
        target_type = PlexLibrary.kind() if source_type == JellyfinLibrary.kind() else JellyfinLibrary.kind()
    else:
        target_type = convert_to
        source_type = PlexLibrary.kind() if target_type == JellyfinLibrary.kind() else JellyfinLibrary.kind()

    source_lib = (PlexLibrary if source_type == PlexLibrary.kind() else JellyfinLibrary)(source_path)
    target_lib = (PlexLibrary if target_type == PlexLibrary.kind() else JellyfinLibrary)(target_path)

    if dry_run:
        log.info("SOURCE %s", source_lib.base_dir)
        log.info("TARGET %s", target_lib.base_dir)
        log.info("CONVERTING %s TO %s", source_lib.kind().capitalize(), target_lib.kind().capitalize())
    else:
        log.info("Syncing '%s' (%s) to '%s' (%s)",
            source_lib.base_dir,
            source_lib.kind().capitalize(),
            target_lib.base_dir,
            target_lib.kind().capitalize(),
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

    for src, _, movie in scan_media_library(source_lib, target_lib, delete=delete, dry_run=dry_run, stats=lib_stats):
        s = process_movie(
            source_lib,
            target_lib,
            src,
            movie,
            delete=delete,
            verbose=verbose,
            dry_run=dry_run,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Plex compatible media library from a Jellyfin library.")
    parser.add_argument("source", help="Jellyfin media library")
    parser.add_argument("target", help="Plex media library")
    parser.add_argument("--convert-to", type=str,
        choices=[JellyfinLibrary.kind(), PlexLibrary.kind(), "auto"], default="auto",
        help="Type of library to convert to ('auto' will try to determine source library type)")
    parser.add_argument("--dry-run", action="store_true", help="Show actions only, don't execute them")
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
            dry_run= args.dry_run,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
            convert_to=args.convert_to,
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
    #     dry_run=True,
    # )
