from pathlib import Path
import pytest

import jellyplex as jp

@pytest.fixture
def plib() -> jp.MediaLibrary:
    return jp.PlexLibrary(Path("."))


SANE_SAMPLES = [
    (
        Path("First movie.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
            providers=None,
        )
    ),
    (
        Path("First movie (1970).mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
            providers=None,
        )
    ),
    (
        Path("First movie (1970) {imdb-tt123456}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
            providers={"imdb-tt123456"},
        )
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
            providers={"imdb-tt654321"},
        )
    ),
    (
        # Hyphen in title string
        Path("Series - A movie (1984) {imdb-tt654321}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
            providers={"imdb-tt654321"},
        )
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321} {edition-Director's Cut}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution=None,
            tags=None,
            providers={"imdb-tt654321"},
        )
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321} {edition-Director's Cut} [DVD].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution=None,
            tags={"DVD",},
            providers={"imdb-tt654321"},
        )
    ),
    (
        Path("Series – A movie (1984) {imdbid-tt654321} {edition-Director's Cut} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
            providers=None,
        )
    ),
    (
        Path("Series – A movie (1984) {imdbid-tt654321}{edition-Director's Cut}[1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
            providers=None,
        )
    ),
    (
        Path("First movie (1970) {imdb-tt123456} [1080p][remux].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution="1080p",
            tags={"remux",},
            providers={"imdb-tt123456"},
        )
    ),
    (
        Path("First movie (1970) {tmdb-54186} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution="1080p",
            tags=None,
            providers={"tmdb-54186"},
        )
    ),
    (
        # Case sensitivity check
        Path("First movie (1970) {IMDB-tt123456} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution="1080p",
            tags=None,
            providers={"imdb-tt123456"},
        )
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # Tags all over the place
        Path("First movie (1970) [remux] {imdb-tt123456} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution="1080p",
            tags={"remux",},
            providers={"imdb-tt123456"},
        )
    ),
    (
        # No spaces
        Path("First movie(1970)[remux]{imdb-tt123456}[1080p]{edition-Director's Cut}[hello world].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags={"remux","hello world"},
            providers={"imdb-tt123456"},
        )
    ),
    (
        # Empty edition string
        Path("First movie (1970) {edition-}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
]

NOT_WORKING_SAMPLES = [
    (
        # Tags all over the place (would Plex accept this?)
        Path("First movie [hello] (1970) [remux] {imdb-tt123456} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution="1080p",
            tags={"hello", "remux"},
            providers={"imdb-tt123456"},
        )
    ),
    (
        # Unknown metadata provider
        Path("First movie (1970) {youtube-y12345678}.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path(""),
        jp.VideoInfo(
            extension="",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path(".mkv"),
        jp.VideoInfo(
            extension="",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
]

@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_plex_video_path(plib: jp.MediaLibrary, path, expected):
    result = plib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES])
def test_parse_not_recommended_plex_video_path(plib: jp.MediaLibrary, path, expected):
    result = plib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES])
def test_parse_bad_plex_video_path(plib: jp.MediaLibrary, path, expected):
    result = plib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"
