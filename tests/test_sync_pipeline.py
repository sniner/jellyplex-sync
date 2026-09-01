"""Smoke tests for the public `sync()` function — guards against drift
between the 0.3 Planner+Realizer pipeline and the caller-visible
contract (stats fields, exit code, summary, file placement).

These complement test_e2e_generator.py (jellyplex-gen-driven) and
test_sync.py (tests against the pre-0.3 internals). They cover the
seam where `sync()` glues Planner.plan() + Realizer.apply() together
and maps RealizeStats back onto LibraryStats."""

from __future__ import annotations

from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.library import CollectingReporter
from jellyplex_sync.sync import LibraryStats


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_sync_links_one_movie_end_to_end(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p].mkv", b"v")

    result = jp.sync(str(src), str(dst))
    assert result.exit_code == 0
    assert (dst / "Movie (2020) [imdbid-tt001]" / "Movie (2020) [imdbid-tt001] - BD.mkv").is_file()


def test_sync_stats_match_pipeline(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    for name in ("A", "B"):
        m = src / f"{name} (2020) {{imdb-tt00{name}}}"
        m.mkdir()
        _touch(m / f"{name}.mkv", b"v")
    _touch(src / "stray.txt", b"")

    stats = LibraryStats()
    result = jp.sync(str(src), str(dst), source_format="plex", stats=stats)
    assert result.exit_code == 0
    assert stats.movies_total == 2
    assert stats.movies_processed == 2
    assert stats.items_linked == 2
    assert len(stats.ignored) == 1


def test_sync_folder_clash_aborts_with_nonzero_exit(tmp_path: Path):
    """If two source folders map to the same target name, the whole run
    is aborted: nothing is synced, and the exit code says so (2) so
    scripts and cron jobs can detect the failure."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    # Both fold to the same Jellyfin folder name (the bracket label is dropped).
    a = src / "Movie (2020) {imdb-tt001} [Directors Cut]"
    b = src / "Movie (2020) {imdb-tt001} [Theatrical]"
    a.mkdir()
    b.mkdir()
    _touch(a / "v.mkv", b"x")
    _touch(b / "v.mkv", b"x")

    stats = LibraryStats()
    result = jp.sync(str(src), str(dst), source_format="plex", stats=stats)
    assert result.exit_code == 2
    assert stats.movies_processed == 0
    # Both folders are counted as candidates.
    assert stats.movies_total == 2
    # Nothing landed.
    assert list(dst.iterdir()) == []


def test_sync_delete_removes_library_stray(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001}.mkv", b"v")
    orphan = dst / "Old (1999) [imdbid-tt999]"
    orphan.mkdir()
    _touch(orphan / "junk.mkv", b"j")

    stats = LibraryStats()
    result = jp.sync(str(src), str(dst), delete=True, stats=stats)
    assert result.exit_code == 0
    assert not orphan.exists()
    # items_removed == 1 (one file inside one library stray).
    assert stats.items_removed == 1


def test_sync_dry_run_changes_nothing(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001}.mkv", b"v")

    stats = LibraryStats()
    result = jp.sync(str(src), str(dst), dry_run=True, stats=stats)
    assert result.exit_code == 0
    assert list(dst.iterdir()) == []
    # But the stats still record what would have happened.
    assert stats.movies_processed == 1
    assert stats.items_linked == 1


def test_sync_result_carries_run_metadata(tmp_path: Path):
    """SyncResult is the single return channel: exit code, resolved
    formats, stats, and the plan's translation losses. The CLI reads
    these instead of re-resolving formats (which re-walked the whole
    source tree under --json) or passing accumulators in."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv", b"v")

    result = jp.sync(str(src), str(dst))
    assert result.exit_code == 0
    assert result.source_format == "plex"
    assert result.target_format == "jellyfin"
    assert result.stats.movies_processed == 1
    assert any(d.value == "remux" for d in result.drops)


def test_sync_result_on_setup_error_has_no_formats(tmp_path: Path):
    result = jp.sync(str(tmp_path / "nope"), str(tmp_path))
    assert result.exit_code == 1
    assert result.source_format is None
    assert result.target_format is None


def test_sync_reporter_collects_drops(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    # [remux] gets dropped by the Jellyfin writer.
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv", b"v")

    reporter = CollectingReporter()
    jp.sync(str(src), str(dst), reporter=reporter)

    assert any(d.value == "remux" for d in reporter.drops if d.kind == "label")
