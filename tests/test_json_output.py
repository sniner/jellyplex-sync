"""Schema-level tests for `--json` output.

These tests pin the JSON keys and shape so accidental breakage
(renamed field, dropped key, wrong nesting) is caught immediately.
The schema itself is documented in `json_output.py`; tests assert
that the documented shape matches what code produces.
"""

import io
import json
from pathlib import Path

import jellyplex_sync as jp
from jellyplex_sync.json_output import write_diff_json, write_sync_json
from jellyplex_sync.library import CollectingReporter, Drop, FileEvent, IgnoredEntry
from jellyplex_sync.sync import DiffEntry, DiffResult, LibraryStats


def _touch(path: Path, content: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# write_sync_json
# ---------------------------------------------------------------------------


def test_sync_json_has_full_schema(tmp_path: Path) -> None:
    stats = LibraryStats(
        movies_total=5,
        movies_processed=4,
        items_linked=10,
        items_removed=2,
        movie_items_removed=1,
        ignored=[IgnoredEntry(tmp_path / "stray.txt", "not a directory")],
    )
    drops = [Drop(kind="label", key=None, value="remux", reason="no Jellyfin equivalent")]

    buf = io.StringIO()
    write_sync_json(
        buf,
        source_path=tmp_path / "src",
        source_format="plex",
        target_path=tmp_path / "dst",
        target_format="jellyfin",
        dry_run=False,
        exit_code=0,
        stats=stats,
        drops=drops,
    )

    payload = json.loads(buf.getvalue())

    assert payload["operation"] == "sync"
    assert payload["exit_code"] == 0
    assert payload["dry_run"] is False
    assert payload["source"] == {"path": str(tmp_path / "src"), "format": "plex"}
    assert payload["target"] == {"path": str(tmp_path / "dst"), "format": "jellyfin"}
    assert payload["summary"] == {
        "movies_total": 5,
        "movies_processed": 4,
        "files_updated": 10,
        "files_removed": 3,  # items_removed + movie_items_removed
        "items_ignored": 1,
        "strays_in_target": 0,
        "clashes": 0,
    }
    assert payload["ignored"] == [
        {"path": str(tmp_path / "stray.txt"), "name": "stray.txt", "reason": "not a directory"}
    ]
    assert payload["translation_losses"] == [
        {"kind": "label", "key": None, "value": "remux", "reason": "no Jellyfin equivalent"}
    ]


def test_sync_json_with_empty_stats() -> None:
    """Default LibraryStats serializes cleanly with empty lists, not nulls."""
    buf = io.StringIO()
    write_sync_json(
        buf,
        source_path=Path("/src"),
        source_format="plex",
        target_path=Path("/dst"),
        target_format="jellyfin",
        dry_run=True,
        exit_code=0,
        stats=LibraryStats(),
        drops=[],
    )
    payload = json.loads(buf.getvalue())
    assert payload["ignored"] == []
    assert payload["translation_losses"] == []
    assert payload["events"] == []
    assert payload["dry_run"] is True


def test_sync_json_dedupes_translation_losses() -> None:
    """Same (kind, key, value, reason) tuple collapses to one entry —
    distinct losses are what's actionable, per-file frequency isn't."""
    same = Drop(kind="label", key=None, value="found", reason="no Jellyfin equivalent")
    different = Drop(kind="label", key=None, value="rented", reason="no Jellyfin equivalent")

    buf = io.StringIO()
    write_sync_json(
        buf,
        source_path=Path("/src"),
        source_format="plex",
        target_path=Path("/dst"),
        target_format="jellyfin",
        dry_run=False,
        exit_code=0,
        stats=LibraryStats(),
        drops=[same, same, different, same],
    )
    payload = json.loads(buf.getvalue())
    assert payload["translation_losses"] == [
        {"kind": "label", "key": None, "value": "found", "reason": "no Jellyfin equivalent"},
        {"kind": "label", "key": None, "value": "rented", "reason": "no Jellyfin equivalent"},
    ]


def test_sync_json_events_payload(tmp_path: Path) -> None:
    """Events serialize with action + target always; source and context
    only when present."""
    stats = LibraryStats(
        events=[
            FileEvent(action="link", target=tmp_path / "dst.mkv", source=tmp_path / "src.mkv"),
            FileEvent(action="skip", target=tmp_path / "dst2.mkv", source=tmp_path / "src2.mkv"),
            FileEvent(action="remove", target=tmp_path / "stray.mkv", context="library_stray"),
            FileEvent(action="remove", target=tmp_path / "ext.mkv", context="movie_stray"),
        ]
    )

    buf = io.StringIO()
    write_sync_json(
        buf,
        source_path=tmp_path / "src",
        source_format="plex",
        target_path=tmp_path / "dst",
        target_format="jellyfin",
        dry_run=False,
        exit_code=0,
        stats=stats,
        drops=[],
    )
    payload = json.loads(buf.getvalue())
    events = payload["events"]
    assert len(events) == 4

    # link: source present, no context
    assert events[0] == {
        "action": "link",
        "target": str(tmp_path / "dst.mkv"),
        "source": str(tmp_path / "src.mkv"),
    }
    # remove: no source, context present
    assert events[2] == {
        "action": "remove",
        "target": str(tmp_path / "stray.mkv"),
        "context": "library_stray",
    }
    # remove can carry different contexts
    assert events[3]["context"] == "movie_stray"


def test_sync_json_writes_trailing_newline() -> None:
    """jq-friendly: every JSON document ends with a newline."""
    buf = io.StringIO()
    write_sync_json(
        buf,
        source_path=Path("/src"),
        source_format="plex",
        target_path=Path("/dst"),
        target_format="jellyfin",
        dry_run=False,
        exit_code=0,
        stats=LibraryStats(),
        drops=[],
    )
    assert buf.getvalue().endswith("\n")


# ---------------------------------------------------------------------------
# write_diff_json
# ---------------------------------------------------------------------------


def test_diff_json_in_sync() -> None:
    buf = io.StringIO()
    write_diff_json(
        buf,
        DiffResult(),
        source_format="plex",
        target_format="jellyfin",
        source_path=Path("/src"),
        target_path=Path("/dst"),
    )
    payload = json.loads(buf.getvalue())
    assert payload["operation"] == "diff"
    assert payload["exit_code"] == 0
    assert payload["in_sync"] is True
    assert payload["movies_only_in_source"] == []
    assert payload["differing_movies"] == []


def test_diff_json_with_differences(tmp_path: Path) -> None:
    result = DiffResult(
        movies_only_in_source=("Foo (1990)",),
        movies_only_in_target=("Bar (1991)",),
        differing_movies=(
            DiffEntry(
                target_movie_name="Baz (1992)",
                only_in_source=("subtitle.srt",),
                only_in_target=("old.nfo",),
            ),
        ),
        drops=(Drop(kind="label", key=None, value="remux", reason="no Jellyfin equivalent"),),
        ignored=(IgnoredEntry(tmp_path / "stray.txt", "not a directory"),),
    )

    buf = io.StringIO()
    write_diff_json(
        buf,
        result,
        source_format="plex",
        target_format="jellyfin",
        source_path=tmp_path,
        target_path=tmp_path,
    )
    payload = json.loads(buf.getvalue())

    assert payload["exit_code"] == 1
    assert payload["in_sync"] is False
    assert payload["movies_only_in_source"] == ["Foo (1990)"]
    assert payload["movies_only_in_target"] == ["Bar (1991)"]
    assert payload["differing_movies"] == [
        {
            "target_movie_name": "Baz (1992)",
            "only_in_source": ["subtitle.srt"],
            "only_in_target": ["old.nfo"],
        }
    ]
    assert payload["translation_losses"][0]["value"] == "remux"
    assert payload["ignored"][0]["name"] == "stray.txt"


# ---------------------------------------------------------------------------
# end-to-end via diff(as_json=True)
# ---------------------------------------------------------------------------


def test_diff_as_json_emits_valid_json(tmp_path: Path) -> None:
    """The public diff() API with as_json=True produces parseable JSON."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001}.mkv", b"v")

    buf = io.StringIO()
    rc = jp.diff(str(src), str(dst), out=buf, as_json=True)

    assert rc == 1
    payload = json.loads(buf.getvalue())
    assert payload["operation"] == "diff"
    assert "First (1984) [imdbid-tt001]" in payload["movies_only_in_source"]


def test_diff_as_json_does_not_print_text(tmp_path: Path) -> None:
    """JSON mode is exclusive: no human-readable headers leak into output."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001}.mkv", b"v")
    target_movie = dst / "First (1984) [imdbid-tt001]"
    target_movie.mkdir()
    _touch(target_movie / "First (1984) [imdbid-tt001].mkv", b"v")

    buf = io.StringIO()
    jp.diff(str(src), str(dst), out=buf, as_json=True)
    output = buf.getvalue()

    assert "Comparing source" not in output
    assert "In sync" not in output
    # Single JSON document — parseable in one shot.
    json.loads(output)


# ---------------------------------------------------------------------------
# sync() with caller-supplied stats / reporter
# ---------------------------------------------------------------------------


def test_sync_populates_caller_supplied_stats(tmp_path: Path) -> None:
    """A caller passing stats= can read aggregates back without
    re-walking MovieStats — this is what enables the --json CLI path."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    movie_dir = src / "First (1984) {imdb-tt001}"
    movie_dir.mkdir()
    _touch(movie_dir / "First (1984) {imdb-tt001}.mkv", b"v")
    _touch(src / "stray.txt", b"")

    stats = LibraryStats()
    reporter = CollectingReporter()
    rc = jp.sync(str(src), str(dst), stats=stats, reporter=reporter)

    assert rc == 0
    assert stats.movies_total == 1
    assert stats.movies_processed == 1
    assert stats.items_linked == 1
    assert len(stats.ignored) == 1
    assert stats.ignored[0].path.name == "stray.txt"
