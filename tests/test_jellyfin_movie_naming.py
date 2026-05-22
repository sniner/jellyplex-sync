from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def jlib() -> jp.JellyfinLibraryReader:
    return jp.JellyfinLibraryReader(Path("."))


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
        Path("First movie (1970) [imdbid-tt123456]"),
        jp.MovieInfo(title="First movie", year="1970", attributes={"imdb": "tt123456"}),
    ),
    (
        Path("First movie [imdbid-tt123456]"),
        jp.MovieInfo(title="First movie", attributes={"imdb": "tt123456"}),
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321]"),
        jp.MovieInfo(title="Series – A movie", year="1984", attributes={"imdb": "tt654321"}),
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # Hyphen in title string
        Path("Series - A movie (1984)"),
        jp.MovieInfo(title="Series - A movie", year="1984"),
    ),
    (
        # Hyphen in title string (with metadata id)
        Path("Series - A movie (1984) - [imdbid-tt654321]"),
        jp.MovieInfo(title="Series - A movie", year="1984", attributes={"imdb": "tt654321"}),
    ),
]

NOT_WORKING_SAMPLES = [
    (
        # Underlines instead of spaces
        Path("New_movie_(1998)"),
        jp.MovieInfo(title="New_movie_(1998)"),
    ),
    (
        # Missing spaces — new parser extracts the provider id and recovers the year
        # (the old parser left the whole thing in the title)
        Path("New movie (1998)-[imdbid-tt654321]"),
        jp.MovieInfo(title="New movie", year="1998", attributes={"imdb": "tt654321"}),
    ),
    (
        # Fields mixed up
        Path("New movie [imdbid-tt654321] (1998)"),
        jp.MovieInfo(title="New movie", year="1998", attributes={"imdb": "tt654321"}),
    ),
    (
        # Unrecognized metadata provider — bracket isn't a known provider id, the
        # trailing " - [...]" gets stripped as if it were a variant suffix. Title and
        # year still get recovered (an improvement over the previous parser, which
        # left the entire string as the title).
        Path("New movie (1998) - [youtube-y12345678]"),
        jp.MovieInfo(title="New movie", year="1998"),
    ),
    (Path(""), None),
]


@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES]
)
def test_parse_not_recommended_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES]
)
def test_parse_bad_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie(path)
    assert result == expected, f"Failed on path: {path}"
