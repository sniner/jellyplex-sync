from __future__ import annotations

import logging
import os
import pathlib
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RemovalCounts:
    files: int = 0
    dirs: int = 0
    ignored: int = 0
    errors: int = 0


def _count_removable(item: pathlib.Path) -> RemovalCounts:
    """Predict what `remove(item)` would do. No side effects — used for
    dry-run reporting so the summary matches what an actual run produces."""
    counts = RemovalCounts()
    if item.is_symlink() or item.is_file():
        counts.files += 1
    elif item.is_dir():
        for root, dirs, files in os.walk(item, topdown=False):
            counts.files += len(files)
            root_path = pathlib.Path(root)
            for name in dirs:
                if (root_path / name).is_symlink():
                    counts.files += 1
                else:
                    counts.dirs += 1
        counts.dirs += 1
    else:
        counts.ignored += 1
    return counts


def _remove(item: pathlib.Path) -> RemovalCounts:
    """Recursively remove a file, symlink, or directory tree.

    Per-entry failures (permission denied, busy file, …) are logged and
    counted in `errors`; the walk continues so a single un-removable
    entry doesn't strand the rest of the sync.
    """
    counts = RemovalCounts()
    if item.is_symlink() or item.is_file():
        try:
            item.unlink()
            counts.files += 1
        except OSError as exc:
            log.warning("Failed to remove '%s': %s", item, exc)
            counts.errors += 1
    elif item.is_dir():
        for root, dirs, files in os.walk(item, topdown=False):
            root_path = pathlib.Path(root)
            for name in files:
                p = root_path / name
                try:
                    p.unlink()
                    counts.files += 1
                except OSError as exc:
                    log.warning("Failed to remove '%s': %s", p, exc)
                    counts.errors += 1
            for name in dirs:
                p = root_path / name
                try:
                    if p.is_symlink():
                        # os.walk lists dir-symlinks under `dirs`; rmdir would fail.
                        p.unlink()
                        counts.files += 1
                    else:
                        p.rmdir()
                        counts.dirs += 1
                except OSError as exc:
                    log.warning("Failed to remove '%s': %s", p, exc)
                    counts.errors += 1
        try:
            item.rmdir()
            counts.dirs += 1
        except OSError as exc:
            log.warning("Failed to remove '%s': %s", item, exc)
            counts.errors += 1
    else:
        log.warning("Will not remove '%s'", item)
        counts.ignored += 1
    return counts


def remove(item: pathlib.Path, *, dry_run: bool = False) -> RemovalCounts:
    if bool(dry_run):
        return _count_removable(item)
    return _remove(item)
