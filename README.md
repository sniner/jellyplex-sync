# Jellyfin-to-Plex Media Library Sync

This small helper script takes your curated Jellyfin media library and creates a Plex-compatible version without duplicating files. I prefer Plex for consumption, so this tool mirrors the existing collection in a format that Plex can easily index.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the Plex library path. The Jellyfin library is treated as the **only source of truth**, and any unmatched content in the Plex folder may be deleted without warning.

> **Note:** This tool is only useful if your Jellyfin library is well-maintained and each movie resides in its own folder.

## Overview

The script scans the source Jellyfin library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

> ⚠️ **Important:** This script is designed exclusively for **movie libraries**. It does **not** support TV shows or miniseries. However, this is usually not a limitation in practice: for shows, Jellyfin and Plex use very similar directory structures, so you can typically point both apps to the same library without issues.

## Usage

### Basic Command

```bash
python3 j2p.py [OPTIONS] /path/to/jellyfin/library /path/to/plex/library
```

### Options

- `--create`
  Create the target directory if it does not exist.

- `--delete`
  Remove movie folders and stray files in the target that are not present in the source.

- `--verbose`
  Show informational messages about each operation.

- `--debug`
  Enable debug-level logging for detailed parsing and linking steps.

## Examples

Mirror a Jellyfin library into an empty Plex structure:

```bash
python3 j2p.py --create ~/Media/Jellyfin ~/Media/Plex
```

Mirror and remove anything in the Plex folder that no longer exists in Jellyfin:

```bash
python3 j2p.py --delete ~/Media/Jellyfin ~/Media/Plex
```

Verbose output with full debug information:

```bash
python3 j2p.py --verbose --debug --delete --create ~/Media/Jellyfin ~/Media/Plex
```

## Behavior

- **Hard links**: Video files are linked, not copied. This preserves disk space and ensures both libraries reflect the same physical files.

- **Asset folders**: Subdirectories (e.g., `other`, `interviews`) are processed recursively with the same hard-link logic. NB: rename `extras` folder to `other` in your Jellyfin library, because Plex does not recognize `extras`.

- **Stray items**: When `--delete` is used, any unexpected files or folders in the target library will be removed.

## Jellyfin movie library outline

This is the expected folder structure in your Jellyfin movie library. The script relies on it being consistent:

```
Movies
├── A Bridge Too Far (1977) [imdbid-tt0075784]
│   ├── A Bridge Too Far (1977) [imdbid-tt0075784].mkv
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) [imdbid-tt0082096]
    ├── Das Boot (1981) [imdbid-tt0082096] - Director's Cut.mkv
    ├── Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.mkv
    └── others
        ├── Production Photos.mkv
        └── Making of.mkv
```

Each movie must reside in its own folder, with optional subfolders for extras. Different editions (e.g., Director's Cut, Theatrical Cut) must be named accordingly.

## License

This project is licensed under the [BSD 2-Clause License](./LICENSE).

## Disclaimer

This is a private project written for personal use. It doesn't cover all use cases or environments. Use at your own risk. Contributions or forks are welcome if you want to adapt it to your own setup.
