"""Tests for the Planner orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.disambig import (
    HashFallbackDisambiguator,
    NaiveDisambiguator,
    _short_hash,
)
from jellyplex_sync.library import CollectingReporter
from jellyplex_sync.planner import Planner


def _make_planner(
    tmp_path: Path,
    *,
    source_format: str = "plex",
    target_format: str = "jellyfin",
    disambiguator=None,
    reporter=None,
) -> tuple[Planner, Path, Path]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    reader_cls = {
        "plex": jp.PlexLibraryReader,
        "jellyfin": jp.JellyfinLibraryReader,
    }[source_format]
    writer_cls = {
        "plex": jp.PlexLibraryWriter,
        "jellyfin": jp.JellyfinLibraryWriter,
    }[target_format]
    planner = Planner(
        reader=reader_cls(source),
        writer=writer_cls(target),
        disambiguator=disambiguator,
        reporter=reporter or CollectingReporter(),
    )
    return planner, source, target


# ---------------------------------------------------------------------------
# Empty / trivial inputs
# ---------------------------------------------------------------------------


def test_empty_library_yields_empty_plan(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    plan = planner.plan()
    assert plan.movies == ()
    assert plan.ignored == ()
    assert plan.clashes == ()
    assert plan.folder_clashes == ()
    assert plan.source_format == "plex"
    assert plan.target_format == "jellyfin"
    assert plan.source_root == source.resolve()
    assert plan.target_root == target.resolve()


def test_source_equal_target_raises(tmp_path):
    source = tmp_path / "lib"
    source.mkdir()
    planner = Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(source),
    )
    with pytest.raises(ValueError, match="into itself"):
        planner.plan()


# ---------------------------------------------------------------------------
# Happy path: simple movies translate
# ---------------------------------------------------------------------------


def test_simple_plex_movie_planned_to_jellyfin(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    movie = source / "Das Boot (1981) {imdb-tt0082096}"
    movie.mkdir()
    (movie / "Das Boot (1981) {imdb-tt0082096} [1080p].mkv").write_text("v")
    plan = planner.plan()
    assert len(plan.movies) == 1
    pm = plan.movies[0]
    assert pm.source_path == movie
    assert pm.target_folder == target.resolve() / "Das Boot (1981) [imdbid-tt0082096]"
    assert len(pm.videos) == 1
    assert pm.videos[0].target_name == "Das Boot (1981) [imdbid-tt0082096] - BD.mkv"
    assert pm.videos[0].disambiguation is None


def test_loose_files_pass_through_unchanged(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    (movie / "poster.jpg").write_text("p")
    (movie / "Movie.nfo").write_text("n")
    plan = planner.plan()
    pm = plan.movies[0]
    loose_names = sorted(f.target_name for f in pm.loose_files)
    assert loose_names == ["Movie.nfo", "poster.jpg"]


def test_assets_recurse(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    extras = movie / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")
    nested = extras / "deleted scenes"
    nested.mkdir()
    (nested / "scene1.mp4").write_text("s")
    plan = planner.plan()
    pm = plan.movies[0]
    assert len(pm.assets) == 1
    extras_asset = pm.assets[0]
    assert extras_asset.folder_name == "extras"
    assert [f.target_name for f in extras_asset.files] == ["trailer.mp4"]
    assert len(extras_asset.subfolders) == 1
    assert extras_asset.subfolders[0].folder_name == "deleted scenes"
    assert [f.target_name for f in extras_asset.subfolders[0].files] == ["scene1.mp4"]


# ---------------------------------------------------------------------------
# Ignored entries
# ---------------------------------------------------------------------------


def test_top_level_file_becomes_ignored(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    (source / "loose-junk.txt").write_text("j")
    plan = planner.plan()
    assert plan.movies == ()
    assert any(e.path.name == "loose-junk.txt" for e in plan.ignored)


def test_unparseable_folder_becomes_ignored(tmp_path):
    # Plex is permissive — it always returns a MovieInfo. The Jellyfin reader
    # is stricter: a folder name that is only an ID block parses to no title.
    planner, source, _ = _make_planner(tmp_path, source_format="jellyfin")
    bad = source / "[imdbid-tt1234567]"
    bad.mkdir()
    (bad / "video.mkv").write_text("v")
    plan = planner.plan()
    assert plan.movies == ()
    assert any(e.reason == "unparseable folder name" for e in plan.ignored)


# ---------------------------------------------------------------------------
# Folder-level clash
# ---------------------------------------------------------------------------


def test_two_folders_collapsing_to_one_target_folder_clash(tmp_path):
    """Two Plex folders that differ only in a bracket label (which the
    Jellyfin writer drops) collapse to the same Jellyfin folder name."""
    planner, source, target = _make_planner(tmp_path)
    a = source / "Movie (2020) {imdb-tt0000001} [Director's Cut]"
    b = source / "Movie (2020) {imdb-tt0000001} [Theatrical]"
    a.mkdir()
    b.mkdir()
    (a / "Movie (2020).mkv").write_text("v")
    (b / "Movie (2020).mkv").write_text("v")
    plan = planner.plan()
    assert plan.movies == ()
    assert len(plan.folder_clashes) == 1
    fc = plan.folder_clashes[0]
    assert fc.target_folder_name == "Movie (2020) [imdbid-tt0000001]"
    assert set(fc.source_folder_names) == {a.name, b.name}


# ---------------------------------------------------------------------------
# Movie-level (video) clash
# ---------------------------------------------------------------------------


def test_naive_disambiguator_records_movie_clash(tmp_path):
    planner, source, target = _make_planner(
        tmp_path, disambiguator=NaiveDisambiguator()
    )
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020) [1080p].mkv").write_text("v")
    (movie / "Movie (2020) [1080p] [remux].mkv").write_text("v")
    plan = planner.plan()
    # Both videos would collapse to "Movie (2020) - BD.mkv". Naive bails.
    assert len(plan.clashes) == 1
    # No PlannedMovie because every video clashed and there's nothing else.
    assert plan.movies == ()


def test_hash_fallback_resolves_clash_into_planned_movie(tmp_path):
    planner, source, target = _make_planner(
        tmp_path, disambiguator=HashFallbackDisambiguator()
    )
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020) [1080p].mkv").write_text("v")
    (movie / "Movie (2020) [1080p] [remux].mkv").write_text("v")
    plan = planner.plan()
    assert plan.clashes == ()
    assert len(plan.movies) == 1
    pm = plan.movies[0]
    assert len(pm.videos) == 2
    # Both have a DisambiguationNote and unique names.
    names = {v.target_name for v in pm.videos}
    assert len(names) == 2
    for v in pm.videos:
        assert v.disambiguation is not None
        assert v.disambiguation.strategy == "hash_suffix"


def test_hash_fallback_unaffected_videos_have_no_note(tmp_path):
    planner, source, target = _make_planner(
        tmp_path, disambiguator=HashFallbackDisambiguator()
    )
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020) [1080p].mkv").write_text("v")
    (movie / "Movie (2020) [2160p].mkv").write_text("v")
    plan = planner.plan()
    for v in plan.movies[0].videos:
        assert v.disambiguation is None


# ---------------------------------------------------------------------------
# Determinism / Reproducibility
# ---------------------------------------------------------------------------


def test_plan_is_reproducible_across_runs(tmp_path):
    planner, source, target = _make_planner(tmp_path)
    for name in ["Movie A (2020)", "Movie B (2021)", "Movie C (2019)"]:
        d = source / name
        d.mkdir()
        (d / f"{name}.mkv").write_text("v")
    plan1 = planner.plan()
    plan2 = planner.plan()
    assert plan1 == plan2


def test_plan_uses_default_hash_fallback_disambiguator(tmp_path):
    """No disambiguator passed → HashFallback default → clashes get resolved."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    planner = Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
    )
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020) [1080p].mkv").write_text("v")
    (movie / "Movie (2020) [1080p] [remux].mkv").write_text("v")
    plan = planner.plan()
    assert plan.clashes == ()
    assert len(plan.movies) == 1
    assert len(plan.movies[0].videos) == 2


