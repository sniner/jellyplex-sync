"""Sanity tests for the Plan IR — primarily that the frozen invariant
holds. The architectural decision to use frozen dataclasses is part of
the public contract (callers can rely on a Plan not mutating under
them); these tests fence that decision in."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from jellyplex_sync.model import MovieInfo
from jellyplex_sync.plan import (
    DisambiguationNote,
    Plan,
    PlannedAsset,
    PlannedFile,
    PlannedMovie,
)


def _planned_file() -> PlannedFile:
    return PlannedFile(source=Path("/src/a.mkv"), target_name="a.mkv")


def test_planned_file_is_frozen():
    pf = _planned_file()
    with pytest.raises(FrozenInstanceError):
        pf.target_name = "b.mkv"  # type: ignore[misc]


def test_planned_asset_is_frozen():
    pa = PlannedAsset(source=Path("/src/extras"), folder_name="extras")
    with pytest.raises(FrozenInstanceError):
        pa.folder_name = "Extras"  # type: ignore[misc]


def test_planned_movie_is_frozen():
    pm = PlannedMovie(
        source_path=Path("/src/M"),
        target_folder=Path("/tgt/M"),
        movie=MovieInfo(title="M"),
    )
    with pytest.raises(FrozenInstanceError):
        pm.target_folder = Path("/elsewhere")  # type: ignore[misc]


def test_plan_is_frozen():
    plan = Plan(
        source_root=Path("/src"),
        target_root=Path("/tgt"),
        source_format="plex",
        target_format="jellyfin",
    )
    with pytest.raises(FrozenInstanceError):
        plan.source_format = "jellyfin"  # type: ignore[misc]


def test_disambiguation_note_is_frozen():
    note = DisambiguationNote(strategy="hash_suffix", detail="hash from source filename")
    with pytest.raises(FrozenInstanceError):
        note.strategy = "label_pullback"  # type: ignore[misc]


def test_planned_movie_defaults_are_empty_tuples():
    pm = PlannedMovie(
        source_path=Path("/src/M"),
        target_folder=Path("/tgt/M"),
        movie=MovieInfo(title="M"),
    )
    assert pm.videos == ()
    assert pm.loose_files == ()
    assert pm.assets == ()
    assert pm.folder_drops == ()


def test_planned_asset_can_nest():
    inner = PlannedAsset(source=Path("/src/extras/sub"), folder_name="sub")
    outer = PlannedAsset(
        source=Path("/src/extras"),
        folder_name="extras",
        subfolders=(inner,),
    )
    assert outer.subfolders[0] is inner


def test_plan_equality_is_value_based():
    p1 = Plan(
        source_root=Path("/src"),
        target_root=Path("/tgt"),
        source_format="plex",
        target_format="jellyfin",
    )
    p2 = Plan(
        source_root=Path("/src"),
        target_root=Path("/tgt"),
        source_format="plex",
        target_format="jellyfin",
    )
    assert p1 == p2
