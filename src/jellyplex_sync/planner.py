"""The Planner: orchestrates discover → interpret → name → disambiguate.

The Planner is a pure function (modulo Reader I/O for `parse_movie` /
`parse_video`): it reads the source tree, produces an immutable Plan,
and never writes to the target filesystem. It reads the target only to
find ignore markers. The `Realizer` (next module) is the only layer
that turns a Plan into actions on disk.

This separation is what makes the new pipeline auditable: the same
Plan can be inspected (`plan` subcommand), compared against an existing
target (`compare`), or executed (`realize`).
"""

from __future__ import annotations

import logging
import pathlib
from collections import defaultdict
from collections.abc import Collection
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
    find_marked,
    is_marked,
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

        locked = self._locked_plan(source_root, target_root)
        if locked is not None:
            return locked

        ignored: list[IgnoredEntry] = []
        clashes: list[MovieClash] = []
        marked_src: list[pathlib.Path] = []

        candidates_by_target = self._group_candidates(source_root, ignored, marked_src)
        marked_tgt = self._marked_in_target(target_root, candidates_by_target.keys())
        marked_movie_folders = {p for p in marked_tgt if p.parent == target_root}
        planned_movies: list[PlannedMovie] = []
        folder_clashes: list[FolderClash] = []
        protected_folders: list[str] = []

        for target_name, items in candidates_by_target.items():
            if target_root / target_name in marked_movie_folders:
                continue
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
                candidate,
                target_root / target_name,
                marked_src,
                marked_tgt,
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
            marked_in_source=tuple(sorted(marked_src)),
            marked_in_target=tuple(sorted(marked_tgt)),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _locked_plan(self, source_root: pathlib.Path, target_root: pathlib.Path) -> Plan | None:
        """An empty Plan if either library root is marked, else None.
        Checked before anything is scanned: a marked source root must not
        read as an empty library, or --delete would clear the target."""
        source_marked = is_marked(source_root)
        target_marked = is_marked(target_root)
        if not (source_marked or target_marked):
            return None
        return Plan(
            source_root=source_root,
            target_root=target_root,
            source_format=self._reader.shortname(),
            target_format=self._writer.shortname(),
            marked_in_source=(source_root,) if source_marked else (),
            marked_in_target=(target_root,) if target_marked else (),
        )

    def _marked_in_target(
        self,
        target_root: pathlib.Path,
        mapped: Collection[str],
    ) -> list[pathlib.Path]:
        """Marked directories at the library level of the target. A folder
        some source movie maps to counts only if it is marked itself;
        inside it, the planned asset folders are checked while they are
        built, and the Realizer checks the rest before removing anything.
        In a folder no source movie maps to, a marker at any depth counts,
        so that the folder is not reported as a stray."""
        if not target_root.is_dir():
            return []
        found: list[pathlib.Path] = []
        for entry in sorted(target_root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in mapped:
                if is_marked(entry):
                    found.append(entry)
            else:
                found.extend(find_marked(entry))
        return found

    def _group_candidates(
        self,
        source_root: pathlib.Path,
        ignored: list[IgnoredEntry],
        marked: list[pathlib.Path],
    ) -> dict[str, list[_Candidate]]:
        """Run discovery + parse_movie, group surviving candidates by the
        target folder name the Writer would produce. Candidates whose
        folder name doesn't parse are added to `ignored`."""
        grouped: dict[str, list[_Candidate]] = defaultdict(list)
        for group in self._discoverer.discover(source_root, ignored=ignored, marked=marked):
            # A discoverer that parsed names to find group boundaries
            # ships the identity with the group; only folder-based
            # discovery leaves the parsing to us.
            movie = (
                group.movie
                if group.movie is not None
                else self._reader.parse_movie(group.source_path)
            )
            if movie is None:
                ignored.append(IgnoredEntry(group.source_path, "unparseable folder name"))
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
        marked_src: list[pathlib.Path],
        marked_tgt: list[pathlib.Path],
    ) -> tuple[PlannedMovie | None, list[MovieClash]]:
        videos_info = [(self._reader.parse_video(p), p) for p in candidate.group.video_files]

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
            PlannedFile(source=p, target_name=p.name) for p in candidate.group.loose_files
        )

        planned_assets: list[PlannedAsset] = []
        for p in candidate.group.asset_dirs:
            asset = self._build_planned_asset(p, target_folder / p.name, marked_src, marked_tgt)
            if asset is not None:
                planned_assets.append(asset)

        # All-clashes corner case: every video in this folder ended up
        # unresolved, and there's nothing else to sync. Returning None
        # keeps the empty movie out of the Plan; the clashes are still
        # reported via Plan.clashes by the caller.
        if videos_info and not planned_videos and not planned_loose and not planned_assets:
            return None, list(dis_result.unresolved)

        pm = PlannedMovie(
            source_path=candidate.source_path,
            target_folder=target_folder,
            movie=candidate.movie,
            videos=planned_videos,
            loose_files=planned_loose,
            assets=tuple(planned_assets),
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

    def _build_planned_asset(
        self,
        asset_dir: pathlib.Path,
        target_dir: pathlib.Path,
        marked_src: list[pathlib.Path],
        marked_tgt: list[pathlib.Path],
    ) -> PlannedAsset | None:
        """Plan one source asset folder into `target_dir`, recursively.
        None if `target_dir` is marked: nothing gets written into it.
        Marked source subfolders are left out and recorded."""
        if is_marked(target_dir):
            marked_tgt.append(target_dir)
            return None
        files: list[PlannedFile] = []
        subfolders: list[PlannedAsset] = []
        for child in sorted(asset_dir.glob("*")):
            if child.name.startswith("."):
                continue
            if child.is_dir() and is_marked(child):
                marked_src.append(child)
            elif child.is_dir():
                sub = self._build_planned_asset(
                    child,
                    target_dir / child.name,
                    marked_src,
                    marked_tgt,
                )
                if sub is not None:
                    subfolders.append(sub)
            elif child.is_file():
                files.append(PlannedFile(source=child, target_name=child.name))
        return PlannedAsset(
            source=asset_dir,
            folder_name=asset_dir.name,
            files=tuple(files),
            subfolders=tuple(subfolders),
        )