# ---------------------------------------------------------------------------
# Reporter integration: drops are observed
# ---------------------------------------------------------------------------


def test_reporter_collects_translation_drops(tmp_path):
    reporter = CollectingReporter()
    planner, source, _ = _make_planner(tmp_path, reporter=reporter)
    movie = source / "Movie (2020)"
    movie.mkdir()
    # [remux] is non-resolution → drop on Jellyfin writer.
    (movie / "Movie (2020) [1080p] [remux].mkv").write_text("v")
    planner.plan()
    label_drops = [d for d in reporter.drops if d.kind == "label"]
    assert any(d.value == "remux" for d in label_drops)


# ---------------------------------------------------------------------------
# Lint mode: source format == target format
# ---------------------------------------------------------------------------


def test_lint_mode_plex_to_plex(tmp_path):
    planner, source, _ = _make_planner(
        tmp_path, source_format="plex", target_format="plex"
    )
    movie = source / "Movie (2020) {imdb-tt0000001}"
    movie.mkdir()
    (movie / "Movie (2020) {imdb-tt0000001}.mkv").write_text("v")
    plan = planner.plan()
    assert len(plan.movies) == 1
    pm = plan.movies[0]
    assert pm.videos[0].target_name == "Movie (2020) {imdb-tt0000001}.mkv"
    assert plan.source_format == plan.target_format == "plex"
