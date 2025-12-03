# Bidirectional Movie Library Sync for Plex and Jellyfin

> **Fork Notice:** This is a fork of [sniner/jellyplex-sync](https://github.com/sniner/jellyplex-sync) maintained by `plex-migration-homelab` with enhanced features for multi-edition support, associated file syncing (subtitles, EDL files), and expanded video format support. The Docker image is published to `ghcr.io/plex-migration-homelab/jellyplex-sync`.

Can't decide between Jellyfin and Plex? This tool might help. It synchronizes your **movie library** between Jellyfin and Plex formats in **both directions** — without duplicating any files. Instead, it uses **hardlinks** to mirror your collection efficiently, saving storage while keeping both libraries in sync.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the target library path. The source library is treated as the **only source of truth**, and any unmatched content in the target folder may be deleted without warning.

> **Note:** This tool is only useful if your media library is well-maintained and each movie resides in its own folder.

## Overview

The script scans the source library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

This fork adds enhanced support for multi-edition movies (Extended, Theatrical, Director's Cut, etc.), automatically syncing all editions found in a source folder. Associated files such as subtitles (`.srt`, `.ass`, `.ssa`, `.sub`, `.idx`, `.vtt`) and edit decision lists (`.edl`) are now synced alongside their parent videos with proper renaming. Additionally, the supported video formats have been expanded beyond `.mkv` and `.m4v` to include `.mp4`, `.avi`, `.mov`, `.wmv`, `.ts`, and `.webm`. Provider tags (such as `{tmdb-xxx}` and `{imdb-xxx}`) are now preserved from source filenames when syncing to the target to ensure correct media identification even when folder-level metadata is insufficient.

> ⚠️ **Important:** This script is designed exclusively for **movie libraries**. It does **not** support TV shows or miniseries. However, this is usually not a limitation in practice: for shows, Jellyfin and Plex use very similar directory structures, so you can typically point both apps to the same library without issues.

> ⚠️ **Unraid:** This script is not compatible with Unraid User Scripts. If you do not want to use the container image, there is an older release in branch `unraid_user_scripts`. Switch to this branch and use the single-file script - but please don't forget to install the Python Plugin in Unraid first.

## Docker Image

If you want to build the docker image locally:

```bash
cd .../jellyplex-sync
docker build -t jellyplex .
```

To run the docker container with the demo library in the project folder:

```bash
docker run --rm -it -v .:/mnt jellyplex /mnt/DEMO_PLEX_LIBRARY/Movies /mnt/DEMO_PLEX_LIBRARY/Jellyfin
```

## Usage

Originally, this script was designed for use in Unraid as a standalone file. That version is still available in the `unraid_user_scripts` branch. On Unraid, the recommended way to run the script is via the Docker image. However, if you prefer to install the Python package locally (i.e. not on Unraid), the following examples show how you can use it as a CLI tool.

### Docker usage

To pull the latest image:

```bash
docker pull ghcr.io/plex-migration-homelab/jellyplex-sync:latest
```

To use the published container image without installing anything locally:

```bash
docker run --rm -it -v /your/media:/mnt ghcr.io/plex-migration-homelab/jellyplex-sync:latest /mnt/source /mnt/target
```

Example using the demo library included in the repo:

```bash
docker run --rm -it -v .:/mnt ghcr.io/plex-migration-homelab/jellyplex-sync:latest /mnt/DEMO_PLEX_LIBRARY/Movies /mnt/DEMO_PLEX_LIBRARY/Jellyfin
```

> Note: Make sure to adjust the volume mount (`-v`) so that both source and target paths are accessible inside the container. They must also reside within the same bind mount, otherwise hard links between source and target will not work.

### Media server integration

If you're using Unraid, you can add the included `jellyplex-sync.sh` script to the User Scripts plugin as a new custom script. This helper script pulls the latest container image (`ghcr.io/plex-migration-homelab/jellyplex-sync:latest`), removes any outdated images, and then runs the main sync operation.

At the very bottom of the script, you'll find the actual command that runs the container. Make sure to adjust the source and target paths to match your own media library structure.

> ⚠️ Important: The script runs in `--dry-run` mode by default. This means it won't make any changes yet — it will only show what would happen. Once you're confident everything is working as expected, you can remove the `--dry-run` flag to perform real changes.

Although tailored for Unraid, this script can also be used on other NAS systems or Linux servers — simply schedule it as a cronjob to automate regular syncs or run it manually on demand. Docker must be installed for the script to work, as it relies on the containerized version of the tool.

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

- `--update-filenames`
  Rename existing hardlinks in the target library if they are stale (i.e., pointing to the correct source file but with an outdated name). This is useful when naming conventions change (e.g., adding provider IDs or edition tags) and you want to fix the target filenames without recreating the hardlinks. If not specified, stale links will cause a warning and the creation of a duplicate file (the new correct name) will be skipped to avoid conflicts.

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

## Partial Sync & Radarr Hook

You can sync a single movie folder instead of scanning the entire library. This is significantly faster for updates triggered by media management tools like Radarr.

### Manual Partial Sync

Use the `--partial` argument to specify the folder name (relative to the source library root) or absolute path of the movie to sync:

```bash
jellyplex-sync --partial "Movie (2021)" /media/jellyfin /media/plex
# OR
jellyplex-sync --partial "/media/jellyfin/Movie (2021)" /media/jellyfin /media/plex
```

> **Note**: Partial sync disables global library cleanup. The `--delete` flag will only remove stray files *within the synced movie folder*.

### Radarr Integration

You can trigger a partial sync automatically when Radarr imports, upgrades, or renames a movie.

1.  **Go to Radarr Settings > Connect**.
2.  Add a new **Custom Script** notification (if running locally) or **Webhook** (if triggering remotely/via container).
    *   *For a Custom Script (local)*: Point to a wrapper script that runs `jellyplex-sync --radarr-hook ...`.
    *   *For a Webhook (remote)*: If you are wrapping `jellyplex-sync` in a small web service, configure the URL.
3.  **Enable on**: Download, Upgrade, Rename.
4.  **Environment Variables**: `jellyplex-sync` automatically reads the following environment variables set by Radarr:
    *   `radarr_eventtype`: The type of event (e.g., Download, Upgrade).
    *   `radarr_movie_path`: The full path to the movie folder.
    *   `radarr_movie_title`: The movie title (used for logging).

**Example Docker/CI Usage**:
If you are running `jellyplex-sync` in a container that has access to the same media volumes as Radarr:

```bash
# This command typically runs inside a script triggered by Radarr
# Ensure the container has the 'radarr_*' environment variables passed to it
jellyplex-sync --radarr-hook /mnt/source /mnt/target
```

**Path Mapping**:
If Radarr runs in a Docker container with different volume mappings than `jellyplex-sync` (e.g., Radarr sees `/movies/Avatar` but Sync sees `/mnt/media/movies/Avatar`), the tool will attempt to resolve the path by matching the folder name (`Avatar`) within the source library.

## Behavior

* **Hard links**: Video files are linked, not copied. This preserves disk space and ensures both libraries reflect the same physical files.

* **Asset folders**: Subdirectories (e.g., `other`, `interviews`) are processed recursively with the same hard-link logic. NB: rename `extras` folder to `other` in your Jellyfin library, because Plex does not recognize `extras`.

* **Stray items**: When `--delete` is used, any unexpected files or folders in the target library will be removed.

## Jellyfin movie library outline

This is the expected folder structure in your Jellyfin movie library. The script relies on it being consistent:

```
Movies
├── A Bridge Too Far (1977) [imdbid-tt0075784]
│   ├── A Bridge Too Far (1977) [imdbid-tt0075784].mkv
│   ├── A Bridge Too Far (1977) [imdbid-tt0075784].en.srt
│   ├── A Bridge Too Far (1977) [imdbid-tt0075784].en.forced.srt
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) [imdbid-tt0082096]
    ├── Das Boot (1981) [imdbid-tt0082096] - Director's Cut.mkv
    ├── Das Boot (1981) [imdbid-tt0082096] - Director's Cut.de.srt
    ├── Das Boot (1981) [imdbid-tt0082096] - Director's Cut.en.srt
    ├── Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.mp4
    ├── Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.en.srt
    ├── Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.edl
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

Each movie must reside in its own folder, with optional subfolders for extras. Different editions (e.g., Director's Cut, Theatrical Cut) are fully supported, with each edition able to have its own video file and associated subtitle/EDL files. Note how different video formats (`.mkv`, `.mp4`) can be used for different editions within the same movie folder.

### Special filename handling

Jellyfin doesn't distinguish between editions (e.g., Director's Cut) and versions (e.g., 1080p vs. 4K). To work around this, I appended tags like "DVD", "BD", or "4K" to filenames in my personal library, ensuring the highest quality appears first and is selected by default in Jellyfin. Plex, on the other hand, supports editions natively and handles different versions via naming patterns and its internal version management. These specific tags are converted into Plex versions, while all other suffixes are treated as editions.

This naming convention is something I came up with for my personal library — it's not part of any official Jellyfin standard. If your setup uses a different scheme, you may want to adjust the parsing behavior by switching to a different VariantParser, such as the simpler SimpleVariantParser.

## Plex movie library outline

Plex follows a more structured naming convention than Jellyfin. While Jellyfin typically appends edition or variant information using a ` - ` (space-hyphen-space) pattern, Plex supports additional metadata inside **curly braces** for editions and **square brackets** for versions or other details.

Unlike Jellyfin, Plex's naming system allows you to embed extra tags such as release source (`[BluRay]`), quality (`[4K]`), or codec (`[HEVC]`) directly in the filename. These tags are ignored by the default Plex scanners during media recognition, but remain visible in the interface — which makes them useful for organizing your collection without affecting playback or matching.

> Note: This behavior applies to Plex's default scanner. If you use custom scanners or agents, they may treat these tags differently.

I originally started with a Jellyfin-style library and converted it to be Plex-compatible. Over time, I came to prefer Plex's more expressive naming conventions and switched my personal collection to follow the Plex format. I now use Jellyfin mainly as a fallback for long-term archival and offline use.

This is the expected folder structure in Plex format (with some demo tags):

```
Movies
├── A Bridge Too Far (1977) {imdb-tt0075784}
│   ├── A Bridge Too Far (1977) {imdb-tt0075784}.mkv
│   ├── A Bridge Too Far (1977) {imdb-tt0075784}.en.srt
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) {imdb-tt0082096}
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut} [1080p].mkv
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut}.de.srt
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut}.en.srt
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [1080p].mp4
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut}.en.srt
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut}.edl
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

