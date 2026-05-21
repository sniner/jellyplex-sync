# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
