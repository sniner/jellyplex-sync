"""Machine-readable JSON output for `sync` and `diff`.

The schema is defined here so it's reviewable in one place. Each
`_<thing>_payload` builder returns a plain `dict` ready for
`json.dumps` — using dicts (not TypedDicts) keeps the shape literal
and visible at call sites. The schema is not stable yet; that's a
post-0.2.0 concern once external consumers actually exist.

Pretty-printed with a trailing newline so output pipes cleanly into
`jq` and other line-oriented tools.
"""

from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING, Any, TextIO

from .library import Drop, FileEvent, FolderClash, IgnoredEntry, MovieClash, dedupe_drops
from .plan import Plan, PlannedAsset, PlannedFile, PlannedMovie

if TYPE_CHECKING:
    from .sync import DiffResult, LibraryStats


def _endpoint_payload(path: pathlib.Path, fmt: str) -> dict[str, Any]:
    return {"path": str(path), "format": fmt}


def _ignored_payload(entries: list[IgnoredEntry] | tuple[IgnoredEntry, ...]) -> list[dict[str, Any]]:
    return [{"path": str(e.path), "name": e.path.name, "reason": e.reason} for e in entries]


def _drops_payload(drops: tuple[Drop, ...] | list[Drop]) -> list[dict[str, Any]]:
    """Distinct drops only — same (kind, key, value, reason) collapses to
    one entry. The point is "what got lost", not the per-file frequency
    (which the user can't map back to specific files from the list anyway)."""
    return [
        {"kind": d.kind, "key": d.key, "value": d.value, "reason": d.reason}
        for d in dedupe_drops(list(drops))
    ]


def _clashes_payload(clashes: list[MovieClash]) -> list[dict[str, Any]]:
    return [
        {
            "movie_folder": c.movie_folder,
            "target_filename": c.target_filename,
            "source_filenames": list(c.source_filenames),
        }
        for c in clashes
    ]


def _events_payload(events: list[FileEvent]) -> list[dict[str, Any]]:
    """Flatten FileEvents into JSON dicts. `source` and `context` are
    omitted when None — keeps the document compact and unambiguous."""
    payload: list[dict[str, Any]] = []
    for ev in events:
        item: dict[str, Any] = {"action": ev.action, "target": str(ev.target)}
        if ev.source is not None:
            item["source"] = str(ev.source)
        if ev.context is not None:
            item["context"] = ev.context
        payload.append(item)
    return payload


def write_sync_json(
    out: TextIO,
    *,
    source_path: pathlib.Path,
    source_format: str,
    target_path: pathlib.Path,
    target_format: str,
    dry_run: bool,
    exit_code: int,
    stats: LibraryStats,
    drops: tuple[Drop, ...] | list[Drop],
) -> None:
    payload = {
        "operation": "sync",
        "exit_code": exit_code,
        "source": _endpoint_payload(source_path, source_format),
        "target": _endpoint_payload(target_path, target_format),
        "dry_run": dry_run,
        "summary": {
            "movies_total": stats.movies_total,
            "movies_processed": stats.movies_processed,
            "files_updated": stats.items_linked,
            "files_removed": stats.items_removed + stats.movie_items_removed,
            "items_ignored": len(stats.ignored),
            "strays_in_target": len(stats.strays_in_target),
            "clashes": len(stats.clashes),
        },
        "ignored": _ignored_payload(stats.ignored),
        "strays_in_target": list(stats.strays_in_target),
        "translation_losses": _drops_payload(drops),
        "clashes": _clashes_payload(stats.clashes),
        "events": _events_payload(stats.events),
    }
    json.dump(payload, out, indent=2)
    out.write("\n")


def _planned_file_payload(f: PlannedFile) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": str(f.source),
        "target_name": f.target_name,
    }
    if f.disambiguation is not None:
        payload["disambiguation"] = {
            "strategy": f.disambiguation.strategy,
            "detail": f.disambiguation.detail,
        }
    return payload


def _planned_asset_payload(a: PlannedAsset) -> dict[str, Any]:
    return {
        "source": str(a.source),
        "folder_name": a.folder_name,
        "files": [_planned_file_payload(f) for f in a.files],
        "subfolders": [_planned_asset_payload(sf) for sf in a.subfolders],
    }


def _planned_movie_payload(m: PlannedMovie) -> dict[str, Any]:
    return {
        "source_folder": m.source_path.name,
        "source_path": str(m.source_path),
        "target_folder": m.target_folder.name,
        "target_path": str(m.target_folder),
        "videos": [_planned_file_payload(f) for f in m.videos],
        "loose_files": [_planned_file_payload(f) for f in m.loose_files],
        "assets": [_planned_asset_payload(a) for a in m.assets],
    }


def _folder_clashes_payload(clashes: tuple[FolderClash, ...]) -> list[dict[str, Any]]:
    return [
        {
            "target_folder_name": fc.target_folder_name,
            "source_folder_names": list(fc.source_folder_names),
        }
        for fc in clashes
    ]


def write_plan_json(
    out: TextIO,
    plan: Plan,
    *,
    drops: tuple[Drop, ...] | list[Drop] = (),
) -> None:
    """Serialise a Plan to JSON. `drops` come from the reporter the
    Planner was fed — they aren't on the Plan itself because they
    belong to translation, not to the plan structure."""
    distinct_drops = dedupe_drops(list(drops))
    payload = {
        "operation": "plan",
        "source": _endpoint_payload(plan.source_root, plan.source_format),
        "target": _endpoint_payload(plan.target_root, plan.target_format),
        "summary": {
            "movies": len(plan.movies),
            "folder_clashes": len(plan.folder_clashes),
            "movie_clashes": len(plan.clashes),
            "translation_losses": len(distinct_drops),
            "ignored": len(plan.ignored),
        },
        "movies": [_planned_movie_payload(m) for m in plan.movies],
        "folder_clashes": _folder_clashes_payload(plan.folder_clashes),
        "movie_clashes": _clashes_payload(list(plan.clashes)),
        "translation_losses": _drops_payload(drops),
        "ignored": _ignored_payload(list(plan.ignored)),
    }
    json.dump(payload, out, indent=2)
    out.write("\n")


def write_diff_json(
    out: TextIO,
    result: DiffResult,
    source_format: str,
    target_format: str,
    source_path: pathlib.Path,
    target_path: pathlib.Path,
) -> None:
    payload = {
        "operation": "diff",
        "exit_code": 1 if result.has_differences else 0,
        "source": _endpoint_payload(source_path, source_format),
        "target": _endpoint_payload(target_path, target_format),
        "in_sync": not result.has_differences,
        "movies_only_in_source": [
            {"source_folder": m.source_folder, "expected_target": m.expected_target}
            for m in result.movies_only_in_source
        ],
        "movies_only_in_target": list(result.movies_only_in_target),
        "differing_movies": [
            {
                "target_movie_name": d.target_movie_name,
                "only_in_source": list(d.only_in_source),
                "only_in_target": list(d.only_in_target),
            }
            for d in result.differing_movies
        ],
        "translation_losses": _drops_payload(result.drops),
        "ignored": _ignored_payload(result.ignored),
    }
    json.dump(payload, out, indent=2)
    out.write("\n")
