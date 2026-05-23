from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def jwriter() -> jp.JellyfinLibraryWriter:
    return jp.JellyfinLibraryWriter(Path("./Jellyfin"))


@pytest.fixture
def preader() -> jp.PlexLibraryReader:
    return jp.PlexLibraryReader(Path("./Plex"))


SAMPLES_FULL_PATH = [
    (
        "/First movie (1984)/First movie (1984).mkv",
        "/First movie (1984)/First movie (1984).mkv",
    ),
    (
        "/A Bridge Too Far (1977) {imdb-tt0075784}/A Bridge Too Far (1977) {imdb-tt0075784}.mkv",
        "/A Bridge Too Far (1977) [imdbid-tt0075784]/A Bridge Too Far (1977) [imdbid-tt0075784].mkv",
    ),
    (
        "/Das Boot (1981) {imdb-tt0082096}/Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut}.mkv",
        "/Das Boot (1981) [imdbid-tt0082096]/Das Boot (1981) [imdbid-tt0082096] - Director's Cut.mkv",
    ),
    (
        "/Das Boot (1981) {imdb-tt0082096}/Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut}.mkv",
        "/Das Boot (1981) [imdbid-tt0082096]/Das Boot (1981) [imdbid-tt0082096] - Theatrical Cut.mkv",
    ),
]

# Only filenames to keep the samples smaller
SAMPLES_FILENAME = [
    (
        "First movie.mkv",
        "First movie.mkv",
    ),
    (
        "First movie (1984).mkv",
        "First movie (1984).mkv",
    ),
    (
        "A Bridge Too Far (1977) {imdb-tt0075784}.mkv",
        "A Bridge Too Far (1977) [imdbid-tt0075784].mkv",
    ),
    (
        "A Bridge Too Far {imdb-tt0075784}.mkv",
        "A Bridge Too Far [imdbid-tt0075784].mkv",
    ),
    (
        "Das Boot (1981) {imdb-tt0082096} {edition-Director's Cut}.mkv",
        "Das Boot (1981) [imdbid-tt0082096] - Director's Cut.mkv",
    ),
    (
        "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [2160p].mkv",
        "Das Boot (1981) [imdbid-tt0082096] - 4k Theatrical Cut.mkv",
    ),
    (
        "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [1080p].mkv",
        "Das Boot (1981) [imdbid-tt0082096] - BD Theatrical Cut.mkv",
    ),
    (
        "Das Boot (1981) {imdb-tt0082096} {edition-Theatrical Cut} [DVD].mkv",
        "Das Boot (1981) [imdbid-tt0082096] - DVD Theatrical Cut.mkv",
    ),
    (
        "Das Boot (1981) {imdb-tt0082096}[1080p]{edition-Theatrical Cut}.mkv",
        "Das Boot (1981) [imdbid-tt0082096] - BD Theatrical Cut.mkv",
    ),
    (
        "First movie (1984) [1080p] {edition-Yeah}.mkv",
        "First movie (1984) - BD Yeah.mkv",
    ),
    # The samples below show lossy conversions because Jellyfin does not support free [bracket] labels
    (
        "First movie (1984) {imdb-tt123456}{edition-Director's Cut}[remux][1080p].mkv",
        "First movie (1984) [imdbid-tt123456] - BD Director's Cut.mkv",
    ),
    (
        "First movie (1984) [hello world] {imdb-tt123456}[DVD][remux].mkv",
        "First movie (1984) [imdbid-tt123456] - DVD.mkv",
    ),
    (
        "First movie (1984) {youtube-y12345678} [1080p].mkv",
        "First movie (1984) - BD.mkv",
    ),
    (
        "First movie (1984) {fancy-stuff} {hello world} [1080p].mkv",
        "First movie (1984) - BD.mkv",
    ),
    # Off-standard resolution labels (e.g. NTSC film transfers at non-standard
    # frame sizes) pass through verbatim instead of being dropped. Better a
    # slightly off label than silent data loss.
    (
        "Queimada (1969) {imdb-tt0064866} [570i].mkv",
        "Queimada (1969) [imdbid-tt0064866] - 570i.mkv",
    ),
    (
        "Custom Source (2024) [1440p].mkv",
        "Custom Source (2024) - 1440p.mkv",
    ),
]


@pytest.mark.parametrize(
    "path,expected", SAMPLES_FULL_PATH, ids=[str(p) for p, _ in SAMPLES_FULL_PATH]
)
def test_plex_to_jellyfin_full(
    jwriter: jp.JellyfinLibraryWriter, preader: jp.PlexLibraryReader, path, expected
):
    source_path = Path(preader.base_dir, path)

    movie = preader.parse_movie(source_path.parent)
    assert movie is not None

    video = preader.parse_video(source_path)
    assert video is not None

    target_movie = jwriter.movie_name(movie)
    target_video = jwriter.video_name(movie, video)
    target_path = Path("/", target_movie, target_video)

    assert str(target_path) == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", SAMPLES_FILENAME, ids=[str(p) for p, _ in SAMPLES_FILENAME]
)
def test_plex_to_jellyfin_short(
    jwriter: jp.JellyfinLibraryWriter, preader: jp.PlexLibraryReader, path, expected
):
    source_path = Path(preader.base_dir, path)

    # Cheap trick: Fake a movie path
    movie = preader.parse_movie(Path(preader.base_dir, source_path.stem))
    assert movie is not None

    video = preader.parse_video(source_path)
    assert video is not None

    target_movie = jwriter.movie_name(movie)
    target_video = jwriter.video_name(movie, video)
    target_path = Path("/", target_movie, target_video)

    assert target_path.name == expected, f"Failed on path: {path}"
