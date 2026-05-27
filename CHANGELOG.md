# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.3.4] - 2026-05-27

### Added
- **`jellyplex` CLI** — new primary entry point with explicit subcommands: `jellyplex sync`,
  `jellyplex diff`, `jellyplex plan`, `jellyplex import`

### Changed
- **`jellyplex-sync`** is now a standalone convenience command that does exactly what
  `jellyplex sync` does — same options, flat argument list, no subcommands. Existing scripts
  and invocations continue to work unchanged
- **Implicit `sync` subcommand removed** — the old behaviour of treating
  `jellyplex-sync <source> <target>` as `jellyplex-sync sync <source> <target>` is gone.
  `jellyplex-sync` no longer accepts subcommands; `jellyplex` always requires one
- **Standalone Linux binary** renamed from `jellyplex-sync-linux-x86_64` to
  `jellyplex-linux-x86_64` — it now provides the full CLI with all subcommands

## [0.3.3] - 2026-05-24

### Added
- **Standalone Linux binary** attached to each GitHub release — a single-file PyInstaller
  build (`jellyplex-sync-linux-x86_64`) for environments where installing a Python package is
  impractical (Unraid, Docker-less NAS setups). Download, `chmod +x`, run

### Removed
- **Forgejo workflow** — was not maintained and had drifted from the GitHub workflow

## [0.3.2] - 2026-05-24

### Added
- **`import` subcommand (experimental)** — imports video files from a staging area (a flat
  directory or directory tree where properly named videos have been dumped) into a structured
  movie library. Files are grouped by their parsed movie identity (title, year, provider ID)
  and placed into the correct one-folder-per-movie layout in the target. Default materializer
  is `--move` (copy + delete source); `--copy` keeps the source. Does not touch existing
  content in the target library — it only adds. Loose non-video files and asset directories
  in the staging area are not imported. `jp.import_media()` is the public API function
- **`MoveMaterializer`** — new materialization strategy: copy the file to the target, then
  delete the source on success. Re-run safe: if the target already exists and matches, the
  source is cleaned up without re-copying. Exported as `jp.MoveMaterializer`
- **`FlatDiscoverer`** — new `SourceDiscoverer` implementation that groups video files by
  filename parsing instead of folder structure. Works recursively on arbitrary directory trees.
  Importable from `jellyplex_sync.discover`

## [0.3.1] - 2026-05-24

### Changed
- **Developer docs split into DEV.md and SPECS.md** — `DEV.md` now covers the
  pipeline architecture (data flow diagram, module map, Plan IR, protocol overview);
  Plex/Jellyfin format specifications, translation rules, resolution label choices,
  extras subfolder conventions, and edge cases moved to the new `SPECS.md`

## [0.3.0] - 2026-05-24

### Breaking changes
- **Video-level clashes are now auto-resolved with a hash suffix** instead of skipping the
  whole movie. When two source files would collide on the same target filename — common in
  the lossy P→J translation (`[1080p].mkv` and `[1080p] [remux].mkv` both collapse to
  `- BD.mkv`) — the colliding files now get a short SHA-256 prefix of their source filename
  appended (e.g. `Movie - BD [a3f7c819].mkv`). Both files get synced; the user gets a
  warning rather than a hard failure. This makes the "every source file is reproducibly
  syncable" property unconditional. Detect hash-suffixed names in `--json` output via the
  per-file `disambiguation` field (`strategy="hash_suffix"`), or in the new `plan`
  subcommand. The `MovieClash` type is preserved but rarely populated — only by SHA-256
  prefix collisions, which are astronomically unlikely for typical folder sizes
- **`LibraryWriter.video_name` Protocol gained a `hash_suffix: str | None = None` kwarg.**
  Backward-compatible for existing callers (default `None` reproduces the pre-0.3 output);
  only relevant if you've implemented a custom `LibraryWriter` and want pyright/mypy to
  treat it as Protocol-conformant. Built-in PlexLibraryWriter and JellyfinLibraryWriter
  place the hash in a bracket label at the end / in the version-label position respectively

### Added
- **`plan` subcommand and `jp.plan()` function** — produce the immutable Plan a sync would
  execute, in human-readable text or `--json` form, without touching either filesystem.
  Use it as a pre-flight check before sync (will this clash? what gets translated?) or as
  the machine-readable answer for tooling. Unlike `sync` and `diff`, the target directory
  does not need to exist
- **Plan IR exported from the public API**: `Plan`, `PlannedMovie`, `PlannedFile`,
  `PlannedAsset`, `DisambiguationNote`, `FolderClash`. All `frozen=True` — safely shareable
  between phases, serialisable, comparable across runs. Use them to build tooling against a
  stable description of what a sync would do
