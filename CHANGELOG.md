# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Breaking changes
- **`--convert-to`** removed in favour of **`--source-format`** and **`--target-format`**
  (both default to `auto`). The new flags are symmetric to the `source`/`target` positionals
  and make it explicit which side is being detected. Migration:
  - `--convert-to=auto` → drop the flag (both defaults are `auto`)
  - `--convert-to=jellyfin` → `--target-format=jellyfin`
  - `--convert-to=plex` → `--target-format=plex`

  The Python API mirrors this: `sync(..., convert_to=...)` and `diff(..., convert_to=...)`
  now take `source_format=` and `target_format=` instead
- **CLI restructured into subcommands** — operations now live under
  `jellyplex-sync sync ...` and `jellyplex-sync diff ...`. The old flat invocation
  (`jellyplex-sync <source> <target>`) still works and is treated as an implicit `sync`,
  so existing scripts keep running
- **Loose top-level files are now synced by default** — sidecar files (`.nfo`, posters,
  external subtitles, plain notes) at the top level of a movie folder used to be silently
  dropped; they're now materialized 1:1 to the target. Dot-files stay excluded. This makes
  the tool safe for a true migration where the source library is deleted afterwards
- **`MediaLibrary` ABC split** into `LibraryReader` and `LibraryWriter` Protocols, and the
  translation logic was lifted out into a dedicated layer. `MovieInfo`/`VideoInfo` lost the
  library-specific fields (`provider`, `movie_id`, `edition`, `resolution`) in favour of
  two open containers: an `attributes` dict (for `{key-value}` style) and a `labels` tuple
  (for `[bracket]` style). `parse_movie_path` was renamed to `parse_movie`. Affects any
  caller using the Python API directly; CLI users see no change

### Added
- **`diff` subcommand** — read-only comparison of source and target libraries. Reports
  movies only on one side, file-level differences on shared movies, and translation losses
  (labels/attributes the target format can't express). Exit codes follow Unix `diff`
  convention: 0 = in sync, 1 = differences, 2 = setup error
- **`--copy` / `--force-copy` materializers** — alternatives to the default `--hardlink`
  mode for environments where hardlinks aren't an option. `--copy` skips files whose target
  size and mtime already match the source; `--force-copy` always overwrites
- **`-v` short alias** for `--verbose`
- **`Reporter` machinery** in the public API (`LoggingReporter`, `StrictReporter`,
  `CollectingReporter`) — Writers report lossy translations through a Reporter, and callers
  decide how to surface them. `CollectingReporter` powers the `diff` translation-loss section
- **Lint / normalize mode** — setting `--source-format` and `--target-format` to the same value
  rewrites a library in its own format (e.g. to canonicalize Plex labels against the current
  layout rules). Works for both `sync` and `diff`
- **Ignored-entries reporting** — top-level items the scanner skips (stray files at the library
  root, folders whose names don't parse) are now listed in both the sync summary and the
  `diff` output. Before, these were silently warning-logged at most and could vanish unnoticed
  when a user deleted the source after migration. New `IgnoredEntry` type in the public API,
  populated on `LibraryStats.ignored` and `DiffResult.ignored`
- **`--json` flag** — machine-readable output for both `sync` and `diff`, written to stdout.
  Under `--json`, stderr is quiet (WARNING level), so the document pipes cleanly into `jq`
  without filtering; pass `--verbose` or `--debug` to re-enable INFO/DEBUG logs alongside
  the JSON. Schema is defined in `jellyplex_sync/json_output.py` and includes operation
  type, source/target endpoints with format, summary counters (including `items_ignored`),
  ignored entries, and translation losses. Schema isn't declared stable yet — pin a version
  when consuming. Public API: `diff(..., as_json=True)` writes the JSON document to `out`;
  `sync()` gained a `stats=` parameter so callers can read aggregate counters
  (`items_linked`, `movies_processed`, `ignored`) without re-walking per-movie `MovieStats`
- **Ignored count is part of the sync summary line** — the text summary now reports
  `N ignored` next to the existing counters, so a glance at the last line tells the full
  story. The per-item list still appears below for context
- **Stray items in target are now counted and surfaced** — items in the target library that
  are not in the source were only logged as `Stray item found` lines (easy to miss when there
  are dozens) and never appeared in the summary. They now contribute to a `strays kept in
  target` count in the text summary and the JSON `summary.strays_in_target`, with the full
  list under top-level `strays_in_target` in JSON. When strays exist and `--delete` was not
  passed, the run ends with a warning that points at `--delete`. New
  `LibraryStats.strays_in_target` field
- **Per-file `events` in `--json` output** — `sync --json` now emits a flat top-level `events`
  array with one entry per file action: `{action, target, source?, context?}`. Actions are
  `link`, `replace`, `skip`, `remove`; the run-level `dry_run` flag distinguishes "did" from
  "would" (so jq filters stay portable between modes). `context` on removes is
  `library_stray` / `movie_stray` / `asset_stray` — tells you which scope a deletion came
  from. Enables external verification scripts (e.g. "show me all replaces with full paths")
  without parsing the text log. New `FileEvent` type in the public API;
  `LibraryStats.events`, `MovieStats.events`, `AssetStats.events` accumulate them.
  `FileMaterializer.materialize()` gained an `events: list[FileEvent] | None = None`
  parameter — backward compatible

## [0.1.6] - 2026-05-21

### Breaking changes
- **`determine_library_type`** renamed to **`guess_library_type`** to reflect that the detector is
  heuristic and can return `None`. Update any direct imports from `jellyplex_sync.sync`
- **License** relicensed from BSD-2-Clause to BSD-3-Clause, adding a non-endorsement clause

### Added
- Test coverage for the sync orchestration: `scan_media_library`, `process_movie`,
  `process_assets_folder` and `guess_library_type` are now exercised with real temp filesystems

### Changed
- **`parse_video_path`** return type tightened from `VideoInfo | None` to `VideoInfo`. Both
  implementations never returned `None` — consumers can drop unnecessary None checks
- **Sync summary** consolidates the duplicate `LibraryStats` and local counters; now reports
  `X of Y movies synced`, making movies skipped due to naming conflicts visible
- **README** restructured with a dedicated Installation section (`uv tool install jellyplex-sync`),
  a single Docker example, and a detailed warning about hardlinks on Unraid's classic array
  (shfs and the mover can break them)

### Fixed
- **Logging** — final summary now uses the module logger like the rest of the module; the
  conflict error message uses `%`-format so it isn't built when the log level is off

### Removed
- **`utils.common_path`** — unused helper, removed along with its tests

## [0.1.5] - 2026-05-21

### Added
- `__all__` in `jellyplex_sync` so re-exported names are explicit for IDEs and type checkers

### Changed
- Minimum supported Python version lowered from 3.12 to 3.11
- Release notes on GitHub/Forgejo are now generated from the commit log since the previous tag

## [0.1.4] - 2026-02-21

First tagged release. Earlier versions exist in the git history but were not published as releases.
