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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)

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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
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
    _touch(stray / "Stray.mkv", b"v")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)

    list(scan_media_library(source, target, delete=True, dry_run=True))

    assert stray.exists()


def test_scan_media_library_records_strays_without_delete(tmp_path: Path) -> None:
    """Strays in target are recorded in LibraryStats regardless of --delete,
    so the summary can warn about them. The migration scenario: user syncs
    from Plex layout into a directory that still holds old Jellyfin-format
    folders. Without this, the summary would falsely report "all in sync"
    while 55 zombie folders sit in target."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    # Two strays in target — both must show up regardless of delete flag.
    (dst / "Old (1990) {imdb-tt999}").mkdir()
    (dst / "Other (1991) {imdb-tt998}").mkdir()

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, stats=stats, delete=False))

    assert set(stats.strays_in_target) == {
        "Old (1990) {imdb-tt999}",
        "Other (1991) {imdb-tt998}",
    }
    assert stats.items_removed == 0  # nothing removed without --delete
    # Strays still on disk
    assert (dst / "Old (1990) {imdb-tt999}").exists()


def test_scan_media_library_records_strays_with_delete(tmp_path: Path) -> None:
    """With --delete the same items appear in strays_in_target AND get
    counted in items_removed and removed from disk."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    stray = dst / "Old (1990) {imdb-tt999}"
    stray.mkdir()
    _touch(stray / "Old.mkv", b"v")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, stats=stats, delete=True))

    assert stats.strays_in_target == ["Old (1990) {imdb-tt999}"]
    assert stats.items_removed == 1
    assert not stray.exists()


def test_scan_media_library_counts_files_inside_stray_dirs(tmp_path: Path) -> None:
    """A stray dir with N files contributes N to items_removed, not 1.
    Pre-0.2.2 a single `items_removed += 1` per entry produced "1 files
    removed" summaries for whole movie folders being torn down."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    stray = dst / "Old (1990) {imdb-tt999}"
    stray.mkdir()
    _touch(stray / "Old.mkv", b"v")
    _touch(stray / "Old.nfo", b"n")
    _touch(stray / "extras" / "bonus.mkv", b"b")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, stats=stats, delete=True))

    assert not stray.exists()
    assert stats.items_removed == 3  # three files, not "one entry"


def test_scan_media_library_dry_run_predicts_recursive_file_count(tmp_path: Path) -> None:
    """Dry-run summary must predict the same file count the real run
    would produce — otherwise users see "1 files would be removed" in
    dry-run and 50 in the actual run, undermining trust in the preview."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    stray = dst / "Old (1990) {imdb-tt999}"
    stray.mkdir()
    for n in range(5):
        _touch(stray / f"part-{n}.mkv", b"v")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, stats=stats, delete=True, dry_run=True))

    assert stray.exists()
    assert stats.items_removed == 5


def test_scan_media_library_records_library_stray_remove_events(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    (dst / "Stray (1990) {imdb-tt999}").mkdir()

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, delete=True, stats=stats))

    remove_events = [e for e in stats.events if e.action == "remove"]
    assert len(remove_events) == 1
    assert remove_events[0].context == "library_stray"
    assert remove_events[0].target.name == "Stray (1990) {imdb-tt999}"
    assert remove_events[0].source is None


def test_scan_media_library_collects_ignored_entries(tmp_path: Path) -> None:
    """Stray files at the library root and unparseable folder names land in
    LibraryStats.ignored so the sync summary can surface them — important
    for migration safety (user mustn't delete the source without seeing
    what was left behind)."""
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    (src / "First (1984) [imdbid-tt001]").mkdir()
    (src / "[imdbid-tt002]").mkdir()  # unparseable: no title after id strip
    (src / "stray.txt").write_bytes(b"")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    stats = LibraryStats()

    list(scan_media_library(source, target, stats=stats))

    ignored_names = {entry.path.name for entry in stats.ignored}
    assert ignored_names == {"[imdbid-tt002]", "stray.txt"}
    reasons = {entry.path.name: entry.reason for entry in stats.ignored}
    assert reasons["stray.txt"] == "not a directory"
    assert reasons["[imdbid-tt002]"] == "unparseable folder name"


def test_scan_media_library_rejects_same_base_dir(tmp_path: Path) -> None:
    src = tmp_path / "lib"
    src.mkdir()
    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(src)

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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
    assert movie is not None

    process_movie(source, target, movie_dir, movie)

    assert not (dst / "First (1984) {imdb-tt001}" / ".hidden").exists()