Note how associated files (subtitles, EDL files) follow the same naming pattern as their parent video files, ensuring they're correctly paired during sync. Provider tags like `{imdb-xxx}` or `{tmdb-xxx}` in source video filenames are preserved when syncing to the target, even when they're not present in the folder name.

## Testing

Before running the script on your production library, it's recommended to test with `--dry-run` and `--verbose` to preview what changes will be made:

```bash
# Dry-run to preview changes
docker run --rm -v /your/media:/mnt ghcr.io/plex-migration-homelab/jellyplex-sync:latest \
    --dry-run --verbose --delete --create /mnt/source /mnt/target
```

When testing multi-edition support, verify that:
- All editions in a source folder are linked in the target (not just the first one found)
- Each edition retains its correct naming pattern
- Associated subtitle and EDL files appear alongside their parent videos

To verify hardlinks are working correctly (not copies):

```bash
# Check inode numbers - they should match for hardlinked files
stat /path/to/source/movie.mkv
stat /path/to/target/movie.mkv
# Look for the "Inode" value in the output - it should be identical
```

If the inode numbers differ, the files were copied instead of hardlinked. This typically means the source and target are on different filesystems or the Docker volume mount wasn't configured correctly.

## Migration from Original

If you're switching from the original [sniner/jellyplex-sync](https://github.com/sniner/jellyplex-sync):

