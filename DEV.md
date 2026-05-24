# Developer Reference

Internal reference for how this project models Plex and Jellyfin movie
library conventions. Captures *why* the code does what it does, the
terminology we use internally vs. what the upstream projects call the
same things, and the design constraints that follow from the asymmetries
between the two systems.

This is a living document. When you discover an edge case or a new
upstream behavior, add it here.

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

We deliberately avoid the word "tag" internally: Plex's docs use it
for the curly-brace form (which we call `attributes`), so calling our
square-bracket concept "tags" would collide. When you cite Plex docs,
quote them in their terms and translate to internal vocabulary
explicitly. "Label" is also Jellyfin's word for its `- <suffix>`
construct ("version label"); that is a different thing — Jellyfin
labels live outside brackets, ours live inside them.

## Plex naming convention (official)

```
/Movies/Movie Name (Year) {imdb-tt1234567}/Movie Name (Year) {imdb-tt1234567}.mkv
/Movies/Blade Runner (1982) {edition-Director's Cut}/Blade Runner (1982) {edition-Director's Cut}.mkv
```

- Folder name and video file name (sans extension) must match.
- `{}` content holds `attributes`: `{imdb-tt...}`, `{tmdb-...}`,
  `{tvdb-...}`, `{edition-Name}`.
- **Plex ignores `[bracketed]` text in filenames entirely.** This is
  not documented as a feature, but is a load-bearing emergent property
  we rely on — see "Asymmetry" below.
- Multi-part movies use split identifiers as filename suffixes:
  `pt1`/`pt2`, `cd1`/`cd2`, `disc1`/`disc2`. Max 8 parts; all parts
  must share the same container format.

### Plex limits

- **Edition names: max 32 characters** (Plex Movie Agent v1.28.1+,
  Plex Pass required for full feature support).
- **Stack size: max 8 parts.**

## Jellyfin naming convention (official)

```
Movie Name (Year) [imdbid-tt1234567]/
├── Movie Name (Year) [imdbid-tt1234567].mkv
├── Movie Name (Year) [imdbid-tt1234567] - 2160p.mkv
└── Movie Name (Year) [imdbid-tt1234567] - Director's Cut.mkv
```

- Quote from the docs: "Each file **must** begin exactly with the
  parent folder name — including any year and/or metadata provider IDs
  — before adding a version label."
- Provider IDs go in `[brackets]` with **`-id` suffix on the key**:
  `[imdbid-...]`, `[tmdbid-...]`, `[tvdbid-...]`.
- Multiple IDs allowed in one name: `Movie (1994) [tmdbid-680] [imdbid-tt0123456]`.
- "Version labels" come after `<space><hyphen><space>`. Resolutions
  ending in `p` or `i` get descending sort priority; everything else
  sorts alphabetically.
- Reserved characters that break things: `< > : " / \ | ? *`.
- 3D markers (case-insensitive): `3D`, `hsbs`, `fsbs`, `htab`, `ftab`,
  `mvc`. Separators: space, period, hyphen, underscore.

### What Jellyfin does *not* have

- No syntactic distinction between "edition" and other version labels
  — `- Director's Cut` and `- 1080p` are syntactically equivalent.
  Only resolution-shaped strings get special sort treatment.
- No equivalent of Plex's free `[bracket]` channel. Square brackets
  are only meaningful when they contain a recognized provider ID
  pattern.

## Identifier syntax — easily confused

| Provider | Plex | Jellyfin |
|---|---|---|
| IMDb | `{imdb-tt1234567}` | `[imdbid-tt1234567]` |
| TMDB | `{tmdb-12345}` | `[tmdbid-12345]` |
| TVDB | `{tvdb-12345}` | `[tvdbid-12345]` (shows only) |

Common mistakes when round-tripping by hand:

- Plex uses the bare provider name (`imdb`), Jellyfin appends `id`
  (`imdbid`).
