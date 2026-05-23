from __future__ import annotations

import logging
import pathlib
import re

from .library import RESOLUTION_PATTERN, Drop, LoggingReporter, Reporter
from .model import MovieInfo, VideoInfo

log = logging.getLogger(__name__)


_JELLYFIN_ID_BLOCK = re.compile(r"(\[(?P<key>[a-zA-Z]+id)-(?P<value>[^\]]+)\])")
_JELLYFIN_ID_ONLY = re.compile(r"^\[[a-zA-Z]+id-[^\]]+\]$")
_JELLYFIN_TITLE_YEAR = re.compile(
    r"^(?P<title>.+?)(?:\s+\((?P<year>\d{4})\))?(?:\s*-\s*)?$"
)

# Maps any resolution-like label string we may see to the canonical Plex form.
# Used by the parser when interpreting Jellyfin version labels.
_SHORTHAND_TO_CANONICAL = {
    "dvd": "DVD",
    "bd": "1080p",
    "4k": "2160p",
}

# Maps a canonical Plex resolution label (or already-shorthand input) to the
# Jellyfin version-label shorthand. Used by the writer.
_CANONICAL_TO_SHORTHAND = {
    "DVD": "DVD",
    "BD": "BD",
    "4k": "4k",
    "480i": "DVD",
    "480p": "DVD",
    "576i": "DVD",
    "576p": "DVD",
    "720i": "720p",
    "720p": "720p",
    "1080i": "BD",
    "1080p": "BD",
    "2160i": "4k",
    "2160p": "4k",
}

# A small superset of provider keys we expose to/from Jellyfin folder names.
# TVDB is shows-only per Jellyfin docs but we still parse/emit it.
_JELLYFIN_PROVIDERS = ("imdb", "tmdb", "tvdb")


class _JellyfinBase:
    def __init__(self, base_dir: pathlib.Path):
        self.base_dir = base_dir.resolve()

    @classmethod
    def shortname(cls) -> str:
        return "jellyfin"


class JellyfinLibraryReader(_JellyfinBase):
    def parse_movie(self, path: pathlib.Path) -> MovieInfo | None:
        name = path.name
        leftover = name
        attributes: dict[str, str] = {}

        for blk, key, value in _JELLYFIN_ID_BLOCK.findall(name):
            provider = key.lower()
            if provider.endswith("id"):
                provider = provider[:-2]
            if provider in _JELLYFIN_PROVIDERS:
                attributes[provider] = value
            leftover = leftover.replace(blk, "")

        leftover = re.sub(r"\s+", " ", leftover).strip()

        # If we see "<title> (YYYY) - <stuff>", drop the trailing variant
        # suffix. Real Jellyfin folder names don't have one, but a file
        # basename does — making the parser tolerant lets callers reuse
        # the same string for both parse_movie and parse_video.
        variant_strip = re.match(r"^(?P<base>.+?\s+\(\d{4}\))\s+-\s+.+$", leftover)
        if variant_strip:
            leftover = variant_strip.group("base")

        match = _JELLYFIN_TITLE_YEAR.match(leftover)
        if not match:
            return None

        title = (match.group("title") or "").strip()
        if not title:
            return None
        year = match.group("year")
        return MovieInfo(title=title, year=year, attributes=attributes)

    def parse_video(self, path: pathlib.Path) -> VideoInfo:
        base = path.stem
        extension = path.suffix
        parts = base.split(" - ")  # Jellyfin's variant separator
        if len(parts) <= 1:
            return VideoInfo(extension=extension)

        last = parts[-1].strip()
        # A provider id at the end is the folder identifier, not a variant.
        if _JELLYFIN_ID_ONLY.match(last):
            return VideoInfo(extension=extension)

        variant = last.lstrip("[").rstrip("]")
        resolution, edition = _split_version_label(variant)

        attributes: dict[str, str] = {}
        if edition:
            attributes["edition"] = edition
        labels = (resolution,) if resolution else ()
        return VideoInfo(extension=extension, attributes=attributes, labels=labels)


