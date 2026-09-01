"""Tests for the disambiguation layer."""

from __future__ import annotations

from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.disambig import (
    DisambiguationResult,
    HashFallbackDisambiguator,
    NaiveDisambiguator,
    _short_hash,
)
from jellyplex_sync.model import MovieInfo, VideoInfo


@pytest.fixture
def jwriter() -> jp.JellyfinLibraryWriter:
    return jp.JellyfinLibraryWriter(Path("./Jellyfin"))


@pytest.fixture
def pwriter() -> jp.PlexLibraryWriter:
    return jp.PlexLibraryWriter(Path("./Plex"))


@pytest.fixture
def movie() -> MovieInfo:
    return MovieInfo(title="Movie", year="2020")


# ---------------------------------------------------------------------------
# NaiveDisambiguator
# ---------------------------------------------------------------------------


def test_naive_no_collisions(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("2160p",)), Path("b.mkv")),
    ]
    result = NaiveDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result.names[Path("a.mkv")] == "Movie (2020) - BD.mkv"
    assert result.names[Path("b.mkv")] == "Movie (2020) - 4k.mkv"
    assert all(note is None for note in result.notes.values())
    assert result.unresolved == ()


def test_naive_collision_yields_movie_clash(movie, jwriter):
    # Both videos have the same labels — same naive Jellyfin name.
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("Movie [1080p].mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("Movie [1080p] [remux].mkv")),
    ]
    result = NaiveDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    # Colliding sources are absent from names.
    assert Path("Movie [1080p].mkv") not in result.names
    assert Path("Movie [1080p] [remux].mkv") not in result.names
    # And the clash is surfaced.
    assert len(result.unresolved) == 1
    clash = result.unresolved[0]
    assert clash.movie_folder == "Movie (2020)"
    assert clash.target_filename == "Movie (2020) - BD.mkv"
    assert set(clash.source_filenames) == {
        "Movie [1080p].mkv",
        "Movie [1080p] [remux].mkv",
    }


def test_naive_mixed_collision_and_uniqueness(movie, jwriter):
    # Three videos: two collide on the BD name, one is unique 4k.
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("b.mkv")),
        (VideoInfo(extension=".mkv", labels=("2160p",)), Path("c.mkv")),
    ]
    result = NaiveDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    # The 4k entry survives, the BD pair clashes.
    assert result.names == {Path("c.mkv"): "Movie (2020) - 4k.mkv"}
    assert len(result.unresolved) == 1
    assert result.unresolved[0].target_filename == "Movie (2020) - BD.mkv"


def test_naive_empty_videos(movie, jwriter):
    result = NaiveDisambiguator().disambiguate(
        movie, [], jwriter, movie_folder="Movie (2020)"
    )
    assert result.names == {}
    assert result.notes == {}
    assert result.unresolved == ()


def test_naive_plex_writer_has_no_clashes(movie, pwriter):
    # Plex never drops information, so labels-distinct videos stay distinct.
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("b.mkv")),
    ]
    result = NaiveDisambiguator().disambiguate(
        movie, videos, pwriter, movie_folder="Movie (2020)"
    )
    assert result.unresolved == ()
    assert len(result.names) == 2


# ---------------------------------------------------------------------------
# HashFallbackDisambiguator
# ---------------------------------------------------------------------------


def test_hashfallback_no_collisions_identical_to_naive(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("2160p",)), Path("b.mkv")),
    ]
    naive = NaiveDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    hashed = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert hashed.names == naive.names
    assert hashed.unresolved == ()
    assert all(n is None for n in hashed.notes.values())


def test_hashfallback_resolves_collision(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("Movie [1080p].mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("Movie [1080p] [remux].mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result.unresolved == ()
    assert len(result.names) == 2
    # Both names are distinct and contain a hash bracket.
    n1 = result.names[Path("Movie [1080p].mkv")]
    n2 = result.names[Path("Movie [1080p] [remux].mkv")]
    assert n1 != n2
    expected_h1 = _short_hash("Movie [1080p].mkv", 8)
    expected_h2 = _short_hash("Movie [1080p] [remux].mkv", 8)
    assert f"[{expected_h1}]" in n1
    assert f"[{expected_h2}]" in n2


def test_hashfallback_notes_disambiguation_strategy(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("b.mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    for source in (Path("a.mkv"), Path("b.mkv")):
        note = result.notes[source]
        assert note is not None
        assert note.strategy == "hash_suffix"
        assert source.name in note.detail


def test_hashfallback_unique_videos_have_no_note(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("2160p",)), Path("b.mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result.notes[Path("a.mkv")] is None
    assert result.notes[Path("b.mkv")] is None


def test_hashfallback_records_each_drop_once_per_video(movie, jwriter):
    """Each accepted video carries exactly its own rendering losses —
    no duplication from probe passes or the movie-level rendering."""
    # `[remux]` / `[amazon]` are non-resolution labels → one drop each.
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p", "amazon")), Path("b.mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert [d.value for d in result.drops[Path("a.mkv")]] == ["remux"]
    assert [d.value for d in result.drops[Path("b.mkv")]] == ["amazon"]


def test_hashfallback_collision_still_records_drops_once(movie, jwriter):
    """Even when collision resolution re-renders with a hashed name,
    each video's drops appear once in the result."""
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("b.mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    for source in (Path("a.mkv"), Path("b.mkv")):
        remux_drops = [d for d in result.drops[source] if d.value == "remux"]
        assert len(remux_drops) == 1


def test_naive_excluded_videos_carry_no_drops(movie, jwriter):
    """Sources excluded because of a clash are absent from `drops` too —
    their losses are moot, the clash itself is the report."""
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p", "remux")), Path("b.mkv")),
    ]
    result = NaiveDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result.drops == {}
    assert len(result.unresolved) == 1


def test_hashfallback_hash_is_deterministic():
    h1 = _short_hash("Movie [1080p].mkv", 8)
    h2 = _short_hash("Movie [1080p].mkv", 8)
    assert h1 == h2
    assert len(h1) == 8
    assert all(c in "0123456789abcdef" for c in h1)


def test_hashfallback_hash_length_validation():
    with pytest.raises(ValueError):
        HashFallbackDisambiguator(hash_length=3)
    with pytest.raises(ValueError):
        HashFallbackDisambiguator(hash_length=65)


def test_hashfallback_custom_hash_length(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("b.mkv")),
    ]
    result = HashFallbackDisambiguator(hash_length=16).disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    name = result.names[Path("a.mkv")]
    # 16-char hex hash should appear in brackets.
    h = _short_hash("a.mkv", 16)
    assert f"[{h}]" in name


def test_hashfallback_three_way_collision(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("b.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("c.mkv")),
    ]
    result = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result.unresolved == ()
    names = {result.names[Path(n)] for n in ("a.mkv", "b.mkv", "c.mkv")}
    assert len(names) == 3


def test_hashfallback_reproducible_across_runs(movie, jwriter):
    videos = [
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("a.mkv")),
        (VideoInfo(extension=".mkv", labels=("1080p",)), Path("b.mkv")),
    ]
    result1 = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    result2 = HashFallbackDisambiguator().disambiguate(
        movie, videos, jwriter, movie_folder="Movie (2020)"
    )
    assert result1.names == result2.names


# ---------------------------------------------------------------------------
# DisambiguationResult dataclass
# ---------------------------------------------------------------------------


def test_disambiguation_result_is_frozen():
    from dataclasses import FrozenInstanceError

    r = DisambiguationResult(names={}, notes={})
    with pytest.raises(FrozenInstanceError):
        r.names = {Path("a"): "b"}  # type: ignore[misc]
