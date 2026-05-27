# Bidirectional Movie Library Sync for Plex and Jellyfin

Can't decide between Jellyfin and Plex? This tool might help. It synchronizes your **movie library** between Jellyfin and Plex formats in **both directions** — without duplicating any files. Instead, it uses **hardlinks** to mirror your collection efficiently, saving storage while keeping both libraries in sync.

> ⚠️ **0.3.0 is another major rewrite.** The internals are reorganised into a clean `discover → plan → realize` pipeline with an immutable Plan as a first-class concept. User-visible: a new **`plan` subcommand** that shows what a sync would do (text or `--json`) without touching anything, and **video-level clashes now auto-resolve with a hash suffix** instead of aborting the movie. The `sync` and `diff` CLI is unchanged. If you depend on the old shape, **try the new version with `--dry-run` first**. Cautious users can pin to a `0.2.x` (or even `0.1.x`) release until they're comfortable. See the [CHANGELOG](./CHANGELOG.md) for the full migration notes.

## Overview

The script scans the source library, parses each movie folder for metadata (title, year, optional provider ID), and reproduces the same directory structure in the target location. Rather than copying video files, it creates hard links to avoid extra storage usage. Asset folders (e.g., `extras`, `subtitles`) are also mirrored. Loose top-level files (posters, NFOs, subtitles) are synced 1:1 by default since 0.2.0. With `--delete`, any files or folders in the target that are no longer present in the source will be removed.

> **Warning:** This script will **overwrite the entire target directory**. Do not store or edit anything manually in the target library path. The source library is treated as the **only source of truth**, and any unmatched content in the target folder may be deleted without warning.

> **Note:** This tool is only useful if your media library is well-maintained and each movie resides in its own folder.

> ⚠️ **Movies only:** This script is designed exclusively for **movie libraries**. It does **not** support TV shows or miniseries. However, this is usually not a limitation in practice: for shows, Jellyfin and Plex use very similar directory structures, so you can typically point both apps to the same library without issues.

> ⚠️ **Stacked / multi-part movies are not supported:** Plex's multi-part filename suffixes (`pt1`/`pt2`, `cd1`/`cd2`, `disc1`/`disc2`) are not recognized — each part is treated as a separate video, which will likely confuse the target scanner. Pre-join multi-disc releases with `mkvmerge` before adding them to your library.

