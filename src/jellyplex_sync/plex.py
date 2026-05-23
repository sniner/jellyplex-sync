from __future__ import annotations

import logging
import pathlib
import re

from .library import LoggingReporter, Reporter
from .model import MovieInfo, VideoInfo

log = logging.getLogger(__name__)


_PLEX_TITLE_YEAR = re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)")
_PLEX_BRACE_BLOCK = re.compile(r"(\{([A-Za-z]+)-([^}]+)\})")
_PLEX_BRACKET_BLOCK = re.compile(r"(\[([^]]+)\])")
_PLEX_PROVIDERS = ("imdb", "tmdb", "tvdb")


class _PlexBase:
    def __init__(self, base_dir: pathlib.Path):
        self.base_dir = base_dir.resolve()

    @classmethod
    def shortname(cls) -> str:
        return "plex"


class PlexLibraryReader(_PlexBase):
    def parse_movie(self, path: pathlib.Path) -> MovieInfo | None:
        name = path.name
        leftover = name
        attributes: dict[str, str] = {}

        for blk, key, val in _PLEX_BRACE_BLOCK.findall(name):
            k = key.lower()
            if k in _PLEX_PROVIDERS:
                attributes[k] = val.strip()
            leftover = leftover.replace(blk, "")

        for blk, _info in _PLEX_BRACKET_BLOCK.findall(leftover):
            leftover = leftover.replace(blk, "")

        leftover = re.sub(r"\s+", " ", leftover).strip()

        match = _PLEX_TITLE_YEAR.match(leftover)
        if match:
            title = match.group("title").strip()
            year: str | None = match.group("year")
        else:
            title = leftover
            year = None

        if not title:
            return None
        return MovieInfo(title=title, year=year, attributes=attributes)

    def parse_video(self, path: pathlib.Path) -> VideoInfo:
        name = path.stem
        leftover = name
        attributes: dict[str, str] = {}
        labels: list[str] = []

        for blk, key, val in _PLEX_BRACE_BLOCK.findall(name):
            if key.lower() == "edition":
                attributes["edition"] = val
            leftover = leftover.replace(blk, "")

        for blk, info in _PLEX_BRACKET_BLOCK.findall(leftover):
            labels.append(info.strip())
            leftover = leftover.replace(blk, "")

        return VideoInfo(
            extension=path.suffix,
            attributes=attributes,
            labels=tuple(labels),
        )


class PlexLibraryWriter(_PlexBase):
    def movie_name(self, movie: MovieInfo, reporter: Reporter | None = None) -> str:
        _ = reporter  # Plex never drops; reporter accepted for protocol compatibility.
        parts = [movie.title]
        if movie.year:
            parts.append(f"({movie.year})")
        for provider in _PLEX_PROVIDERS:
            if provider in movie.attributes:
                parts.append(f"{{{provider}-{movie.attributes[provider]}}}")
        for label in movie.labels:
            parts.append(f"[{label}]")
        return " ".join(parts)

    def video_name(
        self, movie: MovieInfo, video: VideoInfo, reporter: Reporter | None = None
    ) -> str:
        reporter = reporter or LoggingReporter()
        parts = [self.movie_name(movie, reporter)]
        # Plex puts edition first among video attributes, then any others.
        if "edition" in video.attributes:
            parts.append(f"{{edition-{video.attributes['edition']}}}")
        for key, value in video.attributes.items():
            if key == "edition":
                continue
            parts.append(f"{{{key}-{value}}}")
        # Labels go at the end. Plex ignores `[bracket]` content entirely, so
        # this is the safe round-trip channel for anything we couldn't
        # express elsewhere.
        for label in video.labels:
            parts.append(f"[{label}]")
        return f"{' '.join(parts)}{video.extension}"
