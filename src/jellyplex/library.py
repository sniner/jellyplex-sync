import logging
import pathlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator, Optional, Set, Tuple


log = logging.getLogger(__name__)


ACCEPTED_VIDEO_SUFFIXES = {".mkv", ".m4v", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".webm"}
ACCEPTED_ASSOCIATED_SUFFIXES = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".edl", ".nfo"}
RESOLUTION_PATTERN = re.compile(r"\d{3,4}[pi]$")


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
    providers: Optional[Set[str]] = None


class MediaLibrary(ABC):
    def __init__(self, base_dir: pathlib.Path):
        self.base_dir = base_dir.resolve()

    @classmethod
    @abstractmethod
    def shortname(cls) -> str:
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
