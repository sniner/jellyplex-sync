import errno
import logging
import pathlib
import shutil
from typing import Optional


log = logging.getLogger(__name__)


def remove(item: pathlib.Path) -> bool:
    """Remove a file, symlink, or directory.

    Returns True on success, False on failure.
    Handles permission errors and missing files gracefully.
    """
    try:
        if item.is_symlink():
            # Handle symlinks before is_file() since is_file() follows symlinks
            item.unlink()
        elif item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
        else:
            log.warning("Will not remove '%s' (unknown type)", item)
            return False
        return True
    except OSError as e:
        if e.errno == errno.ENOENT:
            # Already removed, consider it a success
            return True
        elif e.errno == errno.EACCES:
            log.error("Permission denied removing '%s'", item)
        elif e.errno == errno.EBUSY:
            log.error("Device or resource busy: '%s'", item)
        else:
            log.error("Failed to remove '%s': %s", item, e)
        return False


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