> ⚠️ **Hardlinks require a shared filesystem:** Source and target paths must live on the **same filesystem**. Hardlinks cannot span filesystems or physical disks. If they don't, switch to `--copy`. On Unraid's classic array this is a real concern — see the [Unraid section](#unraid-user-scripts) for details before running this tool there.

## Installation

### Python package (recommended)

The easiest way to install the CLI is via [uv](https://docs.astral.sh/uv/):

```bash
uv tool install jellyplex-sync
```

This places `jellyplex` and `jellyplex-sync` on your `PATH` in an isolated environment. `pipx install jellyplex-sync` works the same way if you prefer pipx.

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

The main CLI is `jellyplex` with four subcommands:

- **`jellyplex sync`** — mirror a source library into the target layout.
- **`jellyplex diff`** — read-only comparison of source and target. No filesystem changes. Useful before deleting your source after a migration.
- **`jellyplex plan`** — show the Plan a sync would execute (text or `--json`), without touching either side. Pre-flight check before sync, or machine-readable input for tooling.
- **`jellyplex import`** — **(experimental)** import video files from a staging area into a structured library. See below.

For backward compatibility, `jellyplex-sync` is also installed as a standalone command that does exactly what `jellyplex sync` does — same options, no subcommand needed.

### `sync`

```bash
jellyplex sync [OPTIONS] /path/to/source/library /path/to/target/library
```

The first positional is the source library, the second is the target. By default the tool auto-detects whether the source is a Jellyfin or Plex layout and converts to the other format.

#### Options

- `--create` — create the target directory if it doesn't exist.
- `--delete` — remove stray folders/files in the target that have no counterpart in the source. Without this, strays are reported in the summary but kept on disk.
- `--dry-run` — show what would happen without touching the filesystem.
- `-v`, `--verbose` — log every processed movie.
- `--debug` — enable debug-level logging.
- `--json` — emit a machine-readable JSON document on stdout (see [JSON output](#json-output) below). Stderr is automatically quieted to WARNING unless `--verbose`/`--debug` is set, so the document pipes cleanly into `jq`.
- `--source-format {jellyfin,plex,auto}` — declare the source library format. `auto` (default) inspects the source layout.
- `--target-format {jellyfin,plex,auto}` — declare the target library format. `auto` (default) picks the opposite of the source. Setting both flags to the same value puts the tool into lint/normalize mode (rewrite a library in its own format, e.g. to canonicalize Plex labels).

**Materializer flags** (mutually exclusive — pick at most one):

- `--hardlink` (default) — create a hardlink at the target pointing to the source inode. Requires source and target on the same filesystem.
- `--copy` — copy bytes. On re-runs, skips files whose target already has the same size **and** mtime as the source.
- `--force-copy` — always copy, no skip heuristic.

Use `--copy` when source and target are on different filesystems (NAS to local disk, cross-pool moves, etc.). The size+mtime check makes re-runs cheap.

#### Examples

Mirror a Jellyfin library into a new Plex structure:

```bash
jellyplex sync --create ~/Media/Jellyfin ~/Media/Plex
```

Migration with cleanup (target becomes a clean mirror):

```bash
jellyplex sync --delete --create ~/Media/Jellyfin ~/Media/Plex
```

Cross-filesystem copy with safe re-runs:

```bash
jellyplex sync --copy --create /mnt/nas/Movies /mnt/local/Plex
```

Dry-run a verbose, full sync with deletion:

```bash
jellyplex sync --dry-run --verbose --delete --create ~/Media/Jellyfin ~/Media/Plex
```

### `diff`

```bash
jellyplex diff [OPTIONS] /path/to/source/library /path/to/target/library
```

Compares the two libraries without touching anything. Reports movies that exist only on one side, file-level differences inside shared movies, translation losses (Plex labels with no Jellyfin equivalent, for example), and entries the scanner ignored.

Exit codes follow the Unix `diff` convention:

- `0` — in sync.
- `1` — differences found.
- `2` — setup error (missing directories, indecipherable format).

#### Example

Verify a target is a complete mirror before deleting the source:

```bash
jellyplex diff ~/Media/Jellyfin ~/Media/Plex
```

### `plan`

```bash
jellyplex plan [OPTIONS] /path/to/source/library /path/to/target/library
```

Shows the Plan a sync would execute — every movie folder, every translated video filename, every loose file, every asset subdirectory — without touching either filesystem. Useful as a pre-flight check ("will any movies clash? what gets translated?") or as a machine-readable input for tooling with `--json`.

Unlike `sync` and `diff`, the target directory does **not** need to exist. The whole point of `plan` is to answer "what WOULD happen" *before* any setup.

Exit codes:

- `0` — Plan produced successfully. Clashes and translation losses are reported but counted as informational, not failures.
- `2` — setup error (source missing, format undetectable).

#### Example

Pre-flight a sync, see exactly which target filenames would be created:

```bash
jellyplex plan ~/Media/Plex ~/Media/Jellyfin
```

Machine-readable, with `jq` to find videos that needed disambiguation:

```bash
jellyplex plan --json ~/Media/Plex ~/Media/Jellyfin \
    | jq '.movies[].videos[] | select(.disambiguation) | {source, target_name, disambiguation}'
```

### `import` (experimental)

> ⚠️ **This subcommand is experimental.** The exact behaviour may change in future releases as real-world use cases become clearer. Always start with `--dry-run`.

```bash
jellyplex import [OPTIONS] /path/to/staging /path/to/target/library
```

Imports video files from a staging area — a flat directory (or directory tree) where properly named video files have been dumped without the one-folder-per-movie structure that `sync` expects. Files are grouped by their parsed movie identity (title, year, provider ID) and placed into the correct movie folder in the target library.

Semantically distinct from `sync`:

- `sync` mirrors a structured library; the source stays intact.
- `import` ingests from an unstructured dump; the source files are **moved** (deleted after successful copy) by default.
- `import` never removes anything from the target — it only adds.

**Materializer flags** (mutually exclusive):

- `--move` (default) — copy each file to the target, then delete the source.
- `--copy` — copy files; the source is kept. Safe for a test run without `--dry-run`.

Other flags: `--dry-run`, `--create`, `--source-format`, `--target-format`, `-v`, `--debug`.

#### Limitations

- **Loose non-video files** (posters, `.nfo`, subtitles) in the staging area are not imported — there is no folder to assign them to. The target media server can download its own metadata.
- **Asset directories** (extras, trailers) in the staging area are not collected.
- **No `--json` output** yet for import.

#### Example

Move Plex-named video files into a new Jellyfin library:

```bash
jellyplex import --create /mnt/staging /mnt/library/Jellyfin
```

Preview first, keeping the source:

```bash
jellyplex import --copy --dry-run /mnt/staging /mnt/library/Jellyfin
```

### JSON output

All three subcommands accept `--json` for machine-readable output. The document goes to **stdout**; logs continue to go to stderr. Under `--json`, INFO logs are suppressed unless you pass `--verbose` or `--debug`, so the output pipes cleanly into tools like `jq` without filtering.

The schema (still evolving — pin a version when consuming):

- `operation`: `"sync"`, `"diff"`, or `"plan"`.
- `exit_code` (sync, diff): the process exit code, mirrored in the document for convenience.
- `source` / `target`: `{path, format}` for each endpoint.
- `dry_run` (sync only): whether the run was a preview.
- `summary`: counters; the set of fields depends on the operation.
  - sync: `movies_total`, `movies_processed`, `files_updated`, `files_removed`, `items_ignored`, `strays_in_target`, `clashes`.
  - plan: `movies`, `folder_clashes`, `movie_clashes`, `translation_losses`, `ignored`.
- `ignored`: list of source-side entries the scanner skipped, each `{path, name, reason}`.
- `strays_in_target` (sync only): list of names found in target that aren't in source.
- `translation_losses`: distinct `{kind, key, value, reason}` tuples for labels/attributes the target format can't express. Deduplicated — one entry per distinct loss, not per affected file.
- `events` (sync only): flat array of per-file actions, each `{action, target, source?, context?}`. Actions are `link`, `replace`, `skip`, `remove`. For `remove`, `context` is `library_stray` / `movie_stray` / `asset_stray`. Action names are the same in `--dry-run` and real runs; the top-level `dry_run` flag tells you which mode you were in.
- `clashes` (sync only): movie-level video clashes the disambiguator couldn't resolve at all. Normally empty since the hash-fallback resolves the practical cases.
- `diff`-specific fields: `movies_only_in_source`, `movies_only_in_target`, `differing_movies`, `in_sync`.
- `plan`-specific fields: `movies` (each with `videos`, `loose_files`, `assets`), `folder_clashes`, `movie_clashes`. Videos that needed disambiguation carry a `disambiguation` sub-object (`{strategy, detail}`) — `strategy="hash_suffix"` for the auto-resolution case.

#### `jq` examples

Show every file that would be replaced (with full paths):

```bash
jellyplex sync --json --dry-run /src /dst \
    | jq '.events[] | select(.action == "replace") | {source, target}'
```

Verify nothing important gets deleted before running a migration with `--delete`:

```bash
jellyplex sync --json --dry-run --delete /src /dst \
    | jq '.events[] | select(.action == "remove")'
```

Action distribution:

```bash
jellyplex sync --json --dry-run /src /dst \
    | jq '[.events[].action] | group_by(.) | map({action: .[0], count: length})'
```

### Docker

```bash
docker run --rm -v /your/media:/mnt ghcr.io/sniner/jellyplex-sync:latest sync /mnt/source /mnt/target
```

To try the tool, generate a small Plex-format library with
[jellyplex-gen](https://pypi.org/project/jellyplex-gen/) and point the
sync at it:

```bash
uvx jellyplex-gen plex --seed=demo --movies=20 --out=./demo-plex
mkdir ./demo-jellyfin
docker run --rm -v .:/mnt ghcr.io/sniner/jellyplex-sync:latest \
    sync /mnt/demo-plex /mnt/demo-jellyfin
```

> **Bind-mount note:** With `--hardlink` (default), both source and target paths must be reachable inside the container **through the same bind mount**, otherwise hardlinks between them cannot be created. With `--copy`, this constraint goes away.

### Unraid (User Scripts)

The repository includes a `jellyplex-sync.sh` helper you can add to the Unraid User Scripts plugin. It pulls the latest container image, removes outdated ones, and runs the sync. Adjust the source and target paths at the bottom of the script to match your library locations.

> ⚠️ **Dry-run by default:** The script ships with `--dry-run` enabled. It will only print what it would do — nothing changes on disk until you remove that flag.

> ⚠️ **Array layout matters:** Hardlinks only work within a single filesystem. On Unraid's classic md-array, paths under `/mnt/user/...` are served by **shfs**, which can spread files across multiple disks. The result is that hardlinks created across `/mnt/user/...` paths can silently fall back to copies, get broken when the mover relocates files between cache and array, or fail outright. For reliable operation on Unraid, use one of these layouts:
>
> - **Same disk:** Put both source and target under the same `/mnt/diskX/...` path so the kernel sees one filesystem.
> - **Cache pool:** Keep both libraries on a single cache pool with no mover involvement.
> - **ZFS pool (recommended):** ZFS-backed pools present a single filesystem and handle hardlinks cleanly.
> - **Different filesystems:** Switch to `--copy` instead of the default `--hardlink`. Bytes get duplicated, but the layout works.
>
> If you used the legacy single-file script from the `unraid_user_scripts` branch in the past, the same constraint applied there.

This helper can also be used on other NAS systems or Linux servers — schedule it via cron for unattended syncs. Docker must be installed.

## Behavior

- **Hardlinks (default)** — Video files are linked, not copied. Both libraries reference the same physical files on disk. Switch to `--copy` for cross-filesystem setups.
- **Asset folders** — Subdirectories (e.g., `other`, `interviews`) are processed recursively with the same materialization strategy. Note: rename your Jellyfin `extras` folder to `other`, since Plex does not recognize `extras`.
- **Loose top-level files** — Sidecar files (`.nfo`, posters, external subtitles, plain notes) at the top of a movie folder are synced 1:1 by default since 0.2.0. Pre-0.2.0 they were silently dropped — which made the tool unsafe for migrations. Dot-files (`.DS_Store`, `.stversions`, …) stay excluded.
- **Stray items** — With `--delete`, any file or folder in the target that has no counterpart in the source is removed. Without `--delete`, strays are still reported in the summary and the `--json` output, plus a warning at the end of the run points at `--delete`.
- **Ignored items** — Entries the scanner couldn't classify (stray files at the library root, folders whose names don't parse) are reported in the summary and the `--json` `ignored` array. They are *not* carried over to the target — useful to verify before deleting the source.
- **Video-level clashes auto-resolve** — When two source files would translate to the same target name (a common P→J outcome: `[1080p].mkv` and `[1080p] [remux].mkv` both collapse to `- BD.mkv`), a short hash of the source filename gets appended (e.g. `Movie - BD [a3f7c819].mkv`). Both files get synced; spot the hash in the `plan` output or in `--json` via the per-file `disambiguation` field. Pre-0.3 the whole movie was skipped on clash.
- **Folder-level clashes still abort** — Two source folders mapping to the same target folder name (e.g. via dropped `[bracket]` labels) is a structural error in the source library, not something to silently merge. The run is stopped, the clashing folders are listed, and you're asked to rename one side.

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

Jellyfin doesn't distinguish between editions (e.g., Director's Cut) and versions (e.g., 1080p vs. 4K). To work around this, I appended labels like "DVD", "BD", or "4K" to filenames in my personal library, ensuring the highest quality appears first and is selected by default in Jellyfin. Plex, on the other hand, supports editions natively and handles different versions via naming patterns and its internal version management. These specific labels are converted into Plex versions on the way over; other suffixes are treated as editions. The detailed mapping rules (and why DVD/BD/4k beats DVD/SDR/FHD/UHD despite the naming inconsistency) live in [SPECS.md](./SPECS.md).

### Plex

Plex follows a more structured naming convention than Jellyfin. While Jellyfin typically appends edition or variant information using a ` - ` (space-hyphen-space) pattern, Plex supports additional metadata inside **curly braces** for editions and **square brackets** for versions or other details.

Unlike Jellyfin, Plex's naming system allows you to embed extra labels such as release source (`[BluRay]`), quality (`[4K]`), or codec (`[HEVC]`) directly in the filename. These labels are ignored by the default Plex scanners during media recognition, but remain visible in the interface — which makes them useful for organizing your collection without affecting playback or matching.

> Note: This behavior applies to Plex's default scanner. If you use custom scanners or agents, they may treat these labels differently.

I originally started with a Jellyfin-style library and converted it to be Plex-compatible. Over time, I came to prefer Plex's more expressive naming conventions and switched my personal collection to follow the Plex format. I now use Jellyfin mainly as a fallback for long-term archival and offline use.

This is the expected folder structure in Plex format (with some demo labels):

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
