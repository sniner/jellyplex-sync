# Developer reference

How `jellyplex` is built — internal vocabulary, the pipeline
architecture, and where to look when adding a new feature. For *what*
the tool translates and the Plex/Jellyfin format details that motivate
the translation rules, see [SPECS.md](./SPECS.md).

## Internal vocabulary

| Internal term | Shape in filenames | Examples |
|---|---|---|
| `labels` | `[free-form text]` (square brackets) | `[1080p]`, `[remux]`, `[amazon]` |
| `attributes` | `{key-value}` (curly braces) | `{imdb-tt1234567}`, `{edition-Director's Cut}` |
| `metadata` | umbrella term for labels + attributes + title + year | — |

### Cross-reference to upstream terminology

The vendors use the same words for different things. Be careful when
quoting their docs.

| Internal | Plex docs say | Jellyfin docs say |
|---|---|---|
| `labels` (`[...]`) | not recognized — Plex silently ignores them | conflated with "version labels"; can confuse the scanner |
| `attributes` (`{...}`) | **"tags"** (curly-brace form only) | "metadata provider id" (ID variant only); editions are "version labels" |
| `metadata` | — (no umbrella term) | — (no umbrella term) |

The code deliberately avoids the word "tag" internally: Plex's docs use
it for the curly-brace form (which the code calls `attributes`), so
calling the square-bracket concept "tags" would collide. When citing
Plex docs, quote them in their terms and translate to internal
vocabulary explicitly. "Label" is also Jellyfin's word for its
`- <suffix>` construct ("version label"); that is a different thing —
Jellyfin labels live outside brackets, the internal ones live inside.

## Pipeline architecture

The engine is a three-phase pipeline: **discover → plan → realize**,
with the `Plan` as an immutable first-class artefact between phases.
Building a Plan is side-effect free; only the Realizer touches the
target filesystem.

### Data flow

```
                 ┌──────────────────┐
   source_root ──►   Discoverer     │   "where are the movies in the source tree?"
                 │  (pluggable)     │   yields DiscoveredGroup
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │     Reader       │   parse_movie / parse_video
                 │   (per format)   │   yields MovieInfo + VideoInfo
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │     Writer       │   movie_name / video_name (per item)
                 │   (per format)   │   reports Drops via Reporter
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  Disambiguator   │   resolves clashes within one PlannedMovie
                 │   (pluggable)    │   (hash fallback, etc.)
                 └──────────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │     Plan     │  ─►  json_output.write_plan
                  │  (immutable) │  ─►  compare(actual)  →  DiffResult
                  └──────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │    Realizer      │   walk Plan + target: link/copy/skip/remove
                 │  (Materializer)  │   the ONLY layer that sees dry_run
                 └──────────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │ RealizeStats │
                  └──────────────┘
```

### Module map

```
jellyplex_sync/
├── model.py         # MovieInfo, VideoInfo
├── plan.py          # Plan IR — frozen dataclasses
├── library.py       # LibraryReader / LibraryWriter Protocols, Reporter,
│                    #   Drop, IgnoredEntry, MovieClash, FolderClash
├── plex.py          # PlexLibraryReader, PlexLibraryWriter
├── jellyfin.py      # JellyfinLibraryReader, JellyfinLibraryWriter
├── discover.py      # SourceDiscoverer Protocol + TwoLevelDiscoverer
├── disambig.py      # Disambiguator Protocol + Naive / HashFallback impls
├── planner.py       # Planner: discover → interpret → name → disambiguate
├── realize.py       # Realizer + RealizeStats
├── compare.py       # compare(plan) → DiffResult (read target, subtract from plan)
├── materializer.py  # FileMaterializer impls: hardlink / copy / force-copy
├── json_output.py   # sync / diff / plan JSON serialisation
├── utils.py         # remove() with dry-run prediction
└── cli/sync.py      # argparse + subcommand dispatch
```

Each module has one verb: Discoverer finds, Reader interprets, Writer
names, Disambiguator resolves clashes, Planner orchestrates, Realizer
applies, compare diffs. Adding a feature usually means a new
implementation of one of the Protocols, without touching the others.

## Plan IR (`plan.py`)

The Plan is the data structure that bridges planning and realisation.
All types are `@dataclass(frozen=True)` — once built, a Plan cannot
mutate, so it's safe to share, cache, serialise, and compare across
runs.

```python
@dataclass(frozen=True)
class PlannedFile:
    source: pathlib.Path
    target_name: str                           # leaf name, no path separators
    drops: tuple[Drop, ...] = ()
    disambiguation: DisambiguationNote | None = None

@dataclass(frozen=True)
class PlannedAsset:                            # recursive
    source: pathlib.Path
    folder_name: str
    files: tuple[PlannedFile, ...] = ()
    subfolders: tuple["PlannedAsset", ...] = ()

@dataclass(frozen=True)
class PlannedMovie:
    source_path: pathlib.Path
    target_folder: pathlib.Path
    movie: MovieInfo
    videos: tuple[PlannedFile, ...] = ()       # unique names guaranteed
    loose_files: tuple[PlannedFile, ...] = ()
    assets: tuple[PlannedAsset, ...] = ()
    folder_drops: tuple[Drop, ...] = ()

@dataclass(frozen=True)
class Plan:
    source_root: pathlib.Path
    target_root: pathlib.Path
    source_format: str
    target_format: str
    movies: tuple[PlannedMovie, ...] = ()
    ignored: tuple[IgnoredEntry, ...] = ()
    clashes: tuple[MovieClash, ...] = ()       # rare with hash fallback
    folder_clashes: tuple[FolderClash, ...] = ()

@dataclass(frozen=True)
class DisambiguationNote:
    strategy: str    # e.g. "hash_suffix"
    detail: str      # e.g. "hash from source filename 'Movie [1080p].mkv'"
```

