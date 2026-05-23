import io
from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.sync import diff


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _seed_source(src: Path, movies: list[str]) -> None:
    """Create a minimal Plex-format source library."""
    src.mkdir(parents=True, exist_ok=True)
    for folder_name in movies:
        movie_dir = src / folder_name
        movie_dir.mkdir()
        _touch(movie_dir / f"{folder_name}.mkv", b"v")


def _seed_synced_target(src: Path, dst: Path) -> None:
    """Run a real sync once so source and target are aligned."""
    dst.mkdir(parents=True, exist_ok=True)
    rc = jp.sync(str(src), str(dst))
    assert rc == 0


# ---------------------------------------------------------------------------
# exit codes and high-level behavior
# ---------------------------------------------------------------------------


def test_diff_returns_zero_when_in_sync(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    _seed_synced_target(src, dst)

    buf = io.StringIO()
    assert diff(str(src), str(dst), out=buf) == 0
    assert "In sync" in buf.getvalue()


def test_diff_returns_one_when_target_missing_movie(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    dst.mkdir()  # empty target

    buf = io.StringIO()
    assert diff(str(src), str(dst), out=buf) == 1
    assert "only in source" in buf.getvalue().lower()


def test_diff_returns_one_when_target_has_stray(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    _seed_synced_target(src, dst)
    (dst / "Stray Folder (2099)").mkdir()

    buf = io.StringIO()
    assert diff(str(src), str(dst), out=buf) == 1
    assert "only in target" in buf.getvalue().lower()
    assert "Stray Folder (2099)" in buf.getvalue()


def test_diff_returns_one_when_file_differs_within_movie(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    _seed_synced_target(src, dst)
    target_movie_dir = next(dst.iterdir())
    _touch(target_movie_dir / "extra-stuff.txt", b"junk")

    buf = io.StringIO()
    assert diff(str(src), str(dst), out=buf) == 1
    assert "file differences" in buf.getvalue().lower()
    assert "extra-stuff.txt" in buf.getvalue()


def test_diff_returns_two_when_source_missing(tmp_path: Path):
    dst = tmp_path / "dst"
    dst.mkdir()
    buf = io.StringIO()
    rc = diff(str(tmp_path / "no-such"), str(dst), out=buf)
    assert rc == 2


def test_diff_returns_two_when_target_missing(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    buf = io.StringIO()
    rc = diff(str(src), str(tmp_path / "no-such"), out=buf)
    assert rc == 2


# ---------------------------------------------------------------------------
# read-only guarantee
# ---------------------------------------------------------------------------


def test_diff_does_not_touch_filesystem(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    dst.mkdir()
    (dst / "Stray (2099)").mkdir()

    snapshot_before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    diff(str(src), str(dst), out=io.StringIO())
    snapshot_after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    assert snapshot_before == snapshot_after, "diff must not change the filesystem"


# ---------------------------------------------------------------------------
# translation-loss reporting
# ---------------------------------------------------------------------------


def test_diff_reports_translation_drops(tmp_path: Path):
    """A Plex `[remux]` label has no equivalent in a Jellyfin version label
    and gets reported as a translation loss in the diff output."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001} [remux].mkv", b"v")

    buf = io.StringIO()
    rc = diff(str(src), str(dst), out=buf)
    output = buf.getvalue()

    # Exit code 1 because the movie is also only-in-source, not because of
    # the drop alone.
    assert rc == 1
    assert "Translation losses" in output
    assert "remux" in output


# ---------------------------------------------------------------------------
# format auto-detection vs explicit
# ---------------------------------------------------------------------------


def test_diff_honors_format_override(tmp_path: Path):
    """If the source contains Plex-format movies, asking diff to keep the
    target as Plex (lint/no-op) should detect that the target is also
    empty/mismatched."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed_source(src, ["First (1984) {imdb-tt001}"])
    dst.mkdir()

    buf = io.StringIO()
    rc = diff(
        str(src),
        str(dst),
        source_format="plex",
        target_format="plex",
        out=buf,
    )
    # Plex → Plex still expects the movie to exist in target.
    assert rc == 1