- Plex bracket type is `{}`, Jellyfin is `[]`.
- TVDB on Jellyfin is shows-only.

## Extras subdirectories

Both systems allow a movie folder to hold subdirectories with bonus
content — trailers, deleted scenes, featurettes, and the like. The
recognized subfolder names are similar in spirit but **not the same
set**, the casing convention differs, and the generic catch-all
name differs in a way that has bitten us before.

### Plex (Title Case)

From the Plex extras article (see Sources), *"Where `Extra_Directory_Type`
is one of:"*

- `Behind The Scenes`
- `Deleted Scenes`
- `Featurettes`
- `Interviews`
- `Scenes`
- `Shorts`
- `Trailers`
- `Other` — the documented generic catch-all

**A literal `Extras` folder is NOT in Plex's recognized list.** Content
placed in an `Extras/` subdirectory is silently ignored by the Plex
scanner. For generic bonus content on Plex, use `Other` — or its
lowercase form `other`, which is empirically accepted as well (see
"Cross-reference and asymmetries" below).

Plex also supports a parallel mechanism — files placed directly in the
movie folder with a `-Extra_Type` filename suffix
(`-behindthescenes`, `-deleted`, `-featurette`, `-interview`, `-scene`,
`-short`, `-trailer`, `-other`). That is separate from the subfolder
convention and out of scope here.

### Jellyfin (lowercase)

From the Jellyfin movies docs (the extras section is included from a
partial — link in Sources), *"Supported folder types are:"*

- `behind the scenes`
- `deleted scenes`
- `interviews`
- `scenes`
- `samples`
- `shorts`
- `featurettes`
- `clips`
- `other` — *"Generic catch all for extras of an unknown type."*
- `extras` — *"Generic catch all for extras of an unknown type."* (identical wording)
- `trailers`
- `theme-music`
- `backdrops`

Both `other` and `extras` are documented as catch-alls with the same
wording on Jellyfin.

### Cross-reference and asymmetries

| Concept | Plex | Jellyfin |
|---|---|---|
| Behind-the-scenes | `Behind The Scenes` | `behind the scenes` |
| Deleted scenes | `Deleted Scenes` | `deleted scenes` |
| Featurettes | `Featurettes` | `featurettes` |
| Interviews | `Interviews` | `interviews` |
| Scenes | `Scenes` | `scenes` |
| Shorts | `Shorts` | `shorts` |
| Trailers | `Trailers` | `trailers` |
| Generic catch-all | `Other` (docs) / `other` (empirical) | `other` **or** `extras` |
| Samples | — | `samples` |
| Clips | — | `clips` |
| Theme music | — | `theme-music` |
| Backdrops | — | `backdrops` |

- **The `Extras` footgun goes one way.** A folder literally named
  `extras` is a Jellyfin catch-all and a Plex no-op. **The portable
  choice for a generic catch-all is lowercase `other`** — Jellyfin's
  documented form, and empirically accepted by Plex as well (the
  Plex docs show `Other` in Title Case, but the scanner accepts
  `other` in practice; confirmed in production use). When translating
  Jellyfin → Plex, a Jellyfin `extras/` folder should be remapped to
  `other`.
- **Casing is convention, not certainty.** Neither doc page
  explicitly states case-sensitivity rules. We have empirical
  evidence that Plex's scanner accepts lowercase `other`, but no
  data on the other category names (`Behind The Scenes`, etc.).
  Safest: emit each system's documented casing for the specific
  categories; lowercase `other` is fine — and preferable — for the
  catch-all because it survives both scanners with one spelling.
- **Granularity differs.** Jellyfin's `samples`, `clips`,
  `theme-music`, `backdrops` have no documented Plex equivalents.
  Translating Jellyfin → Plex, the safe fallback for all of these
  is `Other` (lossy — the specific category label is dropped). The
  Reporter emits a `Drop` for the lost category.