`PlannedFile.target_name` is always a single filename. Directory
nesting lives in the `PlannedAsset.subfolders` recursion — the
realizer walks the tree and `mkdir(parents=True)` takes care of the
intermediate directories.

## Intermediate model (`model.py`)

```python
@dataclass
class VideoInfo:
    extension: str
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()

@dataclass
class MovieInfo:
    title: str
    year: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()
```

- `attributes` carries `{key-value}` info (provider IDs, edition,
  future keys).
- `labels` carries free-form `[...]` markers (resolution shorthand,
  source markers, user notes).

The Reader is liberal: anything it can't classify still gets a place
in `attributes` or `labels`, so nothing gets lost on the input side.

## Reader / Writer protocols (`library.py`)

```python
class LibraryReader(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def parse_movie(self, path: pathlib.Path) -> MovieInfo | None: ...
    def parse_video(self, path: pathlib.Path) -> VideoInfo: ...

class LibraryWriter(Protocol):
    base_dir: pathlib.Path

    @classmethod
    def shortname(cls) -> str: ...

    def movie_name(self, movie: MovieInfo, reporter: Reporter) -> str: ...
    def video_name(
        self,
        movie: MovieInfo,
        video: VideoInfo,
        reporter: Reporter,
        *,
        hash_suffix: str | None = None,
    ) -> str: ...
```

The Reader has no Reporter — it accepts whatever's on disk and stuffs
unrecognised content into the generic model fields. The Writer takes a
Reporter because it has to make lossy decisions (drop a label, collapse
a provider ID set) and the caller needs to know about them.

`hash_suffix` is `None` for the common case. The `HashFallbackDisambiguator`
passes a short identifier when collision resolution kicks in; each
Writer chooses where the suffix lands in its target format (Plex: a
bracket-label at the end; Jellyfin: bracketed in the version-label
position).

Adding support for a third media server is one Reader + one Writer;
nothing else changes.

## Reporter (`library.py`)

```python
@dataclass
class Drop:
    kind: Literal["label", "attribute"]
    key: str | None       # attribute key, or None for labels
    value: str
    reason: str

class Reporter(Protocol):
    def drop(self, drop: Drop) -> None: ...
    def info(self, message: str) -> None: ...
```

Three concrete reporters cover the usable modes:

| Mode | Reporter | Behaviour |
|---|---|---|
| lenient (default) | `LoggingReporter` | log each drop, continue |
| strict | `StrictReporter` | raise on first drop |
| report-only | `CollectingReporter` | accumulate drops for later inspection; powers the `diff` and `plan` subcommands |

## Discoverer (`discover.py`)

```python
@dataclass(frozen=True)
class DiscoveredGroup:
    source_path: pathlib.Path
    video_files: tuple[pathlib.Path, ...] = ()
    asset_dirs: tuple[pathlib.Path, ...] = ()
    loose_files: tuple[pathlib.Path, ...] = ()

class SourceDiscoverer(Protocol):
    def discover(
        self, root: pathlib.Path,
        *, ignored: list[IgnoredEntry] | None = None,
    ) -> Iterable[DiscoveredGroup]: ...
```

`TwoLevelDiscoverer` (default) is the classic
`<library>/<movie-folder>/<files>` layout. Pre-classifies each group's
contents into video / asset / loose so the planner doesn't have to
inspect file extensions itself. Format-agnostic — it doesn't know
about Plex vs. Jellyfin, only what a video file extension looks like.

The seam is here so other source layouts (a flat dump, deeply nested
trees, multiple movies in one folder) can plug in as additional
`SourceDiscoverer` implementations without touching anything else.

## Disambiguator (`disambig.py`)

```python
class Disambiguator(Protocol):
    def disambiguate(
        self,
        movie: MovieInfo,
        videos: list[tuple[VideoInfo, pathlib.Path]],
        writer: LibraryWriter,
        reporter: Reporter,
        *,
        movie_folder: str,
    ) -> DisambiguationResult: ...

@dataclass(frozen=True)
class DisambiguationResult:
    names: dict[pathlib.Path, str]
    notes: dict[pathlib.Path, DisambiguationNote | None]
    unresolved: tuple[MovieClash, ...] = ()
```

Two implementations ship:

- `NaiveDisambiguator` — calls `writer.video_name` per video; if two
  videos produce the same name, returns them as `unresolved` (and the
  Planner excludes them from the Plan). Strict-mode behaviour.
