import os
from pathlib import Path

import pytest

import jellyplex_sync as jp


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# HardlinkMaterializer
# ---------------------------------------------------------------------------


def test_hardlink_creates_link(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"

    mat = jp.HardlinkMaterializer()
    assert mat.materialize(src, dst) is True
    assert dst.exists()
    assert dst.samefile(src)


def test_hardlink_skips_when_already_linked(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    dst.hardlink_to(src)

    mat = jp.HardlinkMaterializer()
    assert mat.materialize(src, dst) is False


def test_hardlink_replaces_unrelated_file(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = _touch(tmp_path / "dst.mkv", b"different")

    mat = jp.HardlinkMaterializer()
    assert mat.materialize(src, dst) is True
    assert dst.samefile(src)


# ---------------------------------------------------------------------------
# CopyMaterializer
# ---------------------------------------------------------------------------


def test_copy_creates_independent_file(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"

    mat = jp.CopyMaterializer()
    assert mat.materialize(src, dst) is True
    assert dst.read_bytes() == b"abc"
    assert not dst.samefile(src), "copy must produce an independent inode"


def test_copy_preserves_mtime(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    dst = tmp_path / "dst.mkv"

    jp.CopyMaterializer().materialize(src, dst)
    assert dst.stat().st_mtime == src.stat().st_mtime


def test_copy_skips_when_size_and_mtime_match(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    mat = jp.CopyMaterializer()
    mat.materialize(src, dst)  # first run: copies

    assert mat.materialize(src, dst) is False, "second run with same src must be a no-op"


def test_copy_replaces_when_size_differs(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = _touch(tmp_path / "dst.mkv", b"abcdef")  # bigger
    os.utime(dst, (src.stat().st_atime, src.stat().st_mtime))  # same mtime

    mat = jp.CopyMaterializer()
    assert mat.materialize(src, dst) is True
    assert dst.read_bytes() == b"abc"


def test_copy_replaces_when_mtime_differs(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = _touch(tmp_path / "dst.mkv", b"abc")  # same size
    os.utime(dst, (1_500_000_000, 1_500_000_000))  # older mtime

    mat = jp.CopyMaterializer()
    assert mat.materialize(src, dst) is True


# ---------------------------------------------------------------------------
# ForceCopyMaterializer
# ---------------------------------------------------------------------------


def test_force_copy_copies_even_when_identical(tmp_path: Path):
    """ForceCopy must overwrite even when CopyMaterializer would skip
    (size+mtime match). Verified by content, not inode — ext4 and other
    filesystems aggressively reuse the inode after unlink+create, so the
    inode is filesystem-dependent and not a reliable signal."""
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    jp.CopyMaterializer().materialize(src, dst)

    # Poison dst: replace content but keep size+mtime matching src so the
    # CopyMaterializer skip heuristic still kicks in.
    src_stat = src.stat()
    dst.write_bytes(b"xyz")
    os.utime(dst, (src_stat.st_atime, src_stat.st_mtime))

    # Sanity check: CopyMaterializer would falsely skip here.
    assert jp.CopyMaterializer().materialize(src, dst) is False
    assert dst.read_bytes() == b"xyz"

    # ForceCopy ignores the skip heuristic and rewrites.
    assert jp.ForceCopyMaterializer().materialize(src, dst) is True
    assert dst.read_bytes() == b"abc"


def test_force_copy_creates_independent_file(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    assert jp.ForceCopyMaterializer().materialize(src, dst) is True
    assert not dst.samefile(src)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mat",
    [jp.HardlinkMaterializer(), jp.CopyMaterializer(), jp.ForceCopyMaterializer()],
    ids=lambda m: m.name,
)
def test_dry_run_touches_nothing(tmp_path: Path, mat):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    mat.materialize(src, dst, dry_run=True)
    assert not dst.exists()


# ---------------------------------------------------------------------------
# FileEvent recording (events sink)
# ---------------------------------------------------------------------------


def test_hardlink_records_link_event(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    events: list[jp.FileEvent] = []

    jp.HardlinkMaterializer().materialize(src, dst, events=events)

    assert len(events) == 1
    assert events[0].action == "link"
    assert events[0].source == src
    assert events[0].target == dst


def test_hardlink_records_replace_event(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = _touch(tmp_path / "dst.mkv", b"unrelated")
    events: list[jp.FileEvent] = []

    jp.HardlinkMaterializer().materialize(src, dst, events=events)

    assert events[0].action == "replace"


def test_hardlink_records_skip_event(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    dst.hardlink_to(src)
    events: list[jp.FileEvent] = []

    jp.HardlinkMaterializer().materialize(src, dst, events=events)

    assert events[0].action == "skip"


def test_copy_records_skip_event_on_match(tmp_path: Path):
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    mat = jp.CopyMaterializer()
    mat.materialize(src, dst)  # first copy

    events: list[jp.FileEvent] = []
    mat.materialize(src, dst, events=events)

    assert events[0].action == "skip"


def test_events_recorded_in_dry_run_too(tmp_path: Path):
    """Dry-run still records the intended action — that's the whole point
    of consuming events from --dry-run --json."""
    src = _touch(tmp_path / "src.mkv", b"abc")
    dst = tmp_path / "dst.mkv"
    events: list[jp.FileEvent] = []

    jp.HardlinkMaterializer().materialize(src, dst, dry_run=True, events=events)

    assert events[0].action == "link"
    assert not dst.exists()  # nothing actually happened