## Asymmetry of translation

The two systems' concept spaces are not isomorphic. Some translations
are information-preserving; some are lossy. This is intrinsic to the
model, not a bug.

### Plex → Jellyfin

| Element | Translation | Loss |
|---|---|---|
| `{imdb-tt...}` | `[imdbid-tt...]` | lossless |
| `{edition-X}` | ` - X` (version label) | loses the *semantic* "this is an edition" marker |
| `[label]` recognised as resolution etc. | promoted to part of the version label | reshuffled, but preserved |
| `[label]` not recognised (e.g. `[amazon]`, `[rented]`) | **dropped** | Jellyfin would stumble on it |

### Jellyfin → Plex

| Element | Translation | Loss |
|---|---|---|
| `[imdbid-tt...]` | `{imdb-tt...}` | lossless |
| ` - X` | heuristic split: resolution-shaped pieces → Plex `[label]`, remainder → `{edition-...}` | lossless when X parses cleanly |
| residue that doesn't parse | dropped into Plex `[label]` as catch-all | preserved (Plex ignores it anyway) |

### The round-trip caveat

`Plex → Jellyfin → Plex` is **not** identity for arbitrary `[labels]`. A
Plex file with `[amazon]` survives a Plex → Plex sync but loses
`[amazon]` after a hop through Jellyfin. This is fundamental to the
model: Jellyfin has no place to put a free user label without confusing
its scanner.

## Resolution label choices

Jellyfin's version-label sort rule has a subtle interaction with the
specific labels we emit, and the choice is deliberate.

The rule: version labels ending in `p` or `i` sort **descending by
resolution**; everything else sorts **alphabetically** (ASCII).

When syncing Plex → Jellyfin, the resolution `[labels]` get mapped to
shorthand labels: `[2160p]` → `4k`, `[1080p]` → `BD`, `[720p]` → `720p`,
`[DVD]` → `DVD`. These shorthands are chosen so that the alphabetical
sort order puts the *highest* quality first:

```
4k  <  BD  <  DVD     (digits sort before uppercase letters in ASCII)
```

Result in the Jellyfin UI: the highest-quality version is listed first
and gets auto-selected when the user opens the movie.

### Label construction: resolution first, edition second

When a Plex source carries both a resolution `[label]` and an
`{edition-X}`, the Jellyfin label combines them as
`<resolution> <edition>`, e.g. `- 4k Director's Cut`. The resolution
must come first so that the alphabetic sort (`4k` < `BD` < `DVD`) wins
across the *whole* label regardless of which editions are present —
`4k Director's Cut` sorts before `BD Theatrical Cut` because the
comparison starts at the front.

Putting the resolution last (`Director's Cut 1080p`) would *not* help,
either: the docs explicitly state the resolution-aware sort only
triggers when the version name **ends** with `p` or `i`. A label like
`1080p Director's Cut` ends with `t` and therefore falls back to
alphabetic sort — the embedded `p` is irrelevant.

Quote from the Jellyfin docs:

> A version name qualifies as a resolution name when ending with
> either a `p` or an `i`.

### Why not DVD/SDR/FHD/UHD?

The "modern" set DVD/SDR/FHD/UHD sorts as
`DVD < FHD < SDR < UHD` alphabetically — so a movie with a DVD and a
UHD copy would default-play the DVD. That ergonomic regression
outweighs the consistency win of more accurate terminology, so we keep
the existing labels.

### Why not 1080p/2160p/etc.?

`480p`/`720p`/`1080p`/`2160p` would also work — they trigger
Jellyfin's descending-by-resolution sort via the `p` suffix. The reason
we don't switch is that existing user libraries already use the
marketing labels (DVD/BD/4k) in their filenames, and any change would
require either a breaking rename pass or a permanent dual mapping.

## Translation engine architecture

### Pipeline

