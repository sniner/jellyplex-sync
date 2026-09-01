"""The Plan records its own translation losses.

Folder-level drops land on `PlannedMovie.folder_drops`, per-video drops
on `PlannedFile.drops`; `collect_drops()` flattens them in plan order.
The Planner's reporter sees exactly the recorded drops — each one once,
which also pins the fix for the old double-reporting (movie-level drops
used to be re-reported once per video file).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.compare import compare
from jellyplex_sync.json_output import write_plan_json
from jellyplex_sync.library import CollectingReporter, Reporter
from jellyplex_sync.plan import Plan, collect_drops
from jellyplex_sync.planner import Planner


def _plan_for(tmp_path: Path, *, reporter: Reporter | None = None) -> Plan:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir(exist_ok=True)
    target.mkdir(exist_ok=True)
    return Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
        reporter=reporter,
    ).plan()


def _movie_with_losses(tmp_path: Path) -> Path:
    """One movie whose translation to Jellyfin loses on both levels:
    the second provider ID at folder level, `[remux]` at video level."""
    movie = tmp_path / "source" / "Movie (2020) {imdb-tt001} {tmdb-123}"
    movie.mkdir(parents=True, exist_ok=True)
    (movie / "Movie (2020) {imdb-tt001} {tmdb-123} [1080p] [remux].mkv").write_bytes(b"v")
    return movie


def test_plan_records_folder_and_video_drops(tmp_path: Path) -> None:
    _movie_with_losses(tmp_path)
    plan = _plan_for(tmp_path)

    (pm,) = plan.movies
    assert any(d.key == "tmdb" for d in pm.folder_drops)
    (video,) = pm.videos
    assert [d.value for d in video.drops] == ["remux"]
    # The folder-level loss is not repeated on the video.
    assert not any(d.key == "tmdb" for d in video.drops)


def test_collect_drops_flattens_in_plan_order(tmp_path: Path) -> None:
    _movie_with_losses(tmp_path)
    plan = _plan_for(tmp_path)

    (pm,) = plan.movies
    assert collect_drops(plan) == pm.folder_drops + pm.videos[0].drops


def test_reporter_sees_each_recorded_drop_once(tmp_path: Path) -> None:
    _movie_with_losses(tmp_path)
    reporter = CollectingReporter()
    plan = _plan_for(tmp_path, reporter=reporter)

    assert reporter.drops == list(collect_drops(plan))


def test_compare_carries_plan_drops(tmp_path: Path) -> None:
    _movie_with_losses(tmp_path)
    plan = _plan_for(tmp_path)

    result = compare(plan)
    assert result.drops == collect_drops(plan)
    assert any(d.value == "remux" for d in result.drops)


def test_plan_json_carries_per_file_drops(tmp_path: Path) -> None:
    _movie_with_losses(tmp_path)
    plan = _plan_for(tmp_path)

    buf = io.StringIO()
    write_plan_json(buf, plan)
    doc = json.loads(buf.getvalue())

    movie_doc = doc["movies"][0]
    assert any(d["key"] == "tmdb" for d in movie_doc["folder_drops"])
    (video_doc,) = movie_doc["videos"]
    assert [d["value"] for d in video_doc["drops"]] == ["remux"]
    # The deduplicated top-level list still exists, fed from the plan.
    assert doc["summary"]["translation_losses"] == len(doc["translation_losses"])
    assert any(d["value"] == "remux" for d in doc["translation_losses"])


def test_drop_free_plan_stays_lean(tmp_path: Path) -> None:
    """Lossless translations produce no drop fields — neither in the IR
    nor as JSON keys."""
    movie = tmp_path / "source" / "Movie (2020) {imdb-tt001}"
    movie.mkdir(parents=True)
    (movie / "Movie (2020) {imdb-tt001} [1080p].mkv").write_bytes(b"v")
    plan = _plan_for(tmp_path)

    (pm,) = plan.movies
    assert pm.folder_drops == ()
    assert pm.videos[0].drops == ()

    buf = io.StringIO()
    write_plan_json(buf, plan)
    doc = json.loads(buf.getvalue())
    assert "folder_drops" not in doc["movies"][0]
    assert "drops" not in doc["movies"][0]["videos"][0]
