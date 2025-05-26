import logging
import pathlib
import shutil
from typing import Optional


log = logging.getLogger(__name__)


def remove(item: pathlib.Path) -> None:
    if item.is_file() or item.is_symlink():
        item.unlink()
    elif item.is_dir():
        shutil.rmtree(item)
    else:
        log.warning("Will not remove '%s'", item)


def common_path(p1: pathlib.Path, p2: pathlib.Path) -> Optional[pathlib.Path]:
    parts1 = p1.resolve().parts
    parts2 = p2.resolve().parts
    common = []
    for a, b in zip(parts1, parts2):
        if a == b:
            common.append(a)
        else:
            break
    return pathlib.Path(*common) if common else None
