"""Tests for compare(): Plan vs. actual target filesystem → DiffResult."""

from __future__ import annotations

from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.compare import compare
from jellyplex_sync.planner import Planner
from jellyplex_sync.realize import Realizer


def _setup(tmp_path: Path) -> tuple[Path, Path, Planner]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    planner = Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
    )
    return source, target, planner


# ---------------------------------------------------------------------------
# In-sync cases
# ---------------------------------------------------------------------------


def test_empty_plan_empty_target_in_sync(tmp_path):
    _, _, planner = _setup(tmp_path)
    result = compare(planner.plan())
    assert not result.has_differences
    assert result.movies_only_in_source == ()
    assert result.movies_only_in_target == ()
    assert result.differing_movies == ()


def test_after_realize_in_sync(tmp_path):
    source, _, planner = _setup(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    plan = planner.plan()
    Realizer().apply(plan)
    result = compare(plan)
    assert not result.has_differences


# ---------------------------------------------------------------------------
# Movies only in source
# ---------------------------------------------------------------------------


def test_unrealized_movie_is_only_in_source(tmp_path):
    source, target, planner = _setup(tmp_path)
    movie = source / "Das Boot (1981) {imdb-tt0082096}"
    movie.mkdir()
    (movie / "Das Boot (1981) {imdb-tt0082096}.mkv").write_text("v")
    plan = planner.plan()
    result = compare(plan)
    assert len(result.movies_only_in_source) == 1
    entry = result.movies_only_in_source[0]
    assert entry.source_folder == "Das Boot (1981) {imdb-tt0082096}"
    assert entry.expected_target == "Das Boot (1981) [imdbid-tt0082096]"


# ---------------------------------------------------------------------------
# Movies only in target
# ---------------------------------------------------------------------------


def test_orphan_target_folder_is_only_in_target(tmp_path):
    _, target, planner = _setup(tmp_path)
    (target / "Orphan Movie (2019)").mkdir()
    result = compare(planner.plan())
    assert result.movies_only_in_target == ("Orphan Movie (2019)",)


# ---------------------------------------------------------------------------
# File-level differences within a shared movie
# ---------------------------------------------------------------------------


def test_extra_file_in_target_shows_as_only_in_target(tmp_path):
    source, target, planner = _setup(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    plan = planner.plan()
    Realizer().apply(plan)
    # Add an extra file on the target side after realizing.
    (target / "Movie (2020)" / "extra.txt").write_text("e")
    result = compare(plan)
    assert len(result.differing_movies) == 1
    d = result.differing_movies[0]
    assert d.target_movie_name == "Movie (2020)"
    assert d.only_in_source == ()
    assert d.only_in_target == ("extra.txt",)


def test_missing_file_in_target_shows_as_only_in_source(tmp_path):
    source, target, planner = _setup(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    (movie / "poster.jpg").write_text("p")
    plan = planner.plan()
    # Realize only video, manually omit poster.
    target_dir = target / "Movie (2020)"
    target_dir.mkdir()
    (target_dir / "Movie (2020).mkv").write_text("v")
    result = compare(plan)
    d = result.differing_movies[0]
    assert d.only_in_source == ("poster.jpg",)
    assert d.only_in_target == ()


def test_assets_compared_at_folder_level(tmp_path):
    """Comparison goes one level deep — asset subdir name is compared,
    asset contents are not (matches pre-0.3 diff behaviour)."""
    source, target, planner = _setup(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    extras = movie / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")
    plan = planner.plan()
    target_dir = target / "Movie (2020)"
    target_dir.mkdir()
    (target_dir / "Movie (2020).mkv").write_text("v")
    target_extras = target_dir / "extras"
    target_extras.mkdir()
    # Different file inside extras — shouldn't matter for the diff.
    (target_extras / "different-trailer.mp4").write_text("t")
    result = compare(plan)
    assert not result.has_differences


# ---------------------------------------------------------------------------
# Ignored entries flow through
# ---------------------------------------------------------------------------


def test_ignored_entries_passed_through(tmp_path):
    source, _, planner = _setup(tmp_path)
    (source / "junk.txt").write_text("j")
    result = compare(planner.plan())
    assert len(result.ignored) == 1
    assert result.ignored[0].path.name == "junk.txt"


# ---------------------------------------------------------------------------
# Non-existent target dir
# ---------------------------------------------------------------------------


def test_target_dir_missing_treated_as_empty(tmp_path):
    """compare() is pure and doesn't error on missing target — the diff
    just shows everything as only-in-source. Useful for the future
    `plan` subcommand which wants to show what _would_ happen even
    without a target yet."""
    source = tmp_path / "source"
    source.mkdir()
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    plan = Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(tmp_path / "absent"),
    ).plan()
    result = compare(plan)
    assert len(result.movies_only_in_source) == 1
    assert result.movies_only_in_target == ()
