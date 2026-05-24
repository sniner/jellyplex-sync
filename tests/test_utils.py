import os
import stat
from pathlib import Path

import pytest

from jellyplex_sync.utils import RemovalCounts, remove


def _touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_remove_file_returns_files_one(tmp_path: Path) -> None:
    target = _touch(tmp_path / "a.txt", b"x")
    counts = remove(target)
    assert counts == RemovalCounts(files=1)
    assert not target.exists()


def test_remove_symlink_unlinks_link_not_target(tmp_path: Path) -> None:
    real = _touch(tmp_path / "real.txt", b"x")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    counts = remove(link)
    assert counts == RemovalCounts(files=1)
    assert not link.exists()
    assert real.exists()  # target untouched


def test_remove_empty_dir_returns_dirs_one(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    counts = remove(target)
    assert counts == RemovalCounts(dirs=1)
    assert not target.exists()


def test_remove_directory_counts_files_and_dirs_recursively(tmp_path: Path) -> None:
    root = tmp_path / "movie"
    _touch(root / "movie.mkv", b"v")
    _touch(root / "movie.nfo", b"n")
    _touch(root / "extras" / "bonus.mkv", b"b")
    _touch(root / "extras" / "deeper" / "scene.mkv", b"s")

    counts = remove(root)

    # 4 files (movie.mkv, movie.nfo, bonus.mkv, scene.mkv)
    # 3 dirs (deeper, extras, movie)
    assert counts == RemovalCounts(files=4, dirs=3)
    assert not root.exists()


def test_remove_dir_with_symlink_to_dir_unlinks_symlink(tmp_path: Path) -> None:
    """os.walk lists dir-symlinks under `dirs`; rmdir would fail on
    them. The function must detect and unlink instead."""
    root = tmp_path / "movie"
    extras = tmp_path / "extras"
    extras.mkdir()
    _touch(extras / "bonus.mkv", b"b")
    root.mkdir()
    _touch(root / "movie.mkv", b"v")
    (root / "extras").symlink_to(extras, target_is_directory=True)

    counts = remove(root)

    # 1 file (movie.mkv) + 1 file-counted symlink + 1 dir (root). Symlink
    # target's contents are NOT followed.
    assert counts == RemovalCounts(files=2, dirs=1)
    assert not root.exists()
    assert extras.exists()
    assert (extras / "bonus.mkv").exists()


def test_remove_missing_path_is_ignored(tmp_path: Path) -> None:
    counts = remove(tmp_path / "nope")
    assert counts == RemovalCounts(ignored=1)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_remove_continues_past_permission_errors(tmp_path: Path) -> None:
    """A single un-removable entry must not strand the rest of the walk.
    The error is logged and counted; siblings are still removed."""
    root = tmp_path / "movie"
    root.mkdir()
    _touch(root / "removable.mkv", b"v")
    locked_dir = root / "locked"
    locked_dir.mkdir()
    _touch(locked_dir / "stuck.mkv", b"x")
    # Strip write+exec from the parent so its child can't be unlinked
    # (the unlink() syscall checks the directory's perms, not the file's).
    os.chmod(locked_dir, stat.S_IRUSR)

    try:
        counts = remove(root)
    finally:
        # Restore so pytest can clean tmp_path.
        os.chmod(locked_dir, stat.S_IRWXU)

    # The sibling file was removed; stuck.mkv and the locked dir failed.
    assert counts.files == 1
    assert counts.errors >= 1
    assert (locked_dir / "stuck.mkv").exists()


def test_remove_dry_run_matches_real_run_on_directory(tmp_path: Path) -> None:
    """Dry-run accuracy: the same call with dry_run=True predicts what
    the real run produces, with no side effects."""
    def build(parent: Path) -> Path:
        root = parent / "movie"
        _touch(root / "movie.mkv", b"v")
        _touch(root / "movie.nfo", b"n")
        _touch(root / "extras" / "bonus.mkv", b"b")
        return root

    a = build(tmp_path / "a")
    b = build(tmp_path / "b")

    predicted = remove(a, dry_run=True)
    actual = remove(b)

    assert predicted == actual
    assert a.exists()  # dry-run has no side effects
    assert not b.exists()
