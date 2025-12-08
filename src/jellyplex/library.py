import logging
import os
import pathlib
import re
from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass


log = logging.getLogger(__name__)


ACCEPTED_VIDEO_SUFFIXES = {".mkv", ".m4v", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".webm"}
ACCEPTED_ASSOCIATED_SUFFIXES = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".edl", ".nfo"}
RESOLUTION_PATTERN = re.compile(r"\d{3,4}[pi]$")


@dataclass
class MovieInfo:
    """Metadata for the whole movie"""
    title: str
    year: str | None = None
    provider: str | None = None
    movie_id: str | None = None


@dataclass
class VideoInfo:
    """Metadata for a single video file"""
    extension: str
    edition: str | None = None
    resolution: str | None = None
    tags: set[str] | None = None
    providers: set[str] | None = None


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
    def parse_movie_path(self, path: pathlib.Path) -> MovieInfo | None:
        ...

    @abstractmethod
    def parse_video_path(self, path: pathlib.Path) -> VideoInfo | None:
        ...

    def scan(self) -> Generator[tuple[pathlib.Path, MovieInfo], None, None]:
        """Scan library for movie folders using efficient os.scandir."""
        try:
            with os.scandir(self.base_dir) as entries:
                for entry in entries:
                    try:
                        # Use cached is_dir from DirEntry (avoids extra stat call)
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue

                    entry_path = pathlib.Path(entry.path)
                    movie = self.parse_movie_path(entry_path)
                    if not movie:
                        log.warning("Ignoring folder with unparsable name: %s", entry.name)
                        continue

                    yield entry_path, movie
        except OSError as e:
            log.error("Failed to scan library directory '%s': %s", self.base_dir, e)
