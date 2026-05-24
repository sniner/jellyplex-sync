"""Tests for the source-discovery layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from jellyplex_sync.discover import DiscoveredGroup, TwoLevelDiscoverer
from jellyplex_sync.library import IgnoredEntry


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    root.mkdir()
    # A regular movie folder with one video, one loose file, one asset dir.
    movie_a = root / "Movie A (2020)"
    movie_a.mkdir()
    (movie_a / "Movie A (2020).mkv").write_text("v")
    (movie_a / "poster.jpg").write_text("p")
    extras = movie_a / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")
    # A movie folder with two videos, no extras.
    movie_b = root / "Movie B (2021)"
    movie_b.mkdir()
    (movie_b / "Movie B (2021) [1080p].mkv").write_text("v1")
    (movie_b / "Movie B (2021) [2160p].mkv").write_text("v2")
    # Junk at root that should be ignored.
    (root / "loose-root-file.txt").write_text("junk")
    # Dot-junk inside a movie folder — must be skipped.
    (movie_a / ".DS_Store").write_text("ds")
    return root


def test_yields_one_group_per_top_level_folder(library):
    groups = list(TwoLevelDiscoverer().discover(library))
    assert [g.source_path.name for g in groups] == ["Movie A (2020)", "Movie B (2021)"]


def test_classifies_videos_assets_and_loose(library):
    groups = {g.source_path.name: g for g in TwoLevelDiscoverer().discover(library)}
    a = groups["Movie A (2020)"]
    assert [p.name for p in a.video_files] == ["Movie A (2020).mkv"]
    assert [p.name for p in a.loose_files] == ["poster.jpg"]
    assert [p.name for p in a.asset_dirs] == ["extras"]

    b = groups["Movie B (2021)"]
    assert [p.name for p in b.video_files] == [
        "Movie B (2021) [1080p].mkv",
        "Movie B (2021) [2160p].mkv",
    ]
    assert b.loose_files == ()
    assert b.asset_dirs == ()


def test_top_level_files_are_added_to_ignored(library):
    ignored: list[IgnoredEntry] = []
    list(TwoLevelDiscoverer().discover(library, ignored=ignored))
    names = [(e.path.name, e.reason) for e in ignored]
    assert ("loose-root-file.txt", "not a directory") in names


def test_dot_files_inside_groups_are_skipped(library):
    groups = {g.source_path.name: g for g in TwoLevelDiscoverer().discover(library)}
    a = groups["Movie A (2020)"]
    assert all(not p.name.startswith(".") for p in a.video_files + a.loose_files + a.asset_dirs)


def test_empty_library_yields_nothing(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert list(TwoLevelDiscoverer().discover(root)) == []


def test_movie_folder_with_only_dot_files_is_empty_group(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "M").mkdir()
    (root / "M" / ".hidden").write_text("x")
    groups = list(TwoLevelDiscoverer().discover(root))
    assert len(groups) == 1
    assert groups[0].video_files == ()
    assert groups[0].asset_dirs == ()
    assert groups[0].loose_files == ()


def test_discovery_is_lexicographically_sorted(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    for name in ["Z", "A", "M"]:
        (root / name).mkdir()
    groups = list(TwoLevelDiscoverer().discover(root))
    assert [g.source_path.name for g in groups] == ["A", "M", "Z"]


def test_files_within_group_are_sorted(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    m = root / "Movie"
    m.mkdir()
    for name in ["c.mkv", "a.mkv", "b.mkv"]:
        (m / name).write_text("v")
    (group,) = TwoLevelDiscoverer().discover(root)
    assert [p.name for p in group.video_files] == ["a.mkv", "b.mkv", "c.mkv"]


def test_discovered_group_is_frozen():
    from dataclasses import FrozenInstanceError

    g = DiscoveredGroup(source_path=Path("/x"))
    with pytest.raises(FrozenInstanceError):
        g.source_path = Path("/y")  # type: ignore[misc]


def test_non_video_files_at_movie_level_are_loose(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    m = root / "Movie"
    m.mkdir()
    (m / "Movie.mkv").write_text("v")
    (m / "Movie.nfo").write_text("n")
    (m / "Movie.srt").write_text("s")
    (group,) = TwoLevelDiscoverer().discover(root)
    assert [p.name for p in group.video_files] == ["Movie.mkv"]
    assert sorted(p.name for p in group.loose_files) == ["Movie.nfo", "Movie.srt"]