- **No data loss risk**: Existing synced files won't be recreated or modified. The script detects existing hardlinks and preserves them.
- **Incremental additions**: New editions or associated files found in your source library will be added on the next sync run.
- **Backwards compatible**: Your existing library structure remains valid. The enhancements simply add support for features that previously weren't synced.
- **Docker image**: Update your scripts to pull from `ghcr.io/plex-migration-homelab/jellyplex-sync:latest` instead of the original repository.

To migrate, simply run the updated tool against your existing libraries. Use `--dry-run` first to preview what new files will be added.

## Differences from Upstream

This fork differs from the original [sniner/jellyplex-sync](https://github.com/sniner/jellyplex-sync) in the following ways:

- **Expanded video formats**: Added support for `.mp4`, `.avi`, `.mov`, `.wmv`, `.ts`, and `.webm` (original only supported `.mkv` and `.m4v`)
- **Multi-edition support**: All editions in a source folder are synced, not just the first one found. Each edition gets its own properly-named hardlink in the target.
- **Associated file syncing**: Subtitles (`.srt`, `.ass`, `.ssa`, `.sub`, `.idx`, `.vtt`) and EDL files (`.edl`) are now synced alongside their parent videos with matching names.
- **Provider tag preservation**: File-level provider tags (`{tmdb-xxx}`, `{imdb-xxx}`) are preserved from source filenames to target filenames, ensuring correct media identification even when folder-level metadata is insufficient.
- **Stale link handling**: Detects and optionally renames existing hardlinks that have outdated filenames (via `--update-filenames`), preventing duplicates when naming conventions change.
- **Backwards compatibility**: Fully compatible with existing synced libraries created by the original tool. No breaking changes to library structure or naming conventions.

## License

This project is licensed under the [BSD 2-Clause License](./LICENSE).

## Disclaimer

This is a private project written for personal use. It doesn't cover all use cases or environments. Use at your own risk. Contributions or forks are welcome if you want to adapt it to your own setup.
