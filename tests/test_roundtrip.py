"""Round-trip property: parse → render to the other format → parse → render
back to the original format should be idempotent for sane samples.

This pins the symmetry of the translation layer. If symmetry breaks during
future refactors, these tests catch it before the user does.

Lossy paths (e.g. Plex tags that don't survive a hop through Jellyfin) are
deliberately excluded — those have one-way coverage in test_renaming_*.
"""

from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def jreader() -> jp.JellyfinLibraryReader:
    return jp.JellyfinLibraryReader(Path("./Jellyfin"))


@pytest.fixture
def jwriter() -> jp.JellyfinLibraryWriter:
    return jp.JellyfinLibraryWriter(Path("./Jellyfin"))


@pytest.fixture
def preader() -> jp.PlexLibraryReader:
    return jp.PlexLibraryReader(Path("./Plex"))


@pytest.fixture
def pwriter() -> jp.PlexLibraryWriter:
    return jp.PlexLibraryWriter(Path("./Plex"))


# Filenames expected to survive a full round trip in both directions without
# loss. Each line is a Plex-format filename; the Jellyfin equivalent is
# derived during the test, not hand-written, so we test the property, not a
# particular intermediate form.
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


def _plex_to_jelly(preader, jwriter, plex_name: str) -> str:
    source_path = Path(preader.base_dir, plex_name)
    movie = preader.parse_movie(Path(preader.base_dir, source_path.stem))
    assert movie is not None
    video = preader.parse_video(source_path)
    return jwriter.video_name(movie, video)


def _jelly_to_plex(jreader, pwriter, jelly_name: str) -> str:
    source_path = Path(jreader.base_dir, jelly_name)
    movie = jreader.parse_movie(Path(jreader.base_dir, source_path.stem))
    assert movie is not None
    video = jreader.parse_video(source_path)
    return pwriter.video_name(movie, video)


@pytest.mark.parametrize("plex_name", PLEX_ROUND_TRIP_SAMPLES, ids=PLEX_ROUND_TRIP_SAMPLES)
def test_plex_to_jellyfin_to_plex_is_idempotent(preader, jwriter, jreader, pwriter, plex_name):
    jellyfin_name = _plex_to_jelly(preader, jwriter, plex_name)
    plex_again = _jelly_to_plex(jreader, pwriter, jellyfin_name)
    assert plex_again == plex_name, (
        f"Round trip changed the filename:\n"
        f"  Plex (in):  {plex_name}\n"
        f"  Jellyfin:   {jellyfin_name}\n"
        f"  Plex (out): {plex_again}"
    )


@pytest.mark.parametrize("plex_name", PLEX_ROUND_TRIP_SAMPLES, ids=PLEX_ROUND_TRIP_SAMPLES)
def test_jellyfin_to_plex_to_jellyfin_is_idempotent(preader, jwriter, jreader, pwriter, plex_name):
    # Use the Plex sample to compute the canonical Jellyfin form, then
    # round-trip from there. Avoids hand-writing intermediate Jellyfin forms
    # whose canonicality we'd have to guess.
    jellyfin_start = _plex_to_jelly(preader, jwriter, plex_name)
    plex_intermediate = _jelly_to_plex(jreader, pwriter, jellyfin_start)
    jellyfin_again = _plex_to_jelly(preader, jwriter, plex_intermediate)
    assert jellyfin_again == jellyfin_start, (
        f"Round trip changed the filename:\n"
        f"  Jellyfin (in):  {jellyfin_start}\n"
        f"  Plex:           {plex_intermediate}\n"
        f"  Jellyfin (out): {jellyfin_again}"
    )
