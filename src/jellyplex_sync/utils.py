from __future__ import annotations

import logging
import os
import pathlib
import shutil

log = logging.getLogger(__name__)


def remove(item: pathlib.Path) -> None:
    if item.is_file() or item.is_symlink():
        item.unlink()
    elif item.is_dir():
        shutil.rmtree(item)
    else:
        log.warning("Will not remove '%s'", item)


def common_path(p1: pathlib.Path, p2: pathlib.Path) -> pathlib.Path | None:
    try:
        return pathlib.Path(os.path.commonpath([p1.resolve(), p2.resolve()]))
    except ValueError:
        return None
