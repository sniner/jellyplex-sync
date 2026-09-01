"""Failed removals must be visible.

`utils.remove()` already counts per-entry failures, but they used to
end at a log warning: the run still reported success. These tests pin
that failures reach the stats and the exit code — and that a clean
delete run still exits 0 (covered by test_sync_pipeline as well).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.planner import Planner
from jellyplex_sync.realize import Realizer
from jellyplex_sync.sync import LibraryStats

needs_nonroot = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="permission-based removal failures don't apply to root",
)


def _readonly_stray(target: Path) -> Path:
    """A stray folder whose contents cannot be removed (read-only dir)."""
    stray = target / "Old (1999) [imdbid-tt999]"
    stray.mkdir()
    (stray / "junk.mkv").write_bytes(b"j")
    stray.chmod(0o555)
    return stray


@needs_nonroot
def test_realizer_counts_remove_errors(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    stray = _readonly_stray(target)

    plan = Planner(
        reader=jp.PlexLibraryReader(source),
        writer=jp.JellyfinLibraryWriter(target),
    ).plan()
    try:
        stats = Realizer().apply(plan, delete=True)
    finally:
        stray.chmod(0o755)

    assert stats.remove_errors >= 1
    assert stats.files_removed == 0
    assert stray.is_dir()


@needs_nonroot
def test_sync_delete_exits_3_on_failed_removal(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    (movie / "Movie (2020) {imdb-tt001}.mkv").write_bytes(b"v")
    stray = _readonly_stray(dst)

    stats = LibraryStats()
    try:
        result = jp.sync(str(src), str(dst), delete=True, stats=stats)
    finally:
        stray.chmod(0o755)

    assert result.exit_code == 3
    assert stats.remove_errors >= 1
    # The rest of the sync still went through.
    assert stats.movies_processed == 1
    assert (dst / "Movie (2020) [imdbid-tt001]").is_dir()
