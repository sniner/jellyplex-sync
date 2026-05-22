"""Round-trip property: parse → render to the other format → parse → render
back to the original format should be idempotent for sane samples.

This pins the symmetry of the translation layer before Paket 1 lifts it out
of `jellyfin.py` into a dedicated engine. If symmetry breaks during the
refactor, these tests catch it before the user does.

Lossy paths (e.g. Plex tags that don't survive a hop through Jellyfin) are
deliberately excluded — those have one-way coverage in test_renaming_*.
"""

from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def jlib() -> jp.JellyfinLibrary:
    return jp.JellyfinLibrary(Path("./Jellyfin"))


@pytest.fixture
def plib() -> jp.PlexLibrary:
    return jp.PlexLibrary(Path("./Plex"))


# Sample filenames that we expect to survive a full round trip in both
# directions without loss. Each line is a Plex-format filename — the Jellyfin
# equivalent is derived during the test, not hand-written, so we test the
# property, not a particular intermediate form.
PLEX_ROUND_TRIP_SAMPLES = [
    "First movie.mkv",
    "First movie (1984).mkv",
    "A Bridge Too Far (1977) {imdb-tt0075784}.mkv",
    "Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut}.mkv",
    "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [1080p].mkv",
    "Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut} [2160p].mkv",
    "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [720p].mkv",
    "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [DVD].mkv",
]


def _render(src_lib: jp.MediaLibrary, dst_lib: jp.MediaLibrary, filename: str) -> str:
    """Parse a filename in src's convention, then render it in dst's."""
    source_path = Path(src_lib.base_dir, filename)
    movie = src_lib.parse_movie_path(Path(src_lib.base_dir, source_path.stem))
    assert movie is not None, f"Failed to parse movie: {filename}"
    video = src_lib.parse_video_path(source_path)
    return dst_lib.video_name(movie, video)


@pytest.mark.parametrize("plex_name", PLEX_ROUND_TRIP_SAMPLES, ids=PLEX_ROUND_TRIP_SAMPLES)
def test_plex_to_jellyfin_to_plex_is_idempotent(plib, jlib, plex_name):
    jellyfin_name = _render(plib, jlib, plex_name)
    plex_again = _render(jlib, plib, jellyfin_name)
    assert plex_again == plex_name, (
        f"Round trip changed the filename:\n"
        f"  Plex (in):  {plex_name}\n"
        f"  Jellyfin:   {jellyfin_name}\n"
        f"  Plex (out): {plex_again}"
    )


@pytest.mark.parametrize("plex_name", PLEX_ROUND_TRIP_SAMPLES, ids=PLEX_ROUND_TRIP_SAMPLES)
def test_jellyfin_to_plex_to_jellyfin_is_idempotent(plib, jlib, plex_name):
    # Use the Plex sample to compute the canonical Jellyfin form, then
    # round-trip from there. This avoids hand-writing Jellyfin sources whose
    # canonical form we'd have to guess.
    jellyfin_start = _render(plib, jlib, plex_name)
    plex_intermediate = _render(jlib, plib, jellyfin_start)
    jellyfin_again = _render(plib, jlib, plex_intermediate)
    assert jellyfin_again == jellyfin_start, (
        f"Round trip changed the filename:\n"
        f"  Jellyfin (in):  {jellyfin_start}\n"
        f"  Plex:           {plex_intermediate}\n"
        f"  Jellyfin (out): {jellyfin_again}"
    )
