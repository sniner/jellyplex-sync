from pathlib import Path
import pytest

import jellyplex as jp

@pytest.fixture
def jlib() -> jp.MediaLibrary:
    return jp.JellyfinLibrary(Path("."))


SANE_SAMPLES = [
    (
        Path("First movie.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path("First movie (1970).mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path("First movie (1970) [imdbid-tt123456].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321] - Director's Cut.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution=None,
            tags=None,
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321] - DVD Director's Cut.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution=None,
            tags={"DVD",},
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321] - BD Director's Cut.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
        )
    ),
    (
        Path("Series – A movie (1984) [imdbid-tt654321] - 1080p Director's Cut.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
        )
    ),
]

NOT_RECOMMENDED_SAMPLES = [
    (
        # <space><hypen><space> in front of metadata block
        Path("Series – A movie (1984) - [imdbid-tt654321].mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition=None,
            resolution=None,
            tags=None,
        )
    ),
    (
        # Multiple <space><hypen><space> sequences
        Path("Series - A movie (1984) - [imdbid-tt654321] - Director's Cut.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution=None,
            tags=None,
        )
    ),
    (
        # Resolution ('BD') at the end of variant/edition string
        Path("A movie (1984) [imdbid-tt654321] - Director's Cut BD.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
        )
    ),
    (
        # Resolution ('1080p') at the end of variant/edition string
        Path("A movie (1984) [imdbid-tt654321] - Director's Cut 1080p.mkv"),
        jp.VideoInfo(
            extension=".mkv",
            edition="Director's Cut",
            resolution="1080p",
            tags=None,
        )
    ),
]

NOT_WORKING_SAMPLES = [
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
def test_parse_sane_jellyfin_video_path(jlib: jp.MediaLibrary, path, expected):
    result = jlib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_RECOMMENDED_SAMPLES, ids=[str(p) for p, _ in NOT_RECOMMENDED_SAMPLES])
def test_parse_not_recommended_jellyfin_video_path(jlib, path, expected):
    result = jlib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"

@pytest.mark.parametrize("path,expected", NOT_WORKING_SAMPLES, ids=[str(p) for p, _ in NOT_WORKING_SAMPLES])
def test_parse_bad_jellyfin_video_path(jlib, path, expected):
    result = jlib.parse_video_path(path)
    assert result == expected, f"Failed on path: {path}"
