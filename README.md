# Jellyfin-to-Plex Media Library Sync

This small helper script takes your curated media library in Jellyfin or Plex format and creates a compatible mirror for the other system, without duplicating any files. I personally prefer Plex for playback, so the tool initially focused on converting from Jellyfin to Plex, but it now supports both directions.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the target library path. The source library is treated as the **only source of truth**, and any unmatched content in the target folder may be deleted without warning.

> **Note:** This tool is only useful if your media library is well-maintained and each movie resides in its own folder.

## Overview

The script scans the source library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

> ⚠️ **Important:** This script is designed exclusively for **movie libraries**. It does **not** support TV shows or miniseries. However, this is usually not a limitation in practice: for shows, Jellyfin and Plex use very similar directory structures, so you can typically point both apps to the same library without issues.

> ⚠️ **Unraid:** This script is not compatible with Unraid User Scripts. If you do not want to use the container image, there is an older release in branch `unraid_user_scripts`. Switch to this branch and use the single-file script - but please don't forget to install the Python Plugin in Unraid first.

## Docker Image

If you build the docker image locally:

```bash
cd .../jellyplex-sync
docker build -t jellyplex .
```

To run the docker container with the demo library in the project folder:

```bash
docker run --rm -it -v .:/mnt jellyplex /mnt/DEMO_PLEX_LIBRARY/Movies /mnt/DEMO_PLEX_LIBRARY/Jellyfin
```

## Usage

Originally, this script was designed for use in Unraid as a standalone file. That version is still available in the `unraid_user_scripts` branch. On Unraid, the recommended way to run the script is via the Docker image. However, if you prefer to install the Python package locally (not on Unraid), the following examples show how you can use it as a CLI tool.

### Docker usage

To use the published container image without installing anything locally:

```bash
docker run --rm -it -v /your/media:/mnt ghcr.io/sniner/jellyplex-sync:latest /mnt/source /mnt/target
```

Example using the demo library included in the repo:

```bash
docker run --rm -it -v .:/mnt ghcr.io/sniner/jellyplex-sync:latest /mnt/DEMO_PLEX_LIBRARY/Movies /mnt/DEMO_PLEX_LIBRARY/Jellyfin
```

> Note: Make sure to adjust the volume mount (`-v`) so that both source and target paths are accessible inside the container. They must also reside within the same bind mount, otherwise hard links between source and target will not work.

### Media server integration

If you're using Unraid, you can add the included `jellyplex-sync.sh` script to the User Scripts plugin as a new custom script. This helper script pulls the latest container image (`ghcr.io/sniner/jellyplex-sync:latest`), removes any outdated images, and then runs the main sync operation.

At the very bottom of the script, you'll find the actual command that runs the container. Make sure to adjust the source and target paths to match your own media library structure.

> ⚠️ Important: The script runs in `--dry-run` mode by default. This means it won't make any changes yet — it will only show what would happen. Once you're confident everything is working as expected, you can remove the `--dry-run` flag to perform real changes.

Although tailored for Unraid, this script can also be used on other NAS systems or Linux servers — simply schedule it as a cronjob to automate regular syncs. Docker must be installed for the script to work, as it relies on the containerized version of the tool.

### Python CLI usage

If you install the Python package locally, you can run the tool as follows:

```bash
jellyplex-sync [OPTIONS] /path/to/jellyfin/library /path/to/plex/library
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

- `--dry-run`
  Show what would be done, without performing any actual changes. No files will be created, deleted, or linked.

- `--convert-to=...`
  Choose between `jellyfin`, `plex` or `auto` (which is the default): `jellyfin` assumes the source library is in Plex format and creates a Jellyfin-compatible mirror. `plex` does the opposite. And `auto` inspects the source library and selects the appropriate conversion automatically.

## Examples

Mirror a Jellyfin library into an empty Plex structure:

```bash
jellyplex-sync --create ~/Media/Jellyfin ~/Media/Plex
```

Mirror and remove anything in the Plex folder that no longer exists in Jellyfin:

```bash
jellyplex-sync --delete ~/Media/Jellyfin ~/Media/Plex
```

Verbose output with full debug information:

```bash
jellyplex-sync --verbose --debug --delete --create ~/Media/Jellyfin ~/Media/Plex
```

## Behavior

* **Hard links**: Video files are linked, not copied. This preserves disk space and ensures both libraries reflect the same physical files.

* **Asset folders**: Subdirectories (e.g., `other`, `interviews`) are processed recursively with the same hard-link logic. NB: rename `extras` folder to `other` in your Jellyfin library, because Plex does not recognize `extras`.

* **Stray items**: When `--delete` is used, any unexpected files or folders in the target library will be removed.

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
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

Each movie must reside in its own folder, with optional subfolders for extras. Different editions (e.g., Director's Cut, Theatrical Cut) must be named accordingly.

### Special filename handling

Jellyfin doesn't distinguish between editions (e.g., Director's Cut) and versions (e.g., 1080p vs. 4K). To work around this, I appended tags like "DVD", "BD", or "4K" to filenames in my personal library, ensuring the highest quality appears first and is selected by default in Jellyfin. Plex, on the other hand, supports editions natively and handles different versions via naming patterns and its internal version management. These specific tags are converted into Plex versions, while all other suffixes are treated as editions.

This naming convention is something I came up with for my personal library — it's not part of any official Jellyfin standard. If your setup uses a different scheme, you may want to adjust the parsing behavior by switching to a different VariantParser, such as the simpler SimpleVariantParser.

## Plex movie library outline

Plex follows a more structured naming convention than Jellyfin. While Jellyfin typically appends edition or variant information using a ` - ` (space-hyphen-space) pattern, Plex supports additional metadata inside **curly braces** for editions and **square brackets** for versions or other details.

Unlike Jellyfin, Plex’s naming system allows you to embed extra tags such as release source (`[BluRay]`), quality (`[4K]`), or codec (`[HEVC]`) directly in the filename. These tags are ignored by the default Plex scanners during media recognition, but remain visible in the interface — which makes them useful for organizing your collection without affecting playback or matching.

> Note: This behavior applies to Plex's default scanner. If you use custom scanners or agents, they may treat these tags differently.

I originally started with a Jellyfin-style library and converted it to be Plex-compatible. Over time, I came to prefer Plex's more expressive naming conventions and switched my personal collection to follow the Plex format. I now use Jellyfin mainly as a fallback for long-term archival and offline use.

This is the expected folder structure in Plex format (with some demo tags):

```
Movies
├── A Bridge Too Far (1977) {imdb-tt0075784}
│   ├── A Bridge Too Far (1977) {imdb-tt0075784}.mkv
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) {imdb-tt0082096}
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut} [1080p].mkv
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [1080p][remux].mkv
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

## License

This project is licensed under the [BSD 2-Clause License](./LICENSE).

## Disclaimer

This is a private project written for personal use. It doesn't cover all use cases or environments. Use at your own risk. Contributions or forks are welcome if you want to adapt it to your own setup.
