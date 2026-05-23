# Bidirectional Movie Library Sync for Plex and Jellyfin

Can't decide between Jellyfin and Plex? This tool might help. It synchronizes your **movie library** between Jellyfin and Plex formats in **both directions** — without duplicating any files. Instead, it uses **hardlinks** to mirror your collection efficiently, saving storage while keeping both libraries in sync.

## Overview

The script scans the source library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the target library path. The source library is treated as the **only source of truth**, and any unmatched content in the target folder may be deleted without warning.

> **Note:** This tool is only useful if your media library is well-maintained and each movie resides in its own folder.

> ⚠️ **Movies only:** This script is designed exclusively for **movie libraries**. It does **not** support TV shows or miniseries. However, this is usually not a limitation in practice: for shows, Jellyfin and Plex use very similar directory structures, so you can typically point both apps to the same library without issues.

> ⚠️ **Hardlinks require a shared filesystem:** Source and target paths must live on the **same filesystem**. Hardlinks cannot span filesystems or physical disks. On Unraid's classic array this is a real concern — see the [Unraid section](#unraid-user-scripts) for details before running this tool there.

## Installation

### Python package (recommended)

The easiest way to install the CLI is via [uv](https://docs.astral.sh/uv/):

```bash
uv tool install jellyplex-sync
```

This places `jellyplex-sync` on your `PATH` in an isolated environment. `pipx install jellyplex-sync` works the same way if you prefer pipx.

### Docker

A prebuilt container image is published to GitHub Container Registry:

```
ghcr.io/sniner/jellyplex-sync:latest
```

If you'd rather build it yourself:

```bash
docker build -t jellyplex-sync .
```

## Usage

### CLI

```bash
jellyplex-sync [OPTIONS] /path/to/source/library /path/to/target/library
```

The first positional argument is the source library, the second is the target. By default the tool auto-detects whether the source is a Jellyfin or Plex layout and converts it to the other format.

#### Options

- `--create` — create the target directory if it doesn't exist.
- `--delete` — remove movie folders and stray files in the target that are not present in the source.
- `--dry-run` — show what would happen without touching the filesystem.
- `--verbose` — log every processed movie.
- `--debug` — enable debug-level logging.
- `--source-format {jellyfin,plex,auto}` — declare the source library format. `auto` (default) inspects the source layout.
- `--target-format {jellyfin,plex,auto}` — declare the target library format. `auto` (default) picks the opposite of the source. Setting both flags to the same value puts the tool into lint/normalize mode (rewrite a library in its own format, e.g. to canonicalize tags).

#### Examples

Mirror a Jellyfin library into a new Plex structure:

```bash
jellyplex-sync --create ~/Media/Jellyfin ~/Media/Plex
```

Mirror and prune anything in the Plex folder that no longer exists in Jellyfin:

```bash
jellyplex-sync --delete ~/Media/Jellyfin ~/Media/Plex
```

Dry-run a verbose, full sync with deletion:

```bash
jellyplex-sync --dry-run --verbose --delete --create ~/Media/Jellyfin ~/Media/Plex
```

### Docker

```bash
docker run --rm -v /your/media:/mnt ghcr.io/sniner/jellyplex-sync:latest /mnt/source /mnt/target
```

To try the tool, generate a small Plex-format library with
[jellyplex-gen](https://pypi.org/project/jellyplex-gen/) and point the
sync at it:

```bash
uvx jellyplex-gen plex --seed=demo --movies=20 --out=./demo-plex
mkdir ./demo-jellyfin
docker run --rm -v .:/mnt ghcr.io/sniner/jellyplex-sync:latest \
    /mnt/demo-plex /mnt/demo-jellyfin
```

> **Bind-mount note:** Both source and target paths must be reachable inside the container **through the same bind mount**, otherwise hardlinks between them cannot be created.

### Unraid (User Scripts)

The repository includes a `jellyplex-sync.sh` helper you can add to the Unraid User Scripts plugin. It pulls the latest container image, removes outdated ones, and runs the sync. Adjust the source and target paths at the bottom of the script to match your library locations.

> ⚠️ **Dry-run by default:** The script ships with `--dry-run` enabled. It will only print what it would do — nothing changes on disk until you remove that flag.

> ⚠️ **Array layout matters:** Hardlinks only work within a single filesystem. On Unraid's classic md-array, paths under `/mnt/user/...` are served by **shfs**, which can spread files across multiple disks. The result is that hardlinks created across `/mnt/user/...` paths can silently fall back to copies, get broken when the mover relocates files between cache and array, or fail outright. For reliable operation on Unraid, use one of these layouts:
>
> - **Same disk:** Put both source and target under the same `/mnt/diskX/...` path so the kernel sees one filesystem.
> - **Cache pool:** Keep both libraries on a single cache pool with no mover involvement.
> - **ZFS pool (recommended):** ZFS-backed pools present a single filesystem and handle hardlinks cleanly.
>
> If you used the legacy single-file script from the `unraid_user_scripts` branch in the past, the same constraint applied there.

This helper can also be used on other NAS systems or Linux servers — schedule it via cron for unattended syncs. Docker must be installed.

## Behavior

- **Hardlinks** — Video files are linked, not copied. Both libraries reference the same physical files on disk.
- **Asset folders** — Subdirectories (e.g., `other`, `interviews`) are processed recursively with the same hardlink logic. Note: rename your Jellyfin `extras` folder to `other`, since Plex does not recognize `extras`.
- **Stray items** — With `--delete`, any file or folder in the target that has no counterpart in the source is removed.

## Library layouts

### Jellyfin

This is the expected folder structure in a Jellyfin movie library. The parser relies on it being consistent:

```
Movies
├── A Bridge Too Far (1977) [imdbid-tt0075784]
│   ├── A Bridge Too Far (1977) [imdbid-tt0075784].mkv
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) [imdbid-tt0082096]
    ├── Das Boot (1981) [imdbid-tt0082096] - Director's Cut.mkv
    ├── Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.mkv
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

Each movie must reside in its own folder, with optional subfolders for extras. Different editions (e.g., Director's Cut, Theatrical Cut) must be named accordingly.

#### Special filename handling

Jellyfin doesn't distinguish between editions (e.g., Director's Cut) and versions (e.g., 1080p vs. 4K). To work around this, I appended tags like "DVD", "BD", or "4K" to filenames in my personal library, ensuring the highest quality appears first and is selected by default in Jellyfin. Plex, on the other hand, supports editions natively and handles different versions via naming patterns and its internal version management. These specific tags are converted into Plex versions, while all other suffixes are treated as editions.

This naming convention is something I came up with for my personal library — it's not part of any official Jellyfin standard. If your setup uses a different scheme, you may want to adjust the parsing behavior by switching to a different `VariantParser`, such as the simpler `SimpleVariantParser`.

### Plex

Plex follows a more structured naming convention than Jellyfin. While Jellyfin typically appends edition or variant information using a ` - ` (space-hyphen-space) pattern, Plex supports additional metadata inside **curly braces** for editions and **square brackets** for versions or other details.

Unlike Jellyfin, Plex's naming system allows you to embed extra tags such as release source (`[BluRay]`), quality (`[4K]`), or codec (`[HEVC]`) directly in the filename. These tags are ignored by the default Plex scanners during media recognition, but remain visible in the interface — which makes them useful for organizing your collection without affecting playback or matching.

> Note: This behavior applies to Plex's default scanner. If you use custom scanners or agents, they may treat these tags differently.

I originally started with a Jellyfin-style library and converted it to be Plex-compatible. Over time, I came to prefer Plex's more expressive naming conventions and switched my personal collection to follow the Plex format. I now use Jellyfin mainly as a fallback for long-term archival and offline use.

This is the expected folder structure in Plex format (with some demo tags):

```
Movies
├── A Bridge Too Far (1977) {imdb-tt0075784}
│   ├── A Bridge Too Far (1977) {imdb-tt0075784}.mkv
│   └── trailers
│       └── A Bridge Too Far.mkv
└── Das Boot (1981) {imdb-tt0082096}
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut} [1080p].mkv
    ├── Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [1080p][remux].mkv
    └── other
        ├── Production Photos.mkv
        └── Making of.mkv
```

## License

This project is licensed under the [BSD 3-Clause License](./LICENSE).

## Disclaimer

This is a private project written for personal use. It doesn't cover all use cases or environments. Use at your own risk. Contributions or forks are welcome if you want to adapt it to your own setup.
