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
