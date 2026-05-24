"""Tests for the FlatDiscoverer — staging-area video file grouping."""

from __future__ import annotations

from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.discover import FlatDiscoverer
from jellyplex_sync.library import IgnoredEntry


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def preader() -> jp.PlexLibraryReader:
    return jp.PlexLibraryReader(Path("/dummy"))


@pytest.fixture
def jreader() -> jp.JellyfinLibraryReader:
    return jp.JellyfinLibraryReader(Path("/dummy"))


# ---------------------------------------------------------------------------
# Basic grouping
# ---------------------------------------------------------------------------


def test_single_flat_video(tmp_path, preader):
    _touch(tmp_path / "Movie (2020) {imdb-tt001} [1080p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 1
    assert groups[0].video_files[0].name == "Movie (2020) {imdb-tt001} [1080p].mkv"


def test_two_videos_same_movie_grouped(tmp_path, preader):
    """Two files with the same title+year+provider but different resolution
    labels must end up in the same DiscoveredGroup."""
    _touch(tmp_path / "Movie (2020) {imdb-tt001} [1080p].mkv")
    _touch(tmp_path / "Movie (2020) {imdb-tt001} [2160p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


def test_two_different_movies_separate_groups(tmp_path, preader):
    _touch(tmp_path / "Movie A (2020) {imdb-tt001}.mkv")
    _touch(tmp_path / "Movie B (2021) {imdb-tt002}.mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 2
    names = {g.source_path.name for g in groups}
    assert "Movie A (2020) {imdb-tt001}" in names
    assert "Movie B (2021) {imdb-tt002}" in names


def test_same_title_different_providers_separate(tmp_path, preader):
    """Same title and year but different IMDB IDs → two separate movies."""
    _touch(tmp_path / "Movie (2020) {imdb-tt001}.mkv")
    _touch(tmp_path / "Movie (2020) {imdb-tt999}.mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 2


def test_same_title_no_provider_grouped(tmp_path, preader):
    """Without provider IDs, grouping falls back to title+year only."""
    _touch(tmp_path / "Movie (2020) [1080p].mkv")
    _touch(tmp_path / "Movie (2020) [2160p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


# ---------------------------------------------------------------------------
# Recursive scanning
# ---------------------------------------------------------------------------


def test_recursive_finds_files_in_subdirectories(tmp_path, preader):
    _touch(tmp_path / "unsorted" / "Movie (2020) {imdb-tt001} [1080p].mkv")
    _touch(tmp_path / "recent" / "Movie (2020) {imdb-tt001} [2160p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


def test_existing_movie_folder_treated_as_flat_files(tmp_path, preader):
    """Even if the staging area has a proper movie folder, FlatDiscoverer
    ignores the folder structure and groups by filename parsing."""
    movie_dir = tmp_path / "Movie (2020) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "Movie (2020) {imdb-tt001} [1080p].mkv")
    _touch(movie_dir / "Movie (2020) {imdb-tt001} [2160p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


# ---------------------------------------------------------------------------
# Jellyfin format
# ---------------------------------------------------------------------------


def test_jellyfin_flat_video(tmp_path, jreader):
    _touch(tmp_path / "Movie (2020) [imdbid-tt001] - BD.mkv")
    groups = list(FlatDiscoverer(jreader).discover(tmp_path))
    assert len(groups) == 1


def test_jellyfin_two_versions_grouped(tmp_path, jreader):
    _touch(tmp_path / "Movie (2020) [imdbid-tt001] - BD.mkv")
    _touch(tmp_path / "Movie (2020) [imdbid-tt001] - 4k.mkv")
    groups = list(FlatDiscoverer(jreader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


# ---------------------------------------------------------------------------
# Edge cases and ignored entries
# ---------------------------------------------------------------------------


def test_non_video_files_ignored(tmp_path, preader):
    _touch(tmp_path / "poster.jpg")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "Movie (2020).mkv")
    ignored: list[IgnoredEntry] = []
    groups = list(FlatDiscoverer(preader).discover(tmp_path, ignored=ignored))
    assert len(groups) == 1
    non_video = [e for e in ignored if e.reason == "not a video file"]
    assert len(non_video) == 2


def test_dot_files_skipped(tmp_path, preader):
    _touch(tmp_path / ".DS_Store")
    _touch(tmp_path / "Movie (2020).mkv")
    ignored: list[IgnoredEntry] = []
    groups = list(FlatDiscoverer(preader).discover(tmp_path, ignored=ignored))
    assert len(groups) == 1
    assert all(not e.path.name.startswith(".") for e in ignored)


def test_empty_root_yields_nothing(tmp_path, preader):
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert groups == []


def test_no_loose_files_or_assets(tmp_path, preader):
    """FlatDiscoverer never populates loose_files or asset_dirs — in a
    flat staging area there's no folder to assign them to."""
    _touch(tmp_path / "Movie (2020) {imdb-tt001}.mkv")
    _touch(tmp_path / "poster.jpg")
    (tmp_path / "extras").mkdir()
    _touch(tmp_path / "extras" / "trailer.mp4")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert groups[0].loose_files == ()
    assert groups[0].asset_dirs == ()


def test_source_path_is_parseable_by_reader(tmp_path, preader):
    """The synthetic source_path must produce a valid MovieInfo when the
    Planner calls reader.parse_movie on it — that's the contract."""
    _touch(tmp_path / "Movie (2020) {imdb-tt001} [1080p].mkv")
    (group,) = FlatDiscoverer(preader).discover(tmp_path)
    movie = preader.parse_movie(group.source_path)
    assert movie is not None
    assert movie.title == "Movie"
    assert movie.year == "2020"
    assert movie.attributes == {"imdb": "tt001"}


# ---------------------------------------------------------------------------
# Edition variants grouped correctly
# ---------------------------------------------------------------------------


def test_editions_grouped_together(tmp_path, preader):
    """Different editions of the same movie should end up in one group —
    {edition-X} is stripped by parse_movie and doesn't affect the
    grouping key."""
    _touch(tmp_path / "Movie (2020) {imdb-tt001} {edition-Director's Cut} [1080p].mkv")
    _touch(tmp_path / "Movie (2020) {imdb-tt001} {edition-Theatrical} [1080p].mkv")
    groups = list(FlatDiscoverer(preader).discover(tmp_path))
    assert len(groups) == 1
    assert len(groups[0].video_files) == 2


# ---------------------------------------------------------------------------
# End-to-end: FlatDiscoverer → Planner → Plan
# ---------------------------------------------------------------------------


def test_flat_discoverer_integrates_with_planner(tmp_path):
    source = tmp_path / "staging"
    target = tmp_path / "library"
    source.mkdir()
    target.mkdir()

    _touch(source / "Das Boot (1981) {imdb-tt0082096} [1080p].mkv")
    _touch(source / "Das Boot (1981) {imdb-tt0082096} [2160p].mkv")
    _touch(source / "Movie B (2020) {imdb-tt999}.mkv")

    from jellyplex_sync.planner import Planner

    reader = jp.PlexLibraryReader(source)
    planner = Planner(
        reader=reader,
        writer=jp.JellyfinLibraryWriter(target),
        discoverer=FlatDiscoverer(reader),
    )
    plan = planner.plan()

    assert len(plan.movies) == 2
    boot = next(m for m in plan.movies if "Boot" in m.movie.title)
    assert len(boot.videos) == 2
    target_names = {v.target_name for v in boot.videos}
    assert any("BD" in n for n in target_names)
    assert any("4k" in n for n in target_names)
