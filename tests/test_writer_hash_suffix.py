"""Tests for the `hash_suffix` keyword on Writer.video_name.

The hash_suffix arrives from the HashFallbackDisambiguator (next
commit). These tests pin where each Writer places the hash in the
output name, and that calling with the default (None) leaves the
existing behaviour untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.library import CollectingReporter
from jellyplex_sync.model import MovieInfo, VideoInfo


@pytest.fixture
def pwriter() -> jp.PlexLibraryWriter:
    return jp.PlexLibraryWriter(Path("./Plex"))


@pytest.fixture
def jwriter() -> jp.JellyfinLibraryWriter:
    return jp.JellyfinLibraryWriter(Path("./Jellyfin"))


# ---------------------------------------------------------------------------
# Default behaviour: no hash_suffix means no change
# ---------------------------------------------------------------------------


def test_plex_writer_default_unchanged(pwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv", labels=("1080p",))
    explicit = pwriter.video_name(movie, video, hash_suffix=None)
    implicit = pwriter.video_name(movie, video)
    assert explicit == implicit
    assert explicit == "Movie (2020) [1080p].mkv"


def test_jellyfin_writer_default_unchanged(jwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv", labels=("1080p",))
    explicit = jwriter.video_name(movie, video, hash_suffix=None)
    implicit = jwriter.video_name(movie, video)
    assert explicit == implicit
    assert explicit == "Movie (2020) - BD.mkv"


# ---------------------------------------------------------------------------
# Plex placement: hash goes at the very end as a bracket-label
# ---------------------------------------------------------------------------


def test_plex_writer_appends_hash_after_labels(pwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv", labels=("1080p", "remux"))
    out = pwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) [1080p] [remux] [a3f7c819].mkv"


def test_plex_writer_appends_hash_without_labels(pwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv")
    out = pwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) [a3f7c819].mkv"


def test_plex_writer_hash_survives_with_edition(pwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(
        extension=".mkv",
        attributes={"edition": "Director's Cut"},
        labels=("1080p",),
    )
    out = pwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) {edition-Director's Cut} [1080p] [a3f7c819].mkv"


# ---------------------------------------------------------------------------
# Jellyfin placement: hash goes into the version-label position
# ---------------------------------------------------------------------------


def test_jellyfin_writer_appends_hash_after_version_labels(jwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(
        extension=".mkv",
        attributes={"edition": "Director's Cut"},
        labels=("1080p",),
    )
    out = jwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) - BD Director's Cut [a3f7c819].mkv"


def test_jellyfin_writer_hash_creates_version_section_when_none_existed(jwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv")
    out = jwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) - [a3f7c819].mkv"


def test_jellyfin_writer_hash_only_with_resolution(jwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv", labels=("2160p",))
    out = jwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) - 4k [a3f7c819].mkv"


# ---------------------------------------------------------------------------
# Hash + provider id (Jellyfin's [imdbid-...] in the folder name)
# ---------------------------------------------------------------------------


def test_jellyfin_writer_hash_after_imdb_block(jwriter):
    movie = MovieInfo(title="Movie", year="2020", attributes={"imdb": "tt0123456"})
    video = VideoInfo(extension=".mkv", labels=("1080p",))
    out = jwriter.video_name(movie, video, hash_suffix="a3f7c819")
    assert out == "Movie (2020) [imdbid-tt0123456] - BD [a3f7c819].mkv"


# ---------------------------------------------------------------------------
# Disambiguation property: two videos that would naively clash become unique
# ---------------------------------------------------------------------------


def test_jellyfin_hash_suffix_disambiguates_otherwise_identical_targets(jwriter):
    """The whole point of hash_suffix: feed it two source filenames that
    translate to the same name, get back two distinct names."""
    movie = MovieInfo(title="Movie", year="2020")
    # Both videos have the same labels — would collapse to the same Jellyfin name.
    v_a = VideoInfo(extension=".mkv", labels=("1080p",))
    v_b = VideoInfo(extension=".mkv", labels=("1080p",))

    # Without hash: same name.
    assert jwriter.video_name(movie, v_a) == jwriter.video_name(movie, v_b)

    # With distinct hashes (would come from distinct source filenames): different names.
    name_a = jwriter.video_name(movie, v_a, hash_suffix="a3f7c819")
    name_b = jwriter.video_name(movie, v_b, hash_suffix="b1d2e3f4")
    assert name_a != name_b


# ---------------------------------------------------------------------------
# The hash never alters the reporter contract
# ---------------------------------------------------------------------------


def test_hash_suffix_does_not_emit_extra_drops(jwriter):
    movie = MovieInfo(title="Movie", year="2020")
    video = VideoInfo(extension=".mkv", labels=("1080p",))
    r1 = CollectingReporter()
    r2 = CollectingReporter()
    jwriter.video_name(movie, video, r1)
    jwriter.video_name(movie, video, r2, hash_suffix="a3f7c819")
    assert r1.drops == r2.drops
