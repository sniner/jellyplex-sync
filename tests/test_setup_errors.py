"""Setup-error behaviour of the public entry points.

A missing or wrong source path must be reported as such — not as an
undetectable library format, which is what the format sniffer concludes
when it walks a path that isn't there. The exit codes are pinned to
their pre-existing values: 1 for sync/import, 2 for diff/plan.

Also covered here: the cross-filesystem hardlink failure (EXDEV) —
the most common real-world misconfiguration — must name the way out
(--copy) instead of surfacing a raw errno.
"""

from __future__ import annotations

import errno
import logging
import pathlib
from pathlib import Path

import pytest

import jellyplex_sync as jp
from jellyplex_sync.library import FileEvent


@pytest.fixture
def dst(tmp_path: Path) -> Path:
    target = tmp_path / "dst"
    target.mkdir()
    return target


def test_sync_missing_source_reports_path_not_format(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        result = jp.sync(str(tmp_path / "nope"), str(dst))
    assert result.exit_code == 1
    assert "does not exist" in caplog.text
    assert "determine source library type" not in caplog.text


def test_sync_source_is_a_file(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bogus = tmp_path / "movie.mkv"
    bogus.write_bytes(b"x")
    with caplog.at_level(logging.ERROR):
        result = jp.sync(str(bogus), str(dst))
    assert result.exit_code == 1
    assert "not a directory" in caplog.text


def test_diff_missing_source_reports_path_not_format(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        rc = jp.diff(str(tmp_path / "nope"), str(dst))
    assert rc == 2
    assert "does not exist" in caplog.text
    assert "determine source library type" not in caplog.text


def test_plan_missing_source_reports_path_not_format(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        rc = jp.plan(str(tmp_path / "nope"), str(dst))
    assert rc == 2
    assert "does not exist" in caplog.text
    assert "determine source library type" not in caplog.text


def test_import_missing_source_reports_path_not_format(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        result = jp.import_media(str(tmp_path / "nope"), str(dst))
    assert result.exit_code == 1
    assert "does not exist" in caplog.text
    assert "determine source library type" not in caplog.text


class _FailingMaterializer:
    """Materializer that fails with a given errno on the first file —
    simulates hardlinking across a filesystem boundary (EXDEV) without
    needing two real filesystems in the test environment."""

    name = "hardlink"

    def __init__(self, err: int) -> None:
        self._err = err

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool:
        raise OSError(self._err, "simulated failure", str(dst))


def _one_movie_source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir(parents=True)
    (movie / "Movie (2020) {imdb-tt001}.mkv").write_bytes(b"v")
    return src


def test_sync_cross_device_link_points_at_copy(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    src = _one_movie_source(tmp_path)
    with caplog.at_level(logging.ERROR):
        result = jp.sync(
            str(src), str(dst), materializer=_FailingMaterializer(errno.EXDEV)
        )
    assert result.exit_code == 1
    assert "different filesystems" in caplog.text
    assert "--copy" in caplog.text


def test_sync_other_oserror_propagates(tmp_path: Path, dst: Path) -> None:
    """Only EXDEV gets the friendly treatment — anything else is a real
    bug or environment problem and must not be swallowed."""
    src = _one_movie_source(tmp_path)
    with pytest.raises(OSError):
        jp.sync(str(src), str(dst), materializer=_FailingMaterializer(errno.EACCES))


def test_sync_undetectable_format_still_reported(
    tmp_path: Path, dst: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An existing but empty source still yields the format hint —
    the new existence check must not swallow that case."""
    src = tmp_path / "src"
    src.mkdir()
    with caplog.at_level(logging.ERROR):
        result = jp.sync(str(src), str(dst))
    assert result.exit_code == 1
    assert "determine source library type" in caplog.text
