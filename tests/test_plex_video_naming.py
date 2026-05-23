from pathlib import Path

import pytest

import jellyplex_sync as jp


@pytest.fixture
def plib() -> jp.PlexLibraryReader:
    return jp.PlexLibraryReader(Path("."))


SANE_SAMPLES = [
    (
        Path("First movie.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        Path("First movie (1970).mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        Path("First movie (1970) {imdb-tt123456}.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321}.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        # Hyphen in title string
        Path("Series - A movie (1984) {imdb-tt654321}.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321} {edition-Director's Cut}.mkv"),
        jp.VideoInfo(extension=".mkv", attributes={"edition": "Director's Cut"}),
    ),
    (
        Path("Series – A movie (1984) {imdb-tt654321} {edition-Director's Cut} [DVD].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            attributes={"edition": "Director's Cut"},
            labels=("DVD",),
        ),
    ),
    (
        Path("Series – A movie (1984) {imdbid-tt654321} {edition-Director's Cut} [1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            attributes={"edition": "Director's Cut"},
            labels=("1080p",),
        ),
    ),
    (
        Path("Series – A movie (1984) {imdbid-tt654321}{edition-Director's Cut}[1080p].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            attributes={"edition": "Director's Cut"},
            labels=("1080p",),
        ),
    ),
    (
        Path("First movie (1970) {imdb-tt123456} [1080p][remux].mkv"),
        jp.VideoInfo(extension=".mkv", labels=("1080p", "remux")),
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # Labels all over the place
        Path("First movie (1970) [remux] {imdb-tt123456} [1080p].mkv"),
        jp.VideoInfo(extension=".mkv", labels=("remux", "1080p")),
    ),
    (
        # No spaces
        Path(
            "First movie(1970)[remux]{imdb-tt123456}[1080p]{edition-Director's Cut}[hello world].mkv"
        ),
        jp.VideoInfo(
            extension=".mkv",
            attributes={"edition": "Director's Cut"},
            labels=("remux", "1080p", "hello world"),
        ),
    ),
    (
        # Empty edition string is ignored (regex requires at least one non-`}` char in value)
        Path("First movie (1970) {edition-}.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
]

NOT_WORKING_SAMPLES = [
    (
        # Labels all over the place (would Plex accept this?)
        Path("First movie [hello] (1970) [remux] {imdb-tt123456} [1080p].mkv"),
        jp.VideoInfo(extension=".mkv", labels=("hello", "remux", "1080p")),
    ),
    (
        # Unknown metadata provider — ignored at video level (only `edition` is captured)
        Path("First movie (1970) {youtube-y12345678}.mkv"),
        jp.VideoInfo(extension=".mkv"),
    ),
    (
        Path(""),
        jp.VideoInfo(extension=""),
    ),
    (
        Path(".mkv"),
        jp.VideoInfo(extension=""),
    ),
]


@pytest.mark.parametrize("path,expected", SANE_SAMPLES, ids=[str(p) for p, _ in SANE_SAMPLES])
def test_parse_sane_plex_video_path(plib: jp.PlexLibraryReader, path, expected):
    result = plib.parse_video(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES]
)
def test_parse_not_recommended_plex_video_path(plib, path, expected):
    result = plib.parse_video(path)
    assert result == expected, f"Failed on path: {path}"


@pytest.mark.parametrize(
    "path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES]
)
def test_parse_bad_plex_video_path(plib, path, expected):
    result = plib.parse_video(path)
    assert result == expected, f"Failed on path: {path}"
