from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.sync import (
    LibraryStats,
    guess_library_type,
    process_assets_folder,
    process_movie,
    scan_media_library,
)


def _touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# scan_media_library
# ---------------------------------------------------------------------------


def test_scan_media_library_yields_each_movie(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    (src / "Second (1990) [imdbid-tt002]").mkdir()

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)

    results = list(scan_media_library(source, target))

    assert len(results) == 2
    target_names = {dst_path.name for _, dst_path, _ in results}
    assert target_names == {
        "First (1984) {imdb-tt001}",
        "Second (1990) {imdb-tt002}",
    }


def test_scan_media_library_skips_conflicting_sources(tmp_path: Path) -> None:
    """Two source folders that map to the same target name must not be yielded."""
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    # Both fold to the same Plex name `Movie (2000) {imdb-tt001}` because Plex
    # uses the same provider id in its naming scheme.
    (src / "Movie (2000) [imdbid-tt001]").mkdir()
    (src / "Movie (2000) - [imdbid-tt001]").mkdir()

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    stats = LibraryStats()

    results = list(scan_media_library(source, target, stats=stats))

    assert results == []
    assert stats.movies_total == 2


def test_scan_media_library_removes_stray_with_delete(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    stray = dst / "Stray (1999) {imdb-tt999}"
    stray.mkdir()

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, delete=True, stats=stats))

    assert not stray.exists()
    assert stats.items_removed == 1


def test_scan_media_library_dry_run_leaves_stray(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    stray = dst / "Stray"
    stray.mkdir()

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)

    list(scan_media_library(source, target, delete=True, dry_run=True))

    assert stray.exists()


def test_scan_media_library_rejects_same_base_dir(tmp_path: Path) -> None:
    src = tmp_path / "lib"
    src.mkdir()
    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(src)

    with pytest.raises(ValueError):
        list(scan_media_library(source, target))


# ---------------------------------------------------------------------------
# process_movie
# ---------------------------------------------------------------------------


def test_process_movie_hardlinks_video(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    src_video = _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"video-bytes")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie)

    expected = dst / "First (1984) {imdb-tt001}" / "First (1984) {imdb-tt001}.mkv"
    assert expected.exists()
    assert expected.samefile(src_video)
    assert stats.videos_total == 1
    assert stats.videos_linked == 1


def test_process_movie_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    process_movie(source, target, movie_dir, movie)
    second = process_movie(source, target, movie_dir, movie)

    assert second.videos_linked == 0
    assert second.videos_total == 1


def test_process_movie_dry_run_creates_nothing(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    process_movie(source, target, movie_dir, movie, dry_run=True)

    assert not (dst / "First (1984) {imdb-tt001}").exists()


def test_process_movie_syncs_asset_folder(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")
    _touch(movie_dir / "extras" / "trailer.mp4", b"t")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie)

    extras = dst / "First (1984) {imdb-tt001}" / "extras" / "trailer.mp4"
    assert extras.exists()
    assert stats.asset_items_linked == 1


def test_process_movie_ignores_dotfolders(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")
    _touch(movie_dir / ".hidden" / "secret.txt", b"x")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    process_movie(source, target, movie_dir, movie)

    assert not (dst / "First (1984) {imdb-tt001}" / ".hidden").exists()


def test_process_movie_removes_stray_with_delete(tmp_path: Path) -> None:
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    target_movie_dir = dst / "First (1984) {imdb-tt001}"
    target_movie_dir.mkdir()
    stray_file = _touch(target_movie_dir / "leftover.txt", b"old")

    source = jp.JellyfinLibrary(src)
    target = jp.PlexLibrary(dst)
    movie = source.parse_movie_path(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie, delete=True)

    assert not stray_file.exists()
    assert stats.items_removed == 1


# ---------------------------------------------------------------------------
# process_assets_folder
# ---------------------------------------------------------------------------


def test_process_assets_folder_recurses(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", b"a")
    _touch(src / "sub" / "b.txt", b"b")
    _touch(src / "sub" / "deeper" / "c.txt", b"c")

    stats = process_assets_folder(src, dst)

    assert (dst / "a.txt").exists()
    assert (dst / "sub" / "b.txt").exists()
    assert (dst / "sub" / "deeper" / "c.txt").exists()
    assert stats.files_total == 3
    assert stats.files_linked == 3


def test_process_assets_folder_removes_stray_with_delete(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "keep.txt", b"k")
    dst.mkdir()
    stray = _touch(dst / "old.txt", b"o")

    stats = process_assets_folder(src, dst, delete=True)

    assert not stray.exists()
    assert stats.items_removed == 1


def test_process_assets_folder_skips_already_linked(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    src_file = _touch(src / "a.txt", b"a")
    (dst / "a.txt").hardlink_to(src_file)

    stats = process_assets_folder(src, dst)

    assert stats.files_linked == 0
    assert stats.files_total == 1


def test_process_assets_folder_rejects_non_directory(tmp_path: Path) -> None:
    src_file = _touch(tmp_path / "not-a-dir.txt", b"x")
    with pytest.raises(ValueError):
        process_assets_folder(src_file, tmp_path / "dst")


# ---------------------------------------------------------------------------
# guess_library_type
# ---------------------------------------------------------------------------


def test_guess_library_type_detects_plex(tmp_path: Path) -> None:
    movie_dir = tmp_path / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001}.mkv", b"v")

    assert guess_library_type(tmp_path) is jp.PlexLibrary


def test_guess_library_type_detects_jellyfin(tmp_path: Path) -> None:
    movie_dir = tmp_path / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    assert guess_library_type(tmp_path) is jp.JellyfinLibrary


def test_guess_library_type_detects_plex_edition(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Das Boot (1981)"
    movie_dir.mkdir()
    _touch(movie_dir / "Das Boot (1981) {edition-Director's Cut}.mkv", b"v")

    assert guess_library_type(tmp_path) is jp.PlexLibrary


def test_guess_library_type_returns_none_when_unclear(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Plain Movie (2001)"
    movie_dir.mkdir()
    _touch(movie_dir / "Plain Movie (2001).mkv", b"v")

    assert guess_library_type(tmp_path) is None