- `HashFallbackDisambiguator` (default) — same first pass; on
  collision, asks the Writer to re-render with `hash_suffix=<short
  SHA-256 prefix of source filename>`. Source filenames are FS-unique
  within a folder, so the rendered names are unique modulo a
  vanishingly small SHA-256 prefix collision (negligible at the
  default 8-char prefix for realistic folder sizes). Each touched
  file gets a `DisambiguationNote(strategy="hash_suffix")` so the
  --json output and `plan` subcommand can surface why.

## Planner (`planner.py`)

```python
class Planner:
    def __init__(
        self,
        reader: LibraryReader,
        writer: LibraryWriter,
        *,
        discoverer: SourceDiscoverer | None = None,
        disambiguator: Disambiguator | None = None,
        reporter: Reporter | None = None,
    ) -> None: ...

    def plan(self) -> Plan: ...
```

Pure (modulo Reader I/O for `parse_movie` / `parse_video`). Calling
`plan()` twice with the same inputs produces equal Plans. That
property is what makes plans diffable across runs and cacheable
across phases.

The Planner does:

1. `discoverer.discover(source_root)` → candidate groups.
2. For each group, `reader.parse_movie` + `reader.parse_video` →
   infos. Folders the reader rejects become `IgnoredEntry`s.
3. `writer.movie_name(movie)` → target folder name. Two source
   folders mapping to the same target name become a `FolderClash`
   and both source folders are skipped.
4. `disambiguator.disambiguate(...)` → unique video names per movie.
5. Build `PlannedMovie` (videos, loose files, recursive assets).
6. Aggregate into `Plan`.

## Realizer (`realize.py`)

```python
@dataclass
class RealizeStats:
    movies_processed: int = 0
    files_linked: int = 0
    files_removed: int = 0
    ignored_count: int = 0
    strays_in_target: list[str] = field(default_factory=list)
    events: list[FileEvent] = field(default_factory=list)

class Realizer:
    def __init__(self, materializer: FileMaterializer | None = None) -> None: ...

    def apply(
        self,
        plan: Plan,
        *,
        dry_run: bool = False,
        delete: bool = False,
        verbose: bool = False,
        stats: RealizeStats | None = None,
    ) -> RealizeStats: ...
```

The only layer that observes `dry_run`. All other layers compute,
this one acts (or doesn't, under dry-run). Stray detection happens
here: list `plan.target_root`, subtract the planned folder names,
mark the rest as strays. The same idea applies one level deeper
inside each movie folder (movie-level strays) and inside each asset
subfolder (asset-level strays). `FileEvent.context` records which
scope a remove came from (`library_stray` / `movie_stray` /
`asset_stray`).

## Compare (`compare.py`)

```python
def compare(plan: Plan) -> DiffResult: ...
```

Read-only. Walks `plan.target_root` one level deep and subtracts what's
there from what the Plan expects. The same target-side traversal the
old `_compute_diff` did, but the *expected* side comes for free from
the Plan instead of being re-derived by walking the source again.

## Materializer (`materializer.py`)

```python
class FileMaterializer(Protocol):
    name: str

    def materialize(
        self,
        src: pathlib.Path,
        dst: pathlib.Path,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        events: list[FileEvent] | None = None,
    ) -> bool: ...
```

Three impls: `HardlinkMaterializer` (default — same-filesystem
hardlinks), `CopyMaterializer` (cross-filesystem; skips by
size+mtime on re-runs), `ForceCopyMaterializer` (always rewrites).
The seam exists so the CLI can swap strategies without the orchestration
needing to know how the bytes get there.

## Public API surface

```python
import jellyplex_sync as jp

# Top-level functions (the CLI thin-wraps these):
jp.sync(source, target, *, dry_run, delete, create, source_format,
        target_format, reporter, materializer, stats, ...) -> int
jp.diff(source, target, *, source_format, target_format, out, as_json,
        ...) -> int
jp.plan(source, target, *, source_format, target_format, out, as_json,
        ...) -> int

# IR types — build, inspect, serialise:
jp.Plan, jp.PlannedMovie, jp.PlannedFile, jp.PlannedAsset
jp.DisambiguationNote

# Translation-side observability:
jp.Drop, jp.Reporter, jp.LoggingReporter, jp.StrictReporter,
jp.CollectingReporter, jp.dedupe_drops

# Clash / scan-skip types:
jp.MovieClash, jp.FolderClash, jp.IgnoredEntry, jp.FileEvent

# Reader / Writer protocols and the two built-in impls per side:
jp.LibraryReader, jp.LibraryWriter
jp.PlexLibraryReader, jp.PlexLibraryWriter
jp.JellyfinLibraryReader, jp.JellyfinLibraryWriter

# Materializers:
jp.FileMaterializer, jp.HardlinkMaterializer, jp.CopyMaterializer,
jp.ForceCopyMaterializer
```

`Planner`, `Realizer`, `compare`, and the discoverer/disambiguator
implementations are accessible by their module path
(`from jellyplex_sync.planner import Planner`, etc.) but not yet
re-exported from the top-level package — pin to the module path if you
build against them.
