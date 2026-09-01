"""Setup-error behaviour of the public entry points.

A missing or wrong source path must be reported as such — not as an
undetectable library format, which is what the format sniffer concludes
when it walks a path that isn't there. The exit codes are pinned to
their pre-existing values: 1 for sync/import, 2 for diff/plan.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import jellyplex_sync as jp


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
