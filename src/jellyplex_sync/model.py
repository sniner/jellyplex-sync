from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VideoInfo:
    """Format-neutral description of a single video file.

    `attributes` carry the `{key-value}` style structured metadata (e.g.
    `edition` in Plex). `labels` carry the free-form `[bracket]` style
    markers (e.g. resolution shorthand, source markers). Writers decide
    which of these survive the trip into their target format and which
    have to be dropped — see Reporter in library.py.
    """

    extension: str
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()


@dataclass
class MovieInfo:
    """Format-neutral description of a movie folder.

    `attributes` typically holds provider IDs (`imdb`, `tmdb`, `tvdb`).
    Editions live on the associated `VideoInfo`, not here, because the
    current organisational style keeps multiple editions as variant
    files inside one folder.
    """

    title: str
    year: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()
