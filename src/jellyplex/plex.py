import logging
import pathlib
import re
from typing import Generator, Optional, Set, Tuple

from .library import (
    RESOLUTION_PATTERN,
    MovieInfo,
    VideoInfo,
    MediaLibrary,
)


log = logging.getLogger(__name__)


PLEX_MOVIE_PATTERN = re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)")
PLEX_META_BLOCK_PATTERN = re.compile(r"(\{([A-Za-z]+)-([^}]+)\})")
PLEX_META_INFO_PATTERN = re.compile(r"(\[([^]]+)\])")
PLEX_METADATA_PROVIDER = {"imdb", "tmdb", "tvdb"}


class PlexLibrary(MediaLibrary):
    @classmethod
    def shortname(cls) -> str:
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

        if video.providers:
            existing_id = f"{movie.provider}-{movie.movie_id}" if movie.provider and movie.movie_id else None
            for p_tag in sorted(list(video.providers)):
                if p_tag == existing_id:
                    continue
                parts.append(f"{{{p_tag}}}")

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

        if title:
            return MovieInfo(
                title=title,
                year=year,
                provider=provider,
                movie_id=movie_id
            )
        else:
            return None

    def parse_video_path(self, path: pathlib.Path) -> Optional[VideoInfo]:
        name = path.stem
        leftover = name

        # Find edition and providers
        edition: Optional[str] = None
        providers: Set[str] = set()
        for key, val, blk in self._parse_meta_blocks(name):
            if key.lower() == "edition":
                edition = val
            elif key.lower() in PLEX_METADATA_PROVIDER:
                providers.add(f"{key.lower()}-{val}")
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
            providers=providers if providers else None,
        )