class JellyfinLibraryWriter(_JellyfinBase):
    def movie_name(self, movie: MovieInfo, reporter: Reporter | None = None) -> str:
        reporter = reporter or LoggingReporter()
        parts = [movie.title]
        if movie.year:
            parts.append(f"({movie.year})")

        primary = _pick_primary_provider(movie.attributes)
        if primary:
            key, value = primary
            parts.append(f"[{key}id-{value}]")

        # Report any other provider IDs we couldn't fit; Jellyfin tolerates
        # multiple bracket-IDs in the folder name, but jellyplex-sync only
        # emits one for now.
        for key, value in movie.attributes.items():
            if primary and key == primary[0]:
                continue
            if key in _JELLYFIN_PROVIDERS:
                reporter.drop(
                    Drop(
                        kind="attribute",
                        key=key,
                        value=value,
                        reason="only one provider id is emitted per Jellyfin folder",
                    )
                )
            else:
                reporter.drop(
                    Drop(
                        kind="attribute",
                        key=key,
                        value=value,
                        reason="unknown Jellyfin provider key",
                    )
                )

        for label in movie.labels:
            reporter.drop(
                Drop(
                    kind="label",
                    key=None,
                    value=label,
                    reason="free [bracket] labels confuse the Jellyfin scanner",
                )
            )
        return " ".join(parts)

    def video_name(
        self, movie: MovieInfo, video: VideoInfo, reporter: Reporter | None = None
    ) -> str:
        reporter = reporter or LoggingReporter()
        base = self.movie_name(movie, reporter)

        resolution_label: str | None = None
        for label in video.labels:
            shorthand = _CANONICAL_TO_SHORTHAND.get(label) or _CANONICAL_TO_SHORTHAND.get(
                label.upper()
            )
            if shorthand is None:
                reporter.drop(
                    Drop(
                        kind="label",
                        key=None,
                        value=label,
                        reason="no equivalent in a Jellyfin version label",
                    )
                )
                continue
            if resolution_label is None:
                resolution_label = shorthand
            else:
                reporter.drop(
                    Drop(
                        kind="label",
                        key=None,
                        value=label,
                        reason="multiple resolution labels; first one wins",
                    )
                )

        edition = video.attributes.get("edition")
        for key, value in video.attributes.items():
            if key == "edition":
                continue
            reporter.drop(
                Drop(
                    kind="attribute",
                    key=key,
                    value=value,
                    reason="not expressible in a Jellyfin video name",
                )
            )

        label_parts: list[str] = []
        if resolution_label:
            label_parts.append(resolution_label)
        if edition:
            label_parts.append(edition)

        if label_parts:
            return f"{base} - {' '.join(label_parts)}{video.extension}"
        return f"{base}{video.extension}"


def _split_version_label(variant: str) -> tuple[str | None, str | None]:
    """Heuristically split a Jellyfin version label into (resolution, edition).

    Returns the resolution in canonical Plex form (e.g. "1080p" not "BD"),
    or None if no resolution word was found.
    """
    words = variant.split(" ")
    if not words:
        return None, None

    canonical = _to_canonical_resolution(words[0])
    if canonical:
        rest = " ".join(words[1:]).strip()
        return canonical, rest or None

    if len(words) > 1:
        canonical = _to_canonical_resolution(words[-1])
        if canonical:
            rest = " ".join(words[:-1]).strip()
            return canonical, rest or None

    return None, variant


def _to_canonical_resolution(word: str) -> str | None:
    lower = word.lower()
    if lower in _SHORTHAND_TO_CANONICAL:
        return _SHORTHAND_TO_CANONICAL[lower]
    if RESOLUTION_PATTERN.match(word):
        return word
    return None


def _pick_primary_provider(attributes: dict[str, str]) -> tuple[str, str] | None:
    for provider in _JELLYFIN_PROVIDERS:
        if provider in attributes:
            return provider, attributes[provider]
    return None
