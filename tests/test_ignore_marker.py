"""A directory containing `.jellyplex-sync-ignore` is left out of the run.

In the source it is treated as if it did not exist. In the target nothing
is written into it and nothing is removed from it, not even when a parent
folder is a stray under --delete. A marker in a library root stops the
whole run.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.library import IGNORE_MARKER, find_marked
from jellyplex_sync.planner import Planner
from jellyplex_sync.realize import Realizer

SRC_A = "A (2020) {imdb-tt001}"
SRC_B = "B (2021) {imdb-tt002}"
DST_A = "A (2020) [imdbid-tt001]"
DST_B = "B (2021) [imdbid-tt002]"


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _mark(folder: Path) -> None:
    _touch(folder / IGNORE_MARKER, b"")


def _libraries(tmp_path: Path, *movies: str) -> tuple[Path, Path]:
    """A Plex source with one video per movie, and an empty target."""
    src = (tmp_path / "src").resolve()
    dst = (tmp_path / "dst").resolve()
    src.mkdir()
    dst.mkdir()
    for name in movies:
        _touch(src / name / f"{name}.mkv", b"v")
    return src, dst


def _sync(
    src: Path,
    dst: Path,
    *,
    delete: bool = False,
    dry_run: bool = False,
    create: bool = False,
    verbose: bool = False,
) -> jp.SyncResult:
    return jp.sync(
        str(src),
        str(dst),
        source_format="plex",
        delete=delete,
        dry_run=dry_run,
        create=create,
        verbose=verbose,
    )


def _plan(src: Path, dst: Path) -> jp.Plan:
    return Planner(
        reader=jp.PlexLibraryReader(src),
        writer=jp.JellyfinLibraryWriter(dst),
    ).plan()


# ---------------------------------------------------------------------------
# find_marked
# ---------------------------------------------------------------------------


def test_find_marked_returns_outermost_folders_only(tmp_path: Path) -> None:
    _mark(tmp_path / "a")
    _mark(tmp_path / "a" / "inner")
    _mark(tmp_path / "b" / "deep")
    _touch(tmp_path / "c" / "file.mkv")

    assert find_marked(tmp_path) == [tmp_path / "a", tmp_path / "b" / "deep"]
    assert find_marked(tmp_path / "c" / "file.mkv") == []
    assert find_marked(tmp_path / "missing") == []


# ---------------------------------------------------------------------------
# Source side: as if the folder did not exist
# ---------------------------------------------------------------------------


def test_marked_source_movie_is_not_synced(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A, SRC_B)
    _mark(src / SRC_B)

    result = _sync(src, dst)

    assert result.exit_code == 0
    assert (dst / DST_A).is_dir()
    assert not (dst / DST_B).exists()
    assert result.stats.marked_in_source == [src / SRC_B]
    assert result.stats.movies_total == 1


def test_marked_source_movie_copy_becomes_a_stray(tmp_path: Path) -> None:
    """Marking a movie that was synced before leaves its copy in the
    target as a stray: kept without --delete, removed with it."""
    src, dst = _libraries(tmp_path, SRC_A, SRC_B)
    _sync(src, dst)
    _mark(src / SRC_B)

    result = _sync(src, dst)
    assert result.stats.strays_in_target == [DST_B]
    assert (dst / DST_B).is_dir()

    _sync(src, dst, delete=True)
    assert not (dst / DST_B).exists()
    assert (src / SRC_B / f"{SRC_B}.mkv").is_file()


def test_marked_source_asset_folders_are_skipped(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    movie = src / SRC_A
    _touch(movie / "extras" / "e.mkv")
    _mark(movie / "extras")
    _touch(movie / "other" / "o.mkv")
    _touch(movie / "other" / "private" / "p.mkv")
    _mark(movie / "other" / "private")

    plan = _plan(src, dst)
    (pm,) = plan.movies
    assert [a.folder_name for a in pm.assets] == ["other"]
    assert pm.assets[0].subfolders == ()
    assert plan.marked_in_source == (movie / "extras", movie / "other" / "private")

    _sync(src, dst)
    assert (dst / DST_A / "other" / "o.mkv").is_file()
    assert not (dst / DST_A / "extras").exists()
    assert not (dst / DST_A / "other" / "private").exists()


# ---------------------------------------------------------------------------
# Target side: nothing written into it, nothing removed from it
# ---------------------------------------------------------------------------


def test_marked_target_movie_folder_is_left_alone(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    own = _touch(dst / DST_A / "own.mkv", b"mine")
    _mark(dst / DST_A)

    plan = _plan(src, dst)
    assert plan.movies == ()
    assert plan.marked_in_target == (dst / DST_A,)

    result = _sync(src, dst, delete=True)
    assert sorted(p.name for p in (dst / DST_A).iterdir()) == [IGNORE_MARKER, "own.mkv"]
    assert own.read_bytes() == b"mine"
    assert result.stats.strays_in_target == []
    assert result.stats.items_removed == 0


def test_marked_target_folder_without_source_is_no_stray(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    own = _touch(dst / "Own (1999)" / "own.mkv")
    _mark(dst / "Own (1999)")

    result = _sync(src, dst, delete=True)

    assert own.is_file()
    assert result.stats.strays_in_target == []
    assert result.stats.marked_in_target == [dst / "Own (1999)"]


def test_marked_target_asset_folder_gets_nothing_written(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _touch(src / SRC_A / "extras" / "new.mkv")
    mine = _touch(dst / DST_A / "extras" / "mine.mkv")
    _mark(dst / DST_A / "extras")

    plan = _plan(src, dst)
    (pm,) = plan.movies
    assert pm.assets == ()
    assert plan.marked_in_target == (dst / DST_A / "extras",)

    _sync(src, dst, delete=True)
    assert (dst / DST_A / f"{DST_A}.mkv").is_file()
    assert mine.is_file()
    assert not (dst / DST_A / "extras" / "new.mkv").exists()


# ---------------------------------------------------------------------------
# Removal from above: a stray that holds a marked folder stays
# ---------------------------------------------------------------------------


def test_delete_keeps_marked_folder_inside_movie_folder(tmp_path: Path) -> None:
    """`old` has no counterpart in the source, so it is a stray inside
    the movie folder. Removing it would remove the marked folder."""
    src, dst = _libraries(tmp_path, SRC_A)
    _sync(src, dst)
    kept = _touch(dst / DST_A / "old" / "x.mkv")
    _mark(dst / DST_A / "old")
    deep = _touch(dst / DST_A / "older" / "junk.txt")
    _mark(dst / DST_A / "older" / "sub")
    junk = _touch(dst / DST_A / "junk.txt")

    _sync(src, dst, delete=True)

    assert kept.is_file()
    assert deep.is_file()
    assert not junk.exists()


def test_delete_keeps_marked_folder_inside_asset_folder(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _touch(src / SRC_A / "other" / "o.mkv")
    _sync(src, dst)
    kept = _touch(dst / DST_A / "other" / "old" / "x.mkv")
    _mark(dst / DST_A / "other" / "old")

    _sync(src, dst, delete=True)

    assert kept.is_file()
    assert (dst / DST_A / "other" / "o.mkv").is_file()


def test_library_stray_holding_a_marked_folder_is_no_stray(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    kept = _touch(dst / "Gone (1999)" / "extras" / "x.mkv")
    _mark(dst / "Gone (1999)" / "extras")
    _touch(dst / "Stray (2000)" / "s.mkv")

    result = _sync(src, dst, delete=True)

    assert kept.is_file()
    assert not (dst / "Stray (2000)").exists()
    assert result.stats.strays_in_target == ["Stray (2000)"]
    assert result.stats.marked_in_target == [dst / "Gone (1999)" / "extras"]


def test_dry_run_announces_no_removal_of_marked_folders(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _sync(src, dst)
    _touch(dst / DST_A / "old" / "x.mkv")
    _mark(dst / DST_A / "old")

    with caplog.at_level(logging.INFO):
        _sync(src, dst, delete=True, dry_run=True)

    assert not any(r.getMessage().startswith("DELETE") for r in caplog.records)
    assert f"Keeping '{DST_A}/old', it contains {IGNORE_MARKER}" in caplog.messages


# ---------------------------------------------------------------------------
# Marked library root: the run stops
# ---------------------------------------------------------------------------


def test_marked_source_root_changes_nothing_even_with_delete(tmp_path: Path) -> None:
    """A marked source root must not read as an empty library, or
    --delete would clear the target."""
    src, dst = _libraries(tmp_path, SRC_A)
    _sync(src, dst)
    _mark(src)

    result = _sync(src, dst, delete=True)

    assert result.exit_code == 0
    assert (dst / DST_A / f"{DST_A}.mkv").is_file()
    assert result.stats.marked_in_source == [src]
    assert result.stats.items_removed == 0


def test_marked_target_root_gets_nothing_written(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _mark(dst)

    result = _sync(src, dst)

    assert result.exit_code == 0
    assert [p.name for p in dst.iterdir()] == [IGNORE_MARKER]
    assert result.stats.marked_in_target == [dst]


def test_marked_source_root_does_not_create_the_target(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    dst.rmdir()
    _mark(src)

    result = _sync(src, dst, create=True)

    assert result.exit_code == 0
    assert not dst.exists()


def test_realizer_does_nothing_with_a_locked_plan(tmp_path: Path) -> None:
    """Library callers that skip sync() get the same protection."""
    src, dst = _libraries(tmp_path, SRC_A)
    _sync(src, dst)
    _mark(src)

    plan = _plan(src, dst)
    assert plan.locked_root == src

    stats = Realizer().apply(plan, delete=True)
    assert stats.files_removed == 0
    assert (dst / DST_A).is_dir()


def test_plan_reports_a_marked_root(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _mark(dst)

    out = io.StringIO()
    assert jp.plan(str(src), str(dst), out=out) == 0
    assert f"Empty plan: the target library contains {IGNORE_MARKER}" in out.getvalue()

    out = io.StringIO()
    assert jp.plan(str(src), str(dst), out=out, as_json=True) == 0
    doc = json.loads(out.getvalue())
    assert doc["movies"] == []
    assert doc["marked_in_target"] == [str(dst)]


def test_diff_refuses_a_marked_root(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A)
    _mark(src)

    out = io.StringIO()
    assert jp.diff(str(src), str(dst), out=out) == 2
    assert out.getvalue() == ""


# ---------------------------------------------------------------------------
# diff and plan output
# ---------------------------------------------------------------------------


def test_diff_ignores_marked_folders(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A, SRC_B)
    _sync(src, dst)
    _mark(src / SRC_B)
    _touch(dst / "Own (1999)" / "own.mkv")
    _mark(dst / "Own (1999)")
    _touch(dst / DST_A / "old" / "x.mkv")
    _mark(dst / DST_A / "old")
    _sync(src, dst, delete=True)

    out = io.StringIO()
    rc = jp.diff(str(src), str(dst), out=out)

    text = out.getvalue()
    assert rc == 0, text
    assert "In sync" in text
    assert f"Skipped because they contain {IGNORE_MARKER} (2):" in text
    assert f"  source '{SRC_B}'" in text
    assert "  target 'Own (1999)'" in text


def test_plan_lists_marked_folders(tmp_path: Path) -> None:
    src, dst = _libraries(tmp_path, SRC_A, SRC_B)
    _mark(src / SRC_B)
    _touch(dst / DST_A / "extras" / "mine.mkv")
    _mark(dst / DST_A / "extras")
    _touch(src / SRC_A / "extras" / "e.mkv")

    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out)
    text = out.getvalue()
    assert f"  source '{SRC_B}'" in text
    assert f"  target '{DST_A}/extras'" in text

    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out, as_json=True)
    doc = json.loads(out.getvalue())
    assert doc["summary"]["marked_in_source"] == 1
    assert doc["summary"]["marked_in_target"] == 1
    assert doc["marked_in_source"] == [str(src / SRC_B)]
    assert doc["marked_in_target"] == [str(dst / DST_A / "extras")]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_counts_marked_folders(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    src, dst = _libraries(tmp_path, SRC_A, SRC_B)
    _mark(src / SRC_B)
    _touch(dst / "Own (1999)" / "own.mkv")
    _mark(dst / "Own (1999)")

    with caplog.at_level(logging.INFO):
        _sync(src, dst)
    assert (
        f"2 folder(s) skipped because they contain {IGNORE_MARKER}. Pass --verbose to list them"
    ) in caplog.messages

    caplog.clear()
    with caplog.at_level(logging.INFO):
        _sync(src, dst, verbose=True)
    assert f"  source '{SRC_B}'" in caplog.messages
    assert "  target 'Own (1999)'" in caplog.messages


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def _import(staging: Path, dst: Path) -> jp.SyncResult:
    return jp.import_media(str(staging), str(dst), source_format="plex")


def test_import_skips_marked_staging_folders(tmp_path: Path) -> None:
    staging = (tmp_path / "staging").resolve()
    dst = (tmp_path / "dst").resolve()
    dst.mkdir()
    _touch(staging / f"{SRC_A}.mkv")
    held = _touch(staging / "hold" / "deeper" / f"{SRC_B}.mkv")
    _mark(staging / "hold")
    _touch(staging / ".Trash" / "x" / f"{SRC_B}.mkv")
    _mark(staging / ".Trash" / "x")

    result = _import(staging, dst)

    assert (dst / DST_A).is_dir()
    assert not (dst / DST_B).exists()
    assert held.is_file()
    assert result.stats.marked_in_source == [staging / "hold"]


def test_import_leaves_marked_target_folder_alone(tmp_path: Path) -> None:
    staging = (tmp_path / "staging").resolve()
    dst = (tmp_path / "dst").resolve()
    staged = _touch(staging / f"{SRC_A}.mkv")
    _mark(dst / DST_A)

    result = _import(staging, dst)

    assert staged.is_file()
    assert [p.name for p in (dst / DST_A).iterdir()] == [IGNORE_MARKER]
    assert result.stats.marked_in_target == [dst / DST_A]


def test_import_stops_at_a_marked_staging_root(tmp_path: Path) -> None:
    staging = (tmp_path / "staging").resolve()
    dst = (tmp_path / "dst").resolve()
    dst.mkdir()
    staged = _touch(staging / f"{SRC_A}.mkv")
    _mark(staging)

    result = _import(staging, dst)

    assert result.exit_code == 0
    assert staged.is_file()
    assert list(dst.iterdir()) == []
