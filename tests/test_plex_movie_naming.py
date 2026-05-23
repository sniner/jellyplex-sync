from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def plib() -> jp.PlexLibraryReader:
    return jp.PlexLibraryReader(Path("."))


SANE_SAMPLES = [
    (
        Path("First movie"),
        jp.MovieInfo(title="First movie"),
    ),
    (
        Path("First movie (1970)"),
        jp.MovieInfo(title="First movie", year="1970"),
    ),
    (
        Path("First movie (1970) {imdb-tt123456}"),
        jp.MovieInfo(title="First movie", year="1970", attributes={"imdb": "tt123456"}),
    ),
    (
        Path("First movie {imdb-tt123456}"),
        jp.MovieInfo(title="First movie", attributes={"imdb": "tt123456"}),
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321}"),
        jp.MovieInfo(title="Series – A movie", year="1984", attributes={"imdb": "tt654321"}),
    ),
    (
        # Hyphen in title string
        Path("Series - A movie (1984)"),
        jp.MovieInfo(title="Series - A movie", year="1984"),
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # Labels in movie folder name (unsure if Plex would accept this)
        Path("First movie {imdb-tt123456} [label1][label2]"),
        jp.MovieInfo(title="First movie", attributes={"imdb": "tt123456"}),
    ),
]

NOT_WORKING_SAMPLES = [
    (
        # Underlines instead of spaces
        Path("New_movie_(1998)"),
        jp.MovieInfo(title="New_movie_(1998)"),
    ),
    (
        # Missing spaces
        Path("New movie(1998){imdb-tt654321}"),
        jp.MovieInfo(title="New movie(1998)", attributes={"imdb": "tt654321"}),
    ),
    (
        # Jellyfin syntax (but still valid Plex syntax)
        Path("New movie (1998) [imdbid-tt654321]"),
        jp.MovieInfo(title="New movie", year="1998"),
    ),
    (
        # Fields are mixed up (don't think Plex will grok this)
        Path("New movie {imdb-tt654321} (1998)"),
        jp.MovieInfo(title="New movie", year="1998", attributes={"imdb": "tt654321"}),
    ),
    (
        # Unrecognized metadata provider
        Path("New movie (1998) {youtube-y12345678}"),
        jp.MovieInfo(title="New movie", year="1998"),
    ),
    (Path(""), None),
]


@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_plex_movie_path(plib, path, expected):
    result = plib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES]
)
def test_parse_not_recommended_plex_movie_path(plib, path, expected):
    result = plib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES]
)
def test_parse_bad_plex_movie_path(plib, path, expected):
    result = plib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"
