from pathlib import Path
import pytest

from jellyplex_sync import utils

def test_absolute_common_path():
    root = Path("/")

    assert utils.common_path(
        Path("/mnt/media/movies/First movie/"),
        Path("/mnt/media/movies/Second movie/"),
    ) == Path("/mnt/media/movies/")

    assert utils.common_path(
        Path("/mnt/media/movies/First movie/"),
        Path("/mnt/media/music/"),
    ) == Path("/mnt/media/")

    assert utils.common_path(
        Path("/mnt/media/movies/"),
        Path("/usr/local/bin/"),
    ) == root

def test_relative_common_path():
    root = Path.cwd()

    assert utils.common_path(
        Path("./media/movies/First movie/"),
        Path("./media/movies/Second movie/"),
    ) == Path(root, "media/movies")

    assert utils.common_path(
        Path("./media/movies/"),
        Path("./music/"),
    ) == root
