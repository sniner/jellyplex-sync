import logging
import pathlib
import re
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Generator, List, Optional, Set, Tuple, Type, Union

from .library import (
    ACCEPTED_VIDEO_SUFFIXES,
    RESOLUTION_PATTERN,
    MovieInfo,
    VideoInfo,
    MediaLibrary,
)


log = logging.getLogger(__name__)


JELLYFIN_ID_PATTERN = re.compile(r"\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]")
JELLYFIN_MOVIE_PATTERNS = [
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)\s* - \s*\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)\s+\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)$"),
    re.compile(r"^(?P<title>.+?)\s+\[(?P<provider_id>[a-zA-Z]+id-[^\]]+)\]"),
    re.compile(r"^(?P<title>.+?)$"),
]


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
            if tag.upper() in ("DVD", "4k", "BD"):
                return [tag.upper()]
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
