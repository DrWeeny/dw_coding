"""
dw_project - Pipeline-agnostic project registry for dw_coding.

Provides a simple way to define and query a project structure:
    project name / episode (optional) / sequence / shot name

Folder layout (mirrored across shots, assets, images)::

    {project_root}/
        shots/{sequence}/{shot_name}/
        assets/{sequence}/{shot_name}/
        images/{sequence}/{shot_name}/

Assets, even though they may have a slightly different final structure,
follow the same hierarchy as shots so every entity can be looked up the
same way.

Usage::

    from dw_utils.dw_project import ProjectRegistry, Project

    # Register a project
    proj = Project(
        name="my_show",
        root=r"D:/projects/my_show",
        sequence="sq010",
        shot_name="sh0010",
        episode="ep01",          # optional – only for TV shows
    )
    ProjectRegistry.set(proj)

    # Anywhere else in the code base
    proj = ProjectRegistry.get()
    print(proj.shot_path)        # D:/projects/my_show/shots/sq010/sh0010
    print(proj.asset_path)       # D:/projects/my_show/assets/sq010/sh0010
    print(proj.image_path)       # D:/projects/my_show/images/sq010/sh0010

    # Quick mockup for UI / unit-test work
    from dw_utils.dw_project import create_mock_project
    mock = create_mock_project()  # temp dir with folders already on disk
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


# ---------------------------------------------------------------------------
# Project data
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """Immutable description of the current working context.

    Args:
        name:       Human-readable project name (e.g. ``"my_show"``).
        root:       Absolute path to the project root on disk.
        sequence:   Sequence identifier (e.g. ``"sq010"``).
        shot_name:  Shot identifier (e.g. ``"sh0010"``).
        episode:    Episode identifier — **optional**, only for TV shows.
    """

    name: str
    root: str
    sequence: str
    shot_name: str
    episode: Optional[str] = None

    # The three top-level categories that mirror each other.
    CATEGORIES: list = field(default_factory=lambda: ["shots", "assets", "images"],
                             repr=False)

    # ------------------------------------------------------------------
    # Derived paths
    # ------------------------------------------------------------------

    @property
    def _episode_segment(self) -> str:
        """Return the episode path segment or empty string."""
        return self.episode if self.episode else ""

    def _category_path(self, category: str) -> Path:
        """Build ``{root}/{category}/[{episode}/]{sequence}/{shot_name}``."""
        parts = [self.root, category]
        if self._episode_segment:
            parts.append(self._episode_segment)
        parts += [self.sequence, self.shot_name]
        return Path(*parts)

    @property
    def shot_path(self) -> Path:
        return self._category_path("shots")

    @property
    def asset_path(self) -> Path:
        return self._category_path("assets")

    @property
    def image_path(self) -> Path:
        return self._category_path("images")

    def all_paths(self) -> List[Path]:
        """Return every mirrored category path."""
        return [self._category_path(c) for c in self.CATEGORIES]

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def task_key(self) -> str:
        """A flat string suitable for dict keys / subscription scopes.

        Format: ``"{episode}_{sequence}_{shot_name}"`` (episode omitted when
        ``None``).
        """
        parts = [p for p in (self.episode, self.sequence, self.shot_name) if p]
        return "_".join(parts)

    def create_folders(self) -> List[Path]:
        """Create all category directories on disk (``exist_ok=True``)."""
        created = []
        for p in self.all_paths():
            p.mkdir(parents=True, exist_ok=True)
            created.append(p)
        return created

    def exists(self) -> bool:
        """Return ``True`` when the project root exists on disk."""
        return Path(self.root).is_dir()

    def summary(self) -> str:
        lines = [
            f"Project : {self.name}",
            f"Root    : {self.root}",
        ]
        if self.episode:
            lines.append(f"Episode : {self.episode}")
        lines += [
            f"Sequence: {self.sequence}",
            f"Shot    : {self.shot_name}",
            f"Shots   : {self.shot_path}",
            f"Assets  : {self.asset_path}",
            f"Images  : {self.image_path}",
        ]
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.summary()


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

class ProjectRegistry:
    """Global accessor for the *current* project context.

    Call :meth:`set` once at startup and :meth:`get` everywhere else.
    """

    _current: Optional[Project] = None

    @classmethod
    def set(cls, project: Project) -> None:
        cls._current = project

    @classmethod
    def get(cls) -> Optional[Project]:
        return cls._current

    @classmethod
    def clear(cls) -> None:
        cls._current = None

    @classmethod
    def is_set(cls) -> bool:
        return cls._current is not None


# ---------------------------------------------------------------------------
# Mock / placeholder helpers
# ---------------------------------------------------------------------------

_MOCK_SHOTS = [
    # (episode, sequence, shot_name)
    ("ep01", "sq010", "sh0010"),
    ("ep01", "sq010", "sh0020"),
    ("ep01", "sq020", "sh0010"),
    ("ep02", "sq010", "sh0010"),
]

_MOCK_ASSETS = [
    # Assets follow the same structure but live under "assets/"
    (None, "characters", "hero_main"),
    (None, "characters", "hero_sidekick"),
    (None, "props", "sword_01"),
    (None, "environments", "castle_ext"),
]


def create_mock_project(
    name: str = "mockup_project",
    root: Optional[str] = None,
    create_on_disk: bool = True,
    include_assets: bool = True,
) -> List[Project]:
    """Create a set of placeholder :class:`Project` entries for testing.

    When *create_on_disk* is ``True`` (default) every folder is created inside
    a temporary directory so widgets relying on ``os.listdir`` will work.

    Args:
        name:            Project name used for all entries.
        root:            Explicit root directory. When ``None`` a temp dir is
                         used.
        create_on_disk:  Whether to ``mkdir`` the folder tree.
        include_assets:  Whether to include asset entries alongside shots.

    Returns:
        list[Project]: One ``Project`` per shot (and optionally per asset).
        The **first** entry is also registered via :class:`ProjectRegistry`.
    """
    if root is None:
        root = os.path.join(tempfile.mkdtemp(prefix="dw_mock_"), name)

    projects: List[Project] = []

    for ep, seq, shot in _MOCK_SHOTS:
        p = Project(name=name, root=root, episode=ep, sequence=seq, shot_name=shot)
        if create_on_disk:
            p.create_folders()
        projects.append(p)

    if include_assets:
        for ep, seq, shot in _MOCK_ASSETS:
            p = Project(name=name, root=root, episode=ep, sequence=seq, shot_name=shot)
            if create_on_disk:
                p.create_folders()
            projects.append(p)

    # Register the first shot as the "active" context
    if projects:
        ProjectRegistry.set(projects[0])

    return projects


# ---------------------------------------------------------------------------
# CLI quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Creating mock project ===\n")
    entries = create_mock_project()

    for i, p in enumerate(entries):
        tag = " (active)" if i == 0 else ""
        print(f"--- Entry {i}{tag} ---")
        print(p)
        print()

    print(f"Registry -> {ProjectRegistry.get().task_key}")
