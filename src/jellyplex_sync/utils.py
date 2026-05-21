from __future__ import annotations

import logging
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
