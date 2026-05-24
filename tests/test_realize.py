"""Tests for the Realizer: Plan → filesystem actions."""

from __future__ import annotations

from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.materializer import HardlinkMaterializer
from jellyplex_sync.model import MovieInfo
from jellyplex_sync.plan import Plan, PlannedAsset, PlannedFile, PlannedMovie
from jellyplex_sync.planner import Planner
from jellyplex_sync.realize import Realizer, RealizeStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_target(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return source, target


def _plan_from(source: Path, target: Path) -> Plan:
    """End-to-end helper: build a Plan via the Planner so we exercise the
    same wiring the CLI will."""
    return Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
    ).plan()


# ---------------------------------------------------------------------------
# Empty / no-op
# ---------------------------------------------------------------------------


def test_empty_plan_does_nothing(tmp_path):
    source, target = _make_source_target(tmp_path)
    plan = _plan_from(source, target)
    stats = Realizer().apply(plan)
    assert stats.movies_processed == 0
    assert stats.files_linked == 0
    assert stats.files_removed == 0
    assert list(target.iterdir()) == []


def test_apply_raises_when_target_missing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    plan = Plan(
        source_root=source,
        target_root=tmp_path / "absent",
        source_format="plex",
        target_format="jellyfin",
    )
    with pytest.raises(ValueError, match="does not exist"):
        Realizer().apply(plan)


# ---------------------------------------------------------------------------
# Simple sync
# ---------------------------------------------------------------------------


def test_one_movie_one_video_materializes(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020) {imdb-tt0000001}"
    movie.mkdir()
    src_video = movie / "Movie (2020) {imdb-tt0000001} [1080p].mkv"
    src_video.write_text("v")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan)

    expected_dir = target / "Movie (2020) [imdbid-tt0000001]"
    expected_file = expected_dir / "Movie (2020) [imdbid-tt0000001] - BD.mkv"
    assert expected_file.is_file()
    assert expected_file.samefile(src_video)  # hardlink default
    assert stats.movies_processed == 1
    assert stats.files_linked == 1


