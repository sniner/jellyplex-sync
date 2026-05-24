"""Tests for `guess_library_type` — the auto-detect heuristic used by
sync()/diff()/plan() when --source-format=auto.

The bulk of this file used to test the pre-0.3 scan_media_library /
process_movie / process_assets_folder internals; those have been
removed in the 0.3 pipeline rewrite and their tests are now covered
by test_planner.py, test_realize.py, test_compare.py,
test_sync_pipeline.py, test_plan_function.py, and the end-to-end
test_e2e_generator.py."""

from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.sync import guess_library_type


def _touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_guess_library_type_detects_plex(tmp_path: Path) -> None:
    movie_dir = tmp_path / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001}.mkv", b"v")

    assert guess_library_type(tmp_path) is jp.PlexLibraryReader


def test_guess_library_type_detects_jellyfin(tmp_path: Path) -> None:
    movie_dir = tmp_path / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    assert guess_library_type(tmp_path) is jp.JellyfinLibraryReader


def test_guess_library_type_detects_plex_edition(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Das Boot (1981)"
    movie_dir.mkdir()
    _touch(movie_dir / "Das Boot (1981) {edition-Director's Cut}.mkv", b"v")

    assert guess_library_type(tmp_path) is jp.PlexLibraryReader


def test_guess_library_type_returns_none_when_unclear(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Plain Movie (2001)"
    movie_dir.mkdir()
    _touch(movie_dir / "Plain Movie (2001).mkv", b"v")

    assert guess_library_type(tmp_path) is None
