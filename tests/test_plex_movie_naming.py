from pathlib import Path
import pytest

import jellyplex as jp

@pytest.fixture
def plib() -> jp.MediaLibrary:
    return jp.PlexLibrary(Path("."))


SANE_SAMPLES = [
    (
        Path("First movie"),
        jp.MovieInfo(
            title="First movie",
            provider=None,
            movie_id=None,
            year=None,
        )
    ),
    (
        Path("First movie (1970)"),
        jp.MovieInfo(
            title="First movie",
            provider=None,
            movie_id=None,
            year="1970",
        )
    ),
    (
        Path("First movie (1970) {imdb-tt123456}"),
        jp.MovieInfo(
            title="First movie",
            provider="imdb",
            movie_id="tt123456",
            year="1970",
        )
    ),
    (
        Path("First movie {imdb-tt123456}"),
        jp.MovieInfo(
            title="First movie",
            provider="imdb",
            movie_id="tt123456",
            year=None,
        )
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321}"),
        jp.MovieInfo(
            title="Series – A movie",
            provider="imdb",
            movie_id="tt654321",
            year="1984",
        )
    ),
    (
        # Hyphen in title string
        Path("Series - A movie (1984)"),
        jp.MovieInfo(
            title="Series - A movie",
            provider=None,
            movie_id=None,
            year="1984",
        )
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # Tags in movie folder name (unsure if Plex would accept this)
        Path("First movie {imdb-tt123456} [tag1][tag2]"),
        jp.MovieInfo(
            title="First movie",
            provider="imdb",
            movie_id="tt123456",
            year=None,
        )
    ),
]

NOT_WORKING_SAMPLES = [
    (
        # Underlines instead of spaces
        Path("New_movie_(1998)"),
        jp.MovieInfo(
            title="New_movie_(1998)",
            provider=None,
            movie_id=None,
            year=None,
        )
    ),
    (
        # Missing spaces
        Path("New movie(1998){imdb-tt654321}"),
        jp.MovieInfo(
            title="New movie(1998)",
            provider="imdb",
            movie_id="tt654321",
            year=None,
        )
    ),
    (
        # Jellyfin syntax (but still valid Plex syntax)
        Path("New movie (1998) [imdbid-tt654321]"),
        jp.MovieInfo(
            title="New movie",
            provider=None,
            movie_id=None,
            year="1998",
        )
    ),
    (
        # Fields are mixed up (don't think Plex will grok this)
        Path("New movie {imdb-tt654321} (1998)"),
        jp.MovieInfo(
            title="New movie",
            provider="imdb",
            movie_id="tt654321",
            year="1998",
        )
    ),
    (
        # Unrecognized metadata provider
        Path("New movie (1998) {youtube-y12345678}"),
        jp.MovieInfo(
            title="New movie",
            provider=None,
            movie_id=None,
            year="1998",
        )
    ),
    (Path(""), None),
]

@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_plex_movie_path(plib, path, expected):
    result = plib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES])
def test_parse_not_recommended_plex_movie_path(plib, path, expected):
    result = plib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES])
def test_parse_bad_plex_movie_path(plib, path, expected):
    result = plib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"