- **Pipeline architecture** under the hood: source discovery, planning, and realization
  are now separate concerns living in `discover.py`, `planner.py`, `disambig.py`,
  `realize.py`, and `compare.py`. `sync()` and `diff()` are thin wrappers around the same
  pipeline that `plan()` uses, so the three commands stay in lock-step. The new modules
  are importable directly (`from jellyplex_sync.planner import Planner`, etc.) but aren't
  re-exported from the top-level package yet — pin to a specific module path if you build
  against them

### Changed
- **`sync()` is now wholly defined as Planner + Realizer**, with `Realizer` the only layer
  that observes `dry_run`. Behaviour is preserved for the common case; the one user-visible
  difference is the clash auto-resolution above

## [0.2.2] - 2026-05-24

### Fixed
- **Sync summary "N files removed" is now recursively accurate** — pre-0.2.2 the counter did
  `items_removed += 1` per entry, so tearing down a stray movie folder with 50 files inside
  reported "1 files removed". The number now reflects the actual file count, both in real
  runs and under `--dry-run`. Bonus from the underlying refactor: a single un-removable entry
  (e.g. EACCES on a busy file) is logged and counted as an error instead of aborting the
  whole sync — the rest of the tree is still cleaned up
- **`diff` shows "In sync. No differences found." even when translation losses exist** — the
  message was gated on `not result.drops`, so any library with `[remux]`/`[amazon]`/etc.
  labels never saw the confirmation even when source and target were structurally identical.
  Drops are informative (lossy translation), not sync problems; they continue to be reported
  separately

### Changed
- **`diff` "Movies only in source" now shows the source folder name and the expected target
  name** — previously only the expected target name was printed, which read as a curly-brace
  entry "missing" from a square-bracket target when scanning the diff against the actual
  source tree. Text output gains a second line per entry: `→ would be '<expected>'`. JSON
  schema for `movies_only_in_source` becomes a list of `{source_folder, expected_target}`
  objects instead of a list of strings — **breaking** for `--json` consumers reading that
  field (the schema is still pre-1.0 and documented as unstable in the README)

## [0.2.1] - 2026-05-23

### Fixed
- **Drop warnings are quiet by default** — `LoggingReporter` used to log every dropped
  label at WARNING, which produced one warning per affected file on real libraries
  (hundreds of `[remux]`, `[amazon]`, `[BluRay]` etc. each scrolling past). Drops now go to
  DEBUG by default and to INFO with `--verbose`. The text summary still shows aggregate
  counts; the JSON output still carries the deduplicated `translation_losses` list and the
  full per-file events
- **Off-standard resolution labels are preserved instead of dropped** — labels matching the
  resolution shape (`\d{3,4}[pi]`) but not in the known mapping (e.g. `[570i]` from a
  non-NTSC film transfer, or `[1440p]`) now pass through verbatim to the Jellyfin
  version-label position. Previously the label was silently dropped, producing
  `Movie - TV Fassung.mkv` from a source like `Movie [570i] [edition-TV Fassung].mkv`.
  Jellyfin's resolution sort still triggers on the trailing `p`/`i`, so sort order stays
  correct

### Added
- **Movie-level clashes are surfaced in summary and JSON** — when two source files in the
  same movie folder collapse to the same target name (common with the lossy P→J
  translation: `[1080p].mkv` and `[1080p] [remux].mkv` both become `- BD.mkv`), the whole
  movie has always been skipped silently apart from one ERROR log line. Easy to miss in a
  691-movie library. Now: counted as `N skipped due to clash` in the summary line, listed
  under top-level `clashes` in JSON (with movie folder + target filename + source file
  names so you can rename and re-run), and a closing WARNING points the user at the
  remediation. Behavior unchanged — the movie is still skipped wholesale. New `MovieClash`
  type in the public API; `LibraryStats.clashes`, `MovieStats.clash` fields

## [0.2.0] - 2026-05-23

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
- **Deduplicated translation losses** — `translation_losses` in `--json` output and
  `Translation losses` in `diff` text now show distinct `(kind, key, value, reason)` tuples
  only. A library with 50 files carrying a `[found]` label used to produce 50 identical
  entries — noise, because the list doesn't map back to specific files anyway. The
  per-file multiplicity stays available in `CollectingReporter.drops` for callers that want
  it. New `dedupe_drops()` helper exported from the library
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

### Changed
- **README rewritten** for the 0.2.0 surface — subcommand-first invocation, dedicated
  `diff` and `--json` sections with jq recipes, materializer flag explanations, and a
  banner at the top calling out the major-rewrite nature with dry-run / pin-to-0.1.x
  escape hatches
- **`DEV.md` gained an "Extras subdirectories" section** documenting the Plex vs Jellyfin
  extras conventions, with the `Other` vs `extras` footgun and the lowercase-`other`
  portable choice
- **Test suite grew from ~120 to 176 tests** covering the Reader/Writer split, all three
  materializer backends, the JSON output schema, ignored / strays / events accumulation,
  and translation-loss dedupe behavior

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