def test_loose_files_and_assets_are_materialized(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    (movie / "poster.jpg").write_text("p")
    extras = movie / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")
    nested = extras / "deleted scenes"
    nested.mkdir()
    (nested / "scene1.mp4").write_text("s")

    plan = _plan_from(source, target)
    Realizer().apply(plan)

    out = target / "Movie (2020)"
    assert (out / "Movie (2020).mkv").is_file()
    assert (out / "poster.jpg").is_file()
    assert (out / "extras" / "trailer.mp4").is_file()
    assert (out / "extras" / "deleted scenes" / "scene1.mp4").is_file()


def test_idempotent_second_run_skips(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")

    plan = _plan_from(source, target)
    stats1 = Realizer().apply(plan)
    stats2 = Realizer().apply(plan)
    assert stats1.files_linked == 1
    assert stats2.files_linked == 0  # already hardlinked → skip


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_touch_filesystem(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, dry_run=True)
    # Target should still be empty.
    assert list(target.iterdir()) == []
    # But stats and events were recorded.
    assert stats.movies_processed == 1
    assert stats.files_linked == 1
    actions = [e.action for e in stats.events]
    assert "link" in actions


# ---------------------------------------------------------------------------
# Stray detection
# ---------------------------------------------------------------------------


def test_library_strays_are_detected_when_delete_false(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    # Pre-existing folder in target that isn't planned.
    (target / "Orphan Folder").mkdir()

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=False)
    assert "Orphan Folder" in stats.strays_in_target
    assert (target / "Orphan Folder").is_dir()  # not removed


def test_library_strays_are_removed_when_delete_true(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    orphan = target / "Orphan Folder"
    orphan.mkdir()
    (orphan / "junk.mkv").write_text("j")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=True)
    assert "Orphan Folder" in stats.strays_in_target
    assert not orphan.exists()
    assert stats.files_removed == 1


def test_movie_strays_are_removed_when_delete_true(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")

    # Pre-create the target movie folder with stale content.
    target_dir = target / "Movie (2020)"
    target_dir.mkdir()
    (target_dir / "old_file.txt").write_text("old")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=True)

    assert not (target_dir / "old_file.txt").exists()
    assert (target_dir / "Movie (2020).mkv").exists()
    assert stats.files_removed == 1


def test_asset_strays_are_removed_when_delete_true(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    extras = movie / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")

    # Pre-existing target with stale asset content.
    target_extras = target / "Movie (2020)" / "extras"
    target_extras.mkdir(parents=True)
    (target_extras / "stale.mp4").write_text("old")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=True)

    assert not (target_extras / "stale.mp4").exists()
    assert (target_extras / "trailer.mp4").exists()
    assert stats.files_removed == 1


# ---------------------------------------------------------------------------
# FileEvent tracking
# ---------------------------------------------------------------------------


def test_events_are_emitted_for_link_and_remove(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    (target / "Orphan").mkdir()

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=True)

    actions = [e.action for e in stats.events]
    assert "link" in actions
    assert "remove" in actions
    # The remove event carries its context.
    remove_event = next(e for e in stats.events if e.action == "remove")
    assert remove_event.context == "library_stray"


def test_events_distinguish_movie_vs_asset_vs_library_stray(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    extras = movie / "extras"
    extras.mkdir()
    (extras / "trailer.mp4").write_text("t")

    # Pre-seed: orphan at library, stale at movie level, stale at asset level.
    (target / "lib-orphan").mkdir()
    target_movie = target / "Movie (2020)"
    target_movie.mkdir()
    (target_movie / "stale-at-movie.txt").write_text("x")
    target_extras = target_movie / "extras"
    target_extras.mkdir()
    (target_extras / "stale-at-asset.mp4").write_text("x")

    plan = _plan_from(source, target)
    stats = Realizer().apply(plan, delete=True)

    contexts = {
        e.target.name: e.context
        for e in stats.events
        if e.action == "remove"
    }
    assert contexts == {
        "lib-orphan": "library_stray",
        "stale-at-movie.txt": "movie_stray",
        "stale-at-asset.mp4": "asset_stray",
    }


# ---------------------------------------------------------------------------
# Stats wiring
# ---------------------------------------------------------------------------


def test_stats_ignored_count_comes_from_plan(tmp_path):
    source, target = _make_source_target(tmp_path)
    (source / "junk-at-root.txt").write_text("x")
    plan = _plan_from(source, target)
    assert len(plan.ignored) == 1
    stats = Realizer().apply(plan)
    assert stats.ignored_count == 1


def test_caller_supplied_stats_is_reused(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")
    pre = RealizeStats()
    pre.files_linked = 99  # caller can pre-seed counters

    plan = _plan_from(source, target)
    out = Realizer().apply(plan, stats=pre)
    assert out is pre
    assert pre.files_linked == 100


# ---------------------------------------------------------------------------
# Materializer is honoured (sanity check, not full materializer test coverage)
# ---------------------------------------------------------------------------


def test_default_materializer_is_hardlink(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    src_video = movie / "Movie (2020).mkv"
    src_video.write_text("v")
    plan = _plan_from(source, target)
    Realizer().apply(plan)
    dst = target / "Movie (2020)" / "Movie (2020).mkv"
    assert dst.samefile(src_video)


def test_custom_materializer_is_used(tmp_path):
    source, target = _make_source_target(tmp_path)
    movie = source / "Movie (2020)"
    movie.mkdir()
    (movie / "Movie (2020).mkv").write_text("v")

    class Counting(HardlinkMaterializer):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def materialize(self, src, dst, **kw):
            self.calls += 1
            return super().materialize(src, dst, **kw)

    mat = Counting()
    plan = _plan_from(source, target)
    Realizer(materializer=mat).apply(plan)
    assert mat.calls == 1


# ---------------------------------------------------------------------------
# Synthetic Plan (no Planner involved) — guards against Planner coupling
# ---------------------------------------------------------------------------


def test_realize_synthetic_plan_directly(tmp_path):
    """Realizer should consume any well-formed Plan, not just ones the
    Planner built. This guards against accidentally coupling Realizer to
    Planner internals."""
    source, target = _make_source_target(tmp_path)
    src_file = source / "data.txt"
    src_file.write_text("d")

    pm = PlannedMovie(
        source_path=source / "M",
        target_folder=target / "M",
        movie=MovieInfo(title="M"),
        videos=(PlannedFile(source=src_file, target_name="renamed.txt"),),
    )
    plan = Plan(
        source_root=source,
        target_root=target,
        source_format="plex",
        target_format="jellyfin",
        movies=(pm,),
    )
    Realizer().apply(plan)
    assert (target / "M" / "renamed.txt").is_file()


def test_realize_synthetic_plan_with_nested_assets(tmp_path):
    source, target = _make_source_target(tmp_path)
    src_a = source / "a.mp4"
    src_b = source / "b.mp4"
    src_a.write_text("a")
    src_b.write_text("b")

    inner = PlannedAsset(
        source=source / "inner",
        folder_name="deep",
        files=(PlannedFile(source=src_b, target_name="b.mp4"),),
    )
    outer = PlannedAsset(
        source=source / "outer",
        folder_name="extras",
        files=(PlannedFile(source=src_a, target_name="a.mp4"),),
        subfolders=(inner,),
    )
    pm = PlannedMovie(
        source_path=source / "M",
        target_folder=target / "M",
        movie=MovieInfo(title="M"),
        assets=(outer,),
    )
    plan = Plan(
        source_root=source,
        target_root=target,
        source_format="plex",
        target_format="jellyfin",
        movies=(pm,),
    )
    Realizer().apply(plan)
    assert (target / "M" / "extras" / "a.mp4").is_file()
    assert (target / "M" / "extras" / "deep" / "b.mp4").is_file()
