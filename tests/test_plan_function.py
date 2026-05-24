"""Tests for the public plan() function — text and JSON output, exit codes."""

from __future__ import annotations

import io
import json
from pathlib import Path

import jellyplex_sync as jp


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_plan_returns_zero_for_empty_library(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    out = io.StringIO()
    rc = jp.plan(str(src), str(dst), source_format="plex", out=out)
    assert rc == 0


def test_plan_returns_zero_for_normal_library(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001}.mkv")
    out = io.StringIO()
    rc = jp.plan(str(src), str(dst), out=out)
    assert rc == 0


def test_plan_returns_two_when_source_missing(tmp_path: Path):
    out = io.StringIO()
    rc = jp.plan(
        str(tmp_path / "no-such"),
        str(tmp_path),
        source_format="plex",
        target_format="jellyfin",
        out=out,
    )
    assert rc == 2


def test_plan_succeeds_even_when_target_dir_missing(tmp_path: Path):
    """A `plan` call is the right tool to answer 'what would happen if I
    set this up?' — it should succeed even when the target hasn't been
    created yet."""
    src = tmp_path / "src"
    src.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "v.mkv")
    out = io.StringIO()
    rc = jp.plan(str(src), str(tmp_path / "absent"), source_format="plex", out=out)
    assert rc == 0


def test_plan_returns_two_when_format_undetectable(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    # Plain movie name: neither Plex nor Jellyfin markers → auto-detect fails.
    movie = src / "Plain Movie (2020)"
    movie.mkdir()
    _touch(movie / "Plain Movie (2020).mkv")
    out = io.StringIO()
    rc = jp.plan(str(src), str(dst), out=out)
    assert rc == 2


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------


def test_plan_text_header_includes_paths_and_formats(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    out = io.StringIO()
    jp.plan(
        str(src),
        str(dst),
        source_format="plex",
        target_format="jellyfin",
        out=out,
    )
    text = out.getvalue()
    assert "Plan for source" in text
    assert "Plex" in text
    assert "Jellyfin" in text
    assert str(src) in text
    assert str(dst) in text


def test_plan_text_empty_says_empty(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out)
    assert "Empty plan" in out.getvalue()


def test_plan_text_shows_video_translations(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p].mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out)
    text = out.getvalue()
    assert "Movies (1)" in text
    assert "Movie (2020) {imdb-tt001}" in text  # source folder
    assert "Movie (2020) [imdbid-tt001]" in text  # target folder
    assert "Movie (2020) [imdbid-tt001] - BD.mkv" in text  # target video


def test_plan_text_shows_loose_and_assets(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie.mkv")
    _touch(movie / "poster.jpg")
    _touch(movie / "extras" / "trailer.mp4")
    _touch(movie / "extras" / "interview.mp4")
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out)
    text = out.getvalue()
    assert "loose:" in text
    assert "poster.jpg" in text
    assert "assets:" in text
    assert "extras" in text
    assert "(2 files)" in text


def test_plan_text_shows_folder_clash(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    a = src / "Movie (2020) {imdb-tt001} [Director]"
    b = src / "Movie (2020) {imdb-tt001} [Theatrical]"
    a.mkdir()
    b.mkdir()
    _touch(a / "v.mkv")
    _touch(b / "v.mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out)
    text = out.getvalue()
    assert "Folder clashes (1)" in text
    assert "Movie (2020) [imdbid-tt001]" in text


def test_plan_text_shows_movie_clash(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p].mkv")
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out)
    text = out.getvalue()
    assert "Movie clashes (1)" in text


def test_plan_text_shows_translation_losses(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out)
    text = out.getvalue()
    assert "Translation losses" in text
    assert "remux" in text


def test_plan_text_shows_ignored(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _touch(src / "junk.txt")
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out)
    text = out.getvalue()
    assert "Ignored in source (1)" in text
    assert "junk.txt" in text


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_plan_json_emits_parseable_document(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p].mkv")
    out = io.StringIO()
    rc = jp.plan(str(src), str(dst), out=out, as_json=True)
    assert rc == 0
    doc = json.loads(out.getvalue())
    assert doc["operation"] == "plan"
    assert doc["source"]["format"] == "plex"
    assert doc["target"]["format"] == "jellyfin"


def test_plan_json_schema_for_simple_library(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p].mkv")
    _touch(movie / "poster.jpg")
    _touch(movie / "extras" / "trailer.mp4")
    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out, as_json=True)
    doc = json.loads(out.getvalue())

    assert doc["summary"] == {
        "movies": 1,
        "folder_clashes": 0,
        "movie_clashes": 0,
        "translation_losses": 0,
        "ignored": 0,
    }
    assert len(doc["movies"]) == 1
    m = doc["movies"][0]
    assert m["source_folder"] == "Movie (2020) {imdb-tt001}"
    assert m["target_folder"] == "Movie (2020) [imdbid-tt001]"
    assert len(m["videos"]) == 1
    v = m["videos"][0]
    assert v["target_name"] == "Movie (2020) [imdbid-tt001] - BD.mkv"
    assert "disambiguation" not in v  # no disambiguation needed
    assert len(m["loose_files"]) == 1
    assert m["loose_files"][0]["target_name"] == "poster.jpg"
    assert len(m["assets"]) == 1
    asset = m["assets"][0]
    assert asset["folder_name"] == "extras"
    assert len(asset["files"]) == 1


def test_plan_json_does_not_print_text(tmp_path: Path):
    """Under as_json, the document should be the only thing on stdout."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out, as_json=True)
    output = out.getvalue()
    assert "Plan for source" not in output
    assert "Empty plan" not in output
    json.loads(output)


def test_plan_json_includes_folder_clashes(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    a = src / "Movie (2020) {imdb-tt001} [Director]"
    b = src / "Movie (2020) {imdb-tt001} [Theatrical]"
    a.mkdir()
    b.mkdir()
    _touch(a / "v.mkv")
    _touch(b / "v.mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out, as_json=True)
    doc = json.loads(out.getvalue())
    assert doc["summary"]["folder_clashes"] == 1
    fc = doc["folder_clashes"][0]
    assert fc["target_folder_name"] == "Movie (2020) [imdbid-tt001]"
    assert set(fc["source_folder_names"]) == {a.name, b.name}


def test_plan_json_includes_translation_losses(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie (2020) {imdb-tt001} [1080p] [remux].mkv")
    out = io.StringIO()
    jp.plan(str(src), str(dst), out=out, as_json=True)
    doc = json.loads(out.getvalue())
    assert doc["summary"]["translation_losses"] >= 1
    values = [d["value"] for d in doc["translation_losses"]]
    assert "remux" in values


def test_plan_json_nested_assets(tmp_path: Path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie = src / "Movie (2020) {imdb-tt001}"
    movie.mkdir()
    _touch(movie / "Movie.mkv")
    _touch(movie / "extras" / "trailer.mp4")
    _touch(movie / "extras" / "deleted" / "scene.mp4")
    out = io.StringIO()
    jp.plan(str(src), str(dst), source_format="plex", out=out, as_json=True)
    doc = json.loads(out.getvalue())
    extras = doc["movies"][0]["assets"][0]
    assert extras["folder_name"] == "extras"
    assert len(extras["subfolders"]) == 1
    deleted = extras["subfolders"][0]
    assert deleted["folder_name"] == "deleted"
    assert deleted["files"][0]["target_name"] == "scene.mp4"
