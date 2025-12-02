from pathlib import Path
import pytest
import jellyplex as jp
from jellyplex.library import MovieInfo, VideoInfo

@pytest.fixture
def plib() -> jp.PlexLibrary:
    return jp.PlexLibrary(Path("."))

def test_video_name_deduplication_and_sorting(plib: jp.PlexLibrary):
    # 1. Different provider tag than movie folder
    movie = MovieInfo(title="Movie", year="2020", provider="imdb", movie_id="tt67890")
    video = VideoInfo(extension=".mkv", providers={"tmdb-12345"})

    name = plib.video_name(movie, video)
    assert "{imdb-tt67890}" in name
    assert "{tmdb-12345}" in name
    assert name == "Movie (2020) {imdb-tt67890} {tmdb-12345}.mkv"

def test_video_name_multiple_tags_sorted(plib: jp.PlexLibrary):
    # 2. Multiple provider tags in video
    movie = MovieInfo(title="Movie", year="2020", provider=None, movie_id=None)
    video = VideoInfo(extension=".mkv", providers={"imdb-tt123", "tmdb-456"})

    name = plib.video_name(movie, video)
    # Check order: imdb-tt123 comes before tmdb-456
    idx_imdb = name.find("{imdb-tt123}")
    idx_tmdb = name.find("{tmdb-456}")
    assert idx_imdb < idx_tmdb
    assert name == "Movie (2020) {imdb-tt123} {tmdb-456}.mkv"

def test_video_name_duplicate_tag(plib: jp.PlexLibrary):
    # 3. Duplicate tag (should be deduplicated)
    movie = MovieInfo(title="Movie", year="2020", provider="tmdb", movie_id="12345")
    video = VideoInfo(extension=".mkv", providers={"tmdb-12345"})

    name = plib.video_name(movie, video)
    # Should appear only once (part of movie name)
    # Movie name: "Movie (2020) {tmdb-12345}"
    # Video name shouldn't append it again.
    assert name.count("{tmdb-12345}") == 1
    assert name == "Movie (2020) {tmdb-12345}.mkv"
