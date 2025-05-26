from pathlib import Path
import pytest

import jellyplex as jp

@pytest.fixture
def jlib() -> jp.MediaLibrary:
    return jp.JellyfinLibrary(Path("."))


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
        Path("First movie (1970) [imdbid-tt123456]"),
        jp.MovieInfo(
            title="First movie",
            provider="imdb",
            movie_id="tt123456",
            year="1970",
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321]"),
        jp.MovieInfo(
            title="Series – A movie",
            provider="imdb",
            movie_id="tt654321",
            year="1984",
        )
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        Path("Series - A movie (1984)"),
        jp.MovieInfo(
            title="Series - A movie",
            provider=None,
            movie_id=None,
            year="1984",
        )
    ),
    (
        Path("Series - A movie (1984) - [imdbid-tt654321]"),
        jp.MovieInfo(
            title="Series - A movie",
            provider="imdb",
            movie_id="tt654321",
            year="1984",
        )
    ),
]

BAD_SAMPLES = [
    (
        Path("New_movie_(1998)"),
        jp.MovieInfo(
            title="New_movie_(1998)",
            provider=None,
            movie_id=None,
            year=None,
        )
    ),
    (
        Path("New movie (1998)-[imdbid-tt654321]"),
        jp.MovieInfo(
            title="New movie (1998)-[imdbid-tt654321]",
            provider=None,
            movie_id=None,
            year=None,
        )
    ),
    (
        Path("New movie (1998)-[youtube-y12345678]"),
        jp.MovieInfo(
            title="New movie (1998)-[youtube-y12345678]",
            provider=None,
            movie_id=None,
            year=None,
        )
    ),
    (Path(""), None),
]

@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES])
def test_parse_not_recommended_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", BAD_SAMPLES, ids=[str(p) for p, _ in BAD_SAMPLES])
def test_parse_bad_jellyfin_movie_path(jlib, path, expected):
    result = jlib.parse_movie_path(path)
    assert result == expected, f"Failed on path: {path}"