```
[PlexPath]     → [PlexLibraryReader]     → Model → [JellyfinLibraryWriter] → [JellyfinPath]
[JellyfinPath] → [JellyfinLibraryReader] → Model → [PlexLibraryWriter]     → [PlexPath]
```

The intermediate model is library-neutral. Each library contributes a
`LibraryReader` / `LibraryWriter` pair. Adding support for a third
media server is one Reader + one Writer; nothing else changes.

### Intermediate model (`model.py`)

```python
@dataclass(frozen=True)
class VideoInfo:
    extension: str
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class MovieInfo:
    title: str
    year: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()
    videos: tuple[VideoInfo, ...] = ()
```

- `attributes` carries `{key-value}` info (provider IDs, edition,
  future keys).
- `labels` carries free-form `[...]` markers (resolution shorthand,
  source markers, user notes).
- `videos` is a tuple because a single movie folder can hold multiple
  variants (different resolutions, editions).

The Reader is liberal: anything it can't classify still gets a place
in `attributes` or `labels`, so nothing gets lost on the input side.

### Reader / Writer protocols (`library.py`)

```python
class LibraryReader(Protocol):
    base_dir: Path
    @classmethod
    def shortname(cls) -> str: ...
    def parse_movie(self, path: Path) -> MovieInfo | None: ...
    def parse_video(self, path: Path) -> VideoInfo: ...


class LibraryWriter(Protocol):
    base_dir: Path
    @classmethod
    def shortname(cls) -> str: ...
    def movie_path(self, movie: MovieInfo, reporter: Reporter) -> Path: ...
    def video_path(self, movie: MovieInfo, video: VideoInfo, reporter: Reporter) -> Path: ...
```

The Reader has no Reporter — it accepts what's there and stuffs
unrecognised content into the generic model fields. The Writer takes
a Reporter because it must make lossy decisions and the caller needs
to know about them.

### Reporter

```python
@dataclass(frozen=True)
class Drop:
    kind: Literal["label", "attribute"]
    key: str | None       # attribute key, or None for labels
    value: str
    reason: str           # "not expressible in target", "exceeds length limit", ...


class Reporter(Protocol):
    def drop(self, drop: Drop) -> None: ...
    def info(self, message: str) -> None: ...
```

Concrete reporters for the three usable modes:

| Mode | Reporter | Behavior |
|---|---|---|
| lenient (default) | `LoggingReporter` | log each drop at warning level, continue |
| strict | `StrictReporter` | raise on first drop |
| report-only | `CollectingReporter` | accumulate drops for later inspection; used by the `diff` subcommand |

## Edge cases worth remembering

- **Filename ≡ folder name** is enforced by both systems; the scanner
  relies on it.
- **`hi` ambiguity**: Jellyfin uses `hi` as a subtitle flag for
  hearing-impaired, but `hi` is also the Hindi language code.
  Disambiguation requires an explicit language code first.
- **VIDEO_TS / BDMV folders**: Jellyfin doesn't support multiple
  versions or external subtitle/audio inside them.
- **Multi-part + multi-version don't compose** on Jellyfin.
- **Plex Editions need Plex Pass + Movie Agent v1.28.1+** — but this
  doesn't constrain us; we just write the filenames.

## Sources

- Plex: [Naming and organizing your Movie files](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/)
- Plex: [Local Files for Movie Trailers and Extras](https://support.plex.tv/articles/local-files-for-trailers-and-extras/) — extras subfolder names and `-Extra_Type` suffix convention.
- Jellyfin: [Movies](https://jellyfin.org/docs/general/server/media/movies/)
- Jellyfin: [Metadata Provider Identifiers](https://jellyfin.org/docs/general/server/metadata/identifiers/)
- Jellyfin: [`_video-external-extras.md` partial](https://github.com/jellyfin/jellyfin.org/blob/master/docs/general/server/media/_video-external-extras.md) — ground-truth source for the extras subfolder list (the rendered Movies page includes this partial).
