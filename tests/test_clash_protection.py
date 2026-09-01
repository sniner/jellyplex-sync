"""Skipped-because-of-clash must mean: the target stays untouched.

A movie the Disambiguator cannot resolve is absent from the Plan — but a
previous run may have synced it. Without protection, the Realizer would
count its target folder (or the collapsed video name) as a stray and
`--delete` would destroy data of a movie the summary reports as
"skipped". These tests pin the protection and, alongside it, that
genuine strays are still removed.
"""

from __future__ import annotations

from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.disambig import NaiveDisambiguator
from jellyplex_sync.planner import Planner
from jellyplex_sync.realize import Realizer

TARGET_FOLDER = "Movie (2020) [imdbid-tt001]"
COLLAPSED_NAME = "Movie (2020) [imdbid-tt001] - BD.mkv"


def _clashing_source(tmp_path: Path) -> tuple[Path, Path]:
    """Plex source whose two videos collapse to the same Jellyfin name."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    movie = source / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    (movie / "Movie (2020) {imdb-tt001} [1080p].mkv").write_bytes(b"a")
    (movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv").write_bytes(b"b")
    return source, target


def _plan(source: Path, target: Path) -> jp.Plan:
    return Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
        disambiguator=NaiveDisambiguator(),
    ).plan()


def test_fully_clashed_movie_is_protected_in_plan(tmp_path: Path) -> None:
    source, target = _clashing_source(tmp_path)
    plan = _plan(source, target)
    assert plan.movies == ()
    assert len(plan.clashes) == 1
    assert plan.protected_folders == (TARGET_FOLDER,)


def test_delete_keeps_target_folder_of_clashed_movie(tmp_path: Path) -> None:
    source, target = _clashing_source(tmp_path)
    previous = target / TARGET_FOLDER
    previous.mkdir()
    (previous / COLLAPSED_NAME).write_bytes(b"old")

    plan = _plan(source, target)
    stats = Realizer().apply(plan, delete=True)

    assert (previous / COLLAPSED_NAME).is_file()
    assert stats.files_removed == 0
    assert stats.strays_in_target == []


def test_partial_clash_protects_the_collapsed_name_only(tmp_path: Path) -> None:
    """A movie that still has something to sync (here: a loose file) is
    planned — but the collapsed name of its clashing videos is spared,
    while genuine movie-level strays are still removed."""
    source, target = _clashing_source(tmp_path)
    (source / "Movie (2020) {imdb-tt001}" / "poster.jpg").write_bytes(b"p")

    movie_tgt = target / TARGET_FOLDER
    movie_tgt.mkdir()
    (movie_tgt / COLLAPSED_NAME).write_bytes(b"old")
    (movie_tgt / "junk.txt").write_bytes(b"j")

    plan = _plan(source, target)
    (pm,) = plan.movies
    assert pm.protected_files == (COLLAPSED_NAME,)

    Realizer().apply(plan, delete=True)

    assert (movie_tgt / COLLAPSED_NAME).is_file()
    assert not (movie_tgt / "junk.txt").exists()
    assert (movie_tgt / "poster.jpg").is_file()


def test_folder_clash_target_is_protected(tmp_path: Path) -> None:
    """Folder clashes skip both source folders; an existing target
    folder of the clash name must survive a delete run. (sync() aborts
    on folder clashes anyway — this pins the Realizer API contract.)"""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for label in ("A", "B"):
        folder = source / f"Movie (2020) {{imdb-tt001}} [{label}]"
        folder.mkdir()
        (folder / "v.mkv").write_bytes(b"x")
    previous = target / TARGET_FOLDER
    previous.mkdir()
    (previous / COLLAPSED_NAME).write_bytes(b"old")

    plan = _plan(source, target)
    assert plan.protected_folders == (TARGET_FOLDER,)

    stats = Realizer().apply(plan, delete=True)
    assert (previous / COLLAPSED_NAME).is_file()
    assert stats.files_removed == 0


def test_delete_still_removes_genuine_strays(tmp_path: Path) -> None:
    """The protection must not blunt --delete: a target folder with no
    source counterpart is still a stray and still gets removed."""
    source, target = _clashing_source(tmp_path)
    stray = target / "Old (1999) [imdbid-tt999]"
    stray.mkdir()
    (stray / "junk.mkv").write_bytes(b"j")

    plan = _plan(source, target)
    stats = Realizer().apply(plan, delete=True)

    assert not stray.exists()
    assert stats.strays_in_target == ["Old (1999) [imdbid-tt999]"]