def test_process_movie_syncs_loose_top_level_files(tmp_path: Path) -> None:
    """Loose non-video files in the movie directory (subtitles, nfo, poster,
    notes) are synced 1:1 to the target — they keep their original name and
    land in the target movie folder.

    This was the behavior change in Paket 4 (0.2.0): pre-0.2.0 these files
    were silently dropped, which made jellyplex-sync unsafe for migrations.
    Dotfiles like .DS_Store stay excluded, matching the dotfolder skip.
    """
    src = tmp_path / "jellyfin"
    dst = tmp_path / "plex"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")
    _touch(movie_dir / "First (1984) [imdbid-tt001].nfo", b"n")
    _touch(movie_dir / "First (1984) [imdbid-tt001].en.srt", b"s")
    _touch(movie_dir / "poster.jpg", b"p")
    _touch(movie_dir / "random_note.txt", b"r")
    _touch(movie_dir / ".DS_Store", b"junk")
    _touch(movie_dir / "extras" / "trailer.mp4", b"t")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie)

    target_movie = dst / "First (1984) {imdb-tt001}"
    # Video and asset folder still work as before
    assert (target_movie / "First (1984) {imdb-tt001}.mkv").exists()
    assert (target_movie / "extras" / "trailer.mp4").exists()
    # Loose files are now synced with their original filename
    assert (target_movie / "First (1984) [imdbid-tt001].nfo").exists()
    assert (target_movie / "First (1984) [imdbid-tt001].en.srt").exists()
    assert (target_movie / "poster.jpg").exists()
    assert (target_movie / "random_note.txt").exists()
    # Dotfiles still excluded
    assert not (target_movie / ".DS_Store").exists()

    assert stats.loose_files_total == 4
    assert stats.loose_files_linked == 4


def test_process_movie_records_clash_when_two_videos_collide(tmp_path: Path) -> None:
    """Two source files that produce the same target name should be
    recorded as a MovieClash and the whole movie skipped (no link).
    Common in P→J: `[1080p].mkv` and `[1080p] [remux].mkv` both
    collapse to `- BD.mkv`."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "Movie (2020) {imdb-tt1}"
    movie_dir.mkdir()
    _touch(movie_dir / "Movie (2020) {imdb-tt1} [1080p].mkv", b"v1")
    _touch(movie_dir / "Movie (2020) {imdb-tt1} [1080p] [remux].mkv", b"v2")

    source = jp.PlexLibraryReader(src)
    target = jp.JellyfinLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie)

    assert stats.clash is not None
    assert stats.clash.movie_folder == "Movie (2020) {imdb-tt1}"
    assert stats.clash.target_filename == "Movie (2020) [imdbid-tt1] - BD.mkv"
    assert set(stats.clash.source_filenames) == {
        "Movie (2020) {imdb-tt1} [1080p].mkv",
        "Movie (2020) {imdb-tt1} [1080p] [remux].mkv",
    }
    # Nothing actually got linked
    assert stats.videos_linked == 0
    assert not (dst / "Movie (2020) [imdbid-tt1]").exists()


def test_process_movie_records_movie_stray_remove_events(tmp_path: Path) -> None:
    """Strays inside a movie folder produce remove events with
    context='movie_stray' — distinct from library-level strays."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")
    target_movie = dst / "First (1984) {imdb-tt001}"
    target_movie.mkdir()
    _touch(target_movie / "stale-inside-movie.txt", b"old")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie, delete=True)

    remove_events = [e for e in stats.events if e.action == "remove"]
    assert len(remove_events) == 1
    assert remove_events[0].context == "movie_stray"
    assert remove_events[0].target.name == "stale-inside-movie.txt"


def test_process_movie_records_link_events_for_videos(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) [imdbid-tt001]"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) [imdbid-tt001].mkv", b"v")

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
    assert movie is not None

    stats = process_movie(source, target, movie_dir, movie)

    link_events = [e for e in stats.events if e.action == "link"]
    assert len(link_events) == 1
    assert link_events[0].source is not None
    assert link_events[0].source.name == "First (1984) [imdbid-tt001].mkv"


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

    source = jp.JellyfinLibraryReader(src)
    target = jp.PlexLibraryWriter(dst)
    movie = source.parse_movie(movie_dir)
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
