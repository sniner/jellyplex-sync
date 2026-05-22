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
| `tags` | `[free-form text]` (square brackets) | `[1080p]`, `[remux]`, `[amazon]` |
| `attributes` | `{key-value}` (curly braces) | `{imdb-tt1234567}`, `{edition-Director's Cut}` |
| `metadata` | umbrella term for tags + attributes + title + year | — |

### Cross-reference to upstream terminology

The vendors use the same words for different things. Be careful when
quoting their docs.

| Internal | Plex docs say | Jellyfin docs say |
|---|---|---|
| `tags` (`[...]`) | not recognized — Plex silently ignores them | conflated with "version labels"; can confuse the scanner |
| `attributes` (`{...}`) | **"tags"** (curly-brace form only) | "metadata provider id" (ID variant only); editions are "version labels" |
| `metadata` | — (no umbrella term) | — (no umbrella term) |

Note the cross-system clash: Plex's documentation uses the word "tag"
for the curly-brace form, which is the opposite of our convention.
When you cite Plex docs, quote them in their terms and translate to
internal vocabulary explicitly.

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

## Asymmetry of translation

The two systems' concept spaces are not isomorphic. Some translations
are information-preserving; some are lossy. This is intrinsic to the
model, not a bug.

### Plex → Jellyfin

| Element | Translation | Loss |
|---|---|---|
| `{imdb-tt...}` | `[imdbid-tt...]` | lossless |
| `{edition-X}` | ` - X` (version label) | loses the *semantic* "this is an edition" marker |
| `[tag]` recognised as resolution etc. | promoted to part of the version label | reshuffled, but preserved |
| `[tag]` not recognised (e.g. `[amazon]`, `[rented]`) | **dropped** | Jellyfin would stumble on it |

### Jellyfin → Plex

| Element | Translation | Loss |
|---|---|---|
| `[imdbid-tt...]` | `{imdb-tt...}` | lossless |
| ` - X` | heuristic split: resolution-shaped pieces → Plex `[tag]`, remainder → `{edition-...}` | lossless when X parses cleanly |
| residue that doesn't parse | dropped into Plex `[tag]` as catch-all | preserved (Plex ignores it anyway) |

### The round-trip caveat

`Plex → Jellyfin → Plex` is **not** identity for arbitrary `[tags]`. A
Plex file with `[amazon]` survives a Plex → Plex sync but loses
`[amazon]` after a hop through Jellyfin. This is fundamental to the
model: Jellyfin has no place to put a free user tag without confusing
its scanner.

When the migration mode (Paket 4) lands, this caveat needs to be
called out prominently in user-facing documentation.

## Resolution label choices

Jellyfin's version-label sort rule has a subtle interaction with the
specific labels we emit, and the choice is deliberate.

The rule: version labels ending in `p` or `i` sort **descending by
resolution**; everything else sorts **alphabetically** (ASCII).

When syncing Plex → Jellyfin, the resolution `[tags]` get mapped to
shorthand labels: `[2160p]` → `4k`, `[1080p]` → `BD`, `[720p]` → `720p`,
`[DVD]` → `DVD`. These shorthands are chosen so that the alphabetical
sort order puts the *highest* quality first:

```
4k  <  BD  <  DVD     (digits sort before uppercase letters in ASCII)
```

Result in the Jellyfin UI: the highest-quality version is listed first
and gets auto-selected when the user opens the movie.

### Label construction: resolution first, edition second

When a Plex source carries both a resolution `[tag]` and an
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
Either is a 0.2.0+ topic that needs more thought before we touch it.

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

## Living edge-case list

Cases we encounter while building or testing, kept here so they don't
get lost between sessions. Each entry should reference the test that
covers it (or a TODO for one).

- _(placeholder — fill during Paket 0 / future work)_

## Sources

- Plex: [Naming and organizing your Movie files](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/)
- Jellyfin: [Movies](https://jellyfin.org/docs/general/server/media/movies/)
- Jellyfin: [Metadata Provider Identifiers](https://jellyfin.org/docs/general/server/metadata/identifiers/)
