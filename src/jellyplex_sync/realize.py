"""The Realizer: turns a Plan into actions on the target filesystem.

This is the only layer in the 0.3 pipeline that observes `dry_run`.
Every other layer computes; the Realizer acts (or doesn't, under
dry-run). Centralising the I/O side-channel here is what made the
`dry_run` plumbing collapse from seven functions to one.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field

from . import utils
from .library import FileEvent
from .materializer import FileMaterializer, HardlinkMaterializer
from .plan import Plan, PlannedAsset, PlannedFile, PlannedMovie

log = logging.getLogger(__name__)


@dataclass
class RealizeStats:
    """Aggregate counters and events from one Realizer.apply() call.
    Mirrors the shape of the old LibraryStats / MovieStats / AssetStats
    triple — one flat dataclass instead of three nested ones, because
    the Plan already carries the movie/asset structure."""

    movies_processed: int = 0
    files_linked: int = 0
    files_removed: int = 0
    ignored_count: int = 0
    strays_in_target: list[str] = field(default_factory=list)
    events: list[FileEvent] = field(default_factory=list)


class Realizer:
    def __init__(self, materializer: FileMaterializer | None = None) -> None:
        self._materializer = materializer or HardlinkMaterializer()

    def apply(
        self,
        plan: Plan,
        *,
        dry_run: bool = False,
        delete: bool = False,
        verbose: bool = False,
        stats: RealizeStats | None = None,
    ) -> RealizeStats:
        if not plan.target_root.is_dir():
            raise ValueError(
                f"Target directory '{plan.target_root}' does not exist"
            )

        stats = stats or RealizeStats()
        stats.ignored_count = len(plan.ignored)

        for movie in plan.movies:
            self._realize_movie(
                movie,
                dry_run=dry_run,
                delete=delete,
                verbose=verbose,
                stats=stats,
            )
            stats.movies_processed += 1

        # Library-level strays: anything in target_root that isn't a planned
        # movie folder. Done after all movies so the planned folders exist
        # (matters when we want to confirm "this WOULD be a stray" in
        # dry-run output without the planned folder masking it).
        planned_folder_names = {m.target_folder.name for m in plan.movies}
        for entry in sorted(plan.target_root.iterdir()):
            if entry.name in planned_folder_names:
                continue
            stats.strays_in_target.append(entry.name)
            if delete:
                self._remove_entry(
                    entry,
                    dry_run=dry_run,
                    context="library_stray",
                    stats=stats,
                )

        return stats

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _realize_movie(
        self,
        movie: PlannedMovie,
        *,
        dry_run: bool,
        delete: bool,
        verbose: bool,
        stats: RealizeStats,
    ) -> None:
        self._ensure_dir(movie.target_folder, dry_run=dry_run)

        if verbose:
            log.info(
                "Processing '%s' → '%s'",
                movie.source_path.name,
                movie.target_folder.name,
            )

        for pf in movie.videos:
            self._materialize_file(pf, movie.target_folder, dry_run, verbose, stats)
        for pf in movie.loose_files:
            self._materialize_file(pf, movie.target_folder, dry_run, verbose, stats)

        if delete and movie.target_folder.is_dir():
            keep = (
                {f.target_name for f in movie.videos}
                | {f.target_name for f in movie.loose_files}
                | {a.folder_name for a in movie.assets}
            )
            for entry in sorted(movie.target_folder.iterdir()):
                if entry.name in keep:
                    continue
                self._remove_entry(
                    entry,
                    dry_run=dry_run,
                    context="movie_stray",
                    stats=stats,
                )

        for asset in movie.assets:
            self._realize_asset(
                asset,
                movie.target_folder / asset.folder_name,
                dry_run=dry_run,
                delete=delete,
                verbose=verbose,
                stats=stats,
            )

    def _realize_asset(
        self,
        asset: PlannedAsset,
        target_path: pathlib.Path,
        *,
        dry_run: bool,
        delete: bool,
        verbose: bool,
        stats: RealizeStats,
    ) -> None:
        self._ensure_dir(target_path, dry_run=dry_run)

        for pf in asset.files:
            self._materialize_file(pf, target_path, dry_run, verbose, stats)

        if delete and target_path.is_dir():
            keep = (
                {f.target_name for f in asset.files}
                | {sf.folder_name for sf in asset.subfolders}
            )
            for entry in sorted(target_path.iterdir()):
                if entry.name in keep:
                    continue
                self._remove_entry(
                    entry,
                    dry_run=dry_run,
                    context="asset_stray",
                    stats=stats,
                )

        for subfolder in asset.subfolders:
            self._realize_asset(
                subfolder,
                target_path / subfolder.folder_name,
                dry_run=dry_run,
                delete=delete,
                verbose=verbose,
                stats=stats,
            )

    def _materialize_file(
        self,
        pf: PlannedFile,
        parent: pathlib.Path,
        dry_run: bool,
        verbose: bool,
        stats: RealizeStats,
    ) -> None:
        dst = parent / pf.target_name
        if self._materializer.materialize(
            pf.source,
            dst,
            dry_run=dry_run,
            verbose=verbose,
            events=stats.events,
        ):
            stats.files_linked += 1

    def _ensure_dir(self, path: pathlib.Path, *, dry_run: bool) -> None:
        if path.exists():
            return
        if dry_run:
            log.info("MKDIR  %s", path)
        else:
            path.mkdir(parents=True, exist_ok=True)

    def _remove_entry(
        self,
        entry: pathlib.Path,
        *,
        dry_run: bool,
        context: str,
        stats: RealizeStats,
    ) -> None:
        if dry_run:
            log.info("DELETE %s", entry)
        else:
            log.info("Removing stray item '%s'", entry.name)
        result = utils.remove(entry, dry_run=dry_run)
        stats.files_removed += result.files
        stats.events.append(
            FileEvent(action="remove", target=entry, context=context)
        )
