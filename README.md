# Jellyfin-to-Plex Media Library Sync

This small helper script takes your curated Jellyfin media library and creates a Plex-compatible version without duplicating files. I prefer Plex for consumption, so this tool mirrors the existing collection in a format that Plex can easily index.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the Plex library path. The Jellyfin library is treated as the **only source of truth**, and any unmatched content in the Plex folder may be deleted without warning.

> **Note:** This tool is only useful if your Jellyfin library is well-maintained and each movie resides in its own folder.

## Overview

The script scans the source Jellyfin library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

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

- **Asset folders**: Subdirectories (e.g., `extras`, `subtitles`) are processed recursively with the same hard-link logic. `extras` will be renamed to `other`, because Plex does not recognize `extras`.

- **Stray items**: When `--delete` is used, any unexpected files or folders in the target library will be removed. Subfolders inside each movie folder (like bonus material) are always cleaned automatically.

## License

This project is licensed under the [BSD 2-Clause License](./LICENSE).

## Disclaimer

This is a private project written for personal use. It doesn't cover all use cases or environments. Use at your own risk. Contributions or forks are welcome if you want to adapt it to your own setup.
