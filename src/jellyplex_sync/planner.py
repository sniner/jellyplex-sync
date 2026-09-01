"""The Planner: orchestrates discover → interpret → name → disambiguate.

The Planner is a pure function (modulo Reader I/O for `parse_movie` /
`parse_video`): it reads the source tree, produces an immutable Plan,
and never touches the target filesystem. The `Realizer` (next module)
is the only layer that turns a Plan into actions on disk.

This separation is what makes the new pipeline auditable: the same
Plan can be inspected (`plan` subcommand), compared against an existing
target (`compare`), or executed (`realize`).
"""

from __future__ import annotations

import logging
import pathlib
from collections import defaultdict
from dataclasses import dataclass

from .disambig import (
    DisambiguationResult,
    Disambiguator,
    HashFallbackDisambiguator,
)
from .discover import DiscoveredGroup, SourceDiscoverer, TwoLevelDiscoverer
from .library import (
    CollectingReporter,
    Drop,
    FolderClash,
    IgnoredEntry,
    LibraryReader,
    LibraryWriter,
    LoggingReporter,
    MovieClash,
    Reporter,
)
from .model import MovieInfo
from .plan import Plan, PlannedAsset, PlannedFile, PlannedMovie

log = logging.getLogger(__name__)


@dataclass
class _Candidate:
    source_path: pathlib.Path
    movie: MovieInfo
    group: DiscoveredGroup
    folder_drops: tuple[Drop, ...] = ()


class Planner:
    """Builds a Plan from a Reader/Writer pair and (optionally) a custom
    Discoverer or Disambiguator. Calling `plan()` twice with the same
    inputs produces equal Plans — the property that makes plans
    diffable across runs and cacheable across phases.

    Translation losses are recorded in the Plan itself (`folder_drops`
    per movie, `drops` per video). The `reporter` additionally receives
    every recorded Drop as planning progresses — exactly once each, in
    plan order — so LoggingReporter keeps narrating and StrictReporter
    keeps aborting on the first loss."""

    def __init__(
        self,
        reader: LibraryReader,
        writer: LibraryWriter,
        *,
        discoverer: SourceDiscoverer | None = None,
        disambiguator: Disambiguator | None = None,
        reporter: Reporter | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._discoverer = discoverer or TwoLevelDiscoverer()
        self._disambiguator = disambiguator or HashFallbackDisambiguator()
        self._reporter = reporter or LoggingReporter()

    def plan(self) -> Plan:
        source_root = self._reader.base_dir
        target_root = self._writer.base_dir
        if source_root == target_root:
            raise ValueError("Cannot plan a library into itself")

        ignored: list[IgnoredEntry] = []
        clashes: list[MovieClash] = []

        candidates_by_target = self._group_candidates(source_root, ignored)
        planned_movies: list[PlannedMovie] = []
        folder_clashes: list[FolderClash] = []
        protected_folders: list[str] = []

        for target_name, items in candidates_by_target.items():
            if len(items) > 1:
                folder_clashes.append(
                    FolderClash(
                        target_folder_name=target_name,
                        source_folder_names=tuple(c.source_path.name for c in items),
                    )
                )
                protected_folders.append(target_name)
                continue
            (candidate,) = items
            pm, movie_clashes = self._build_planned_movie(
                candidate, target_root / target_name
            )
            clashes.extend(movie_clashes)
            if pm is not None:
                planned_movies.append(pm)
                self._replay_drops(pm)
            else:
                # The movie was skipped wholesale; an existing target
                # folder of that name belongs to it, not to the strays.
                protected_folders.append(target_name)

        return Plan(
            source_root=source_root,
            target_root=target_root,
            source_format=self._reader.shortname(),
            target_format=self._writer.shortname(),
            movies=tuple(planned_movies),
            ignored=tuple(ignored),
            clashes=tuple(clashes),
            folder_clashes=tuple(folder_clashes),
            protected_folders=tuple(protected_folders),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _group_candidates(
        self,
        source_root: pathlib.Path,
        ignored: list[IgnoredEntry],
    ) -> dict[str, list[_Candidate]]:
        """Run discovery + parse_movie, group surviving candidates by the
        target folder name the Writer would produce. Candidates whose
        folder name doesn't parse are added to `ignored`."""
        grouped: dict[str, list[_Candidate]] = defaultdict(list)
        for group in self._discoverer.discover(source_root, ignored=ignored):
            movie = self._reader.parse_movie(group.source_path)
            if movie is None:
                ignored.append(
                    IgnoredEntry(group.source_path, "unparseable folder name")
                )
                continue
            collector = CollectingReporter()
            target_name = self._writer.movie_name(movie, collector)
            grouped[target_name].append(
                _Candidate(
                    source_path=group.source_path,
                    movie=movie,
                    group=group,
                    folder_drops=tuple(collector.drops),
                )
            )
        return grouped

    def _build_planned_movie(
        self,
        candidate: _Candidate,
        target_folder: pathlib.Path,
    ) -> tuple[PlannedMovie | None, list[MovieClash]]:
        videos_info = [
            (self._reader.parse_video(p), p) for p in candidate.group.video_files
        ]

        if videos_info:
            dis_result = self._disambiguator.disambiguate(
                candidate.movie,
                videos_info,
                self._writer,
                movie_folder=candidate.source_path.name,
            )
        else:
            dis_result = DisambiguationResult(names={}, notes={})

        planned_videos = tuple(
            PlannedFile(
                source=source,
                target_name=dis_result.names[source],
                drops=dis_result.drops.get(source, ()),
                disambiguation=dis_result.notes[source],
            )
            for _, source in videos_info
            if source in dis_result.names
        )

        planned_loose = tuple(
            PlannedFile(source=p, target_name=p.name)
            for p in candidate.group.loose_files
        )

        planned_assets = tuple(
            self._build_planned_asset(p) for p in candidate.group.asset_dirs
        )

        # All-clashes corner case: every video in this folder ended up
        # unresolved, and there's nothing else to sync. Returning None
        # keeps the empty movie out of the Plan; the clashes are still
        # reported via Plan.clashes by the caller.
        if (
            videos_info
            and not planned_videos
            and not planned_loose
            and not planned_assets
        ):
            return None, list(dis_result.unresolved)

        pm = PlannedMovie(
            source_path=candidate.source_path,
            target_folder=target_folder,
            movie=candidate.movie,
            videos=planned_videos,
            loose_files=planned_loose,
            assets=planned_assets,
            folder_drops=candidate.folder_drops,
            protected_files=tuple(c.target_filename for c in dis_result.unresolved),
        )
        return pm, list(dis_result.unresolved)

    def _replay_drops(self, pm: PlannedMovie) -> None:
        """Forward the drops recorded on one PlannedMovie to the
        reporter — the reporter sees exactly what the Plan records."""
        for drop in pm.folder_drops:
            self._reporter.drop(drop)
        for pf in pm.videos:
            for drop in pf.drops:
                self._reporter.drop(drop)

    def _build_planned_asset(self, asset_dir: pathlib.Path) -> PlannedAsset:
        files: list[PlannedFile] = []
        subfolders: list[PlannedAsset] = []
        for child in sorted(asset_dir.glob("*")):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                subfolders.append(self._build_planned_asset(child))
            elif child.is_file():
                files.append(PlannedFile(source=child, target_name=child.name))
        return PlannedAsset(
            source=asset_dir,
            folder_name=asset_dir.name,
            files=tuple(files),
            subfolders=tuple(subfolders),
        )
