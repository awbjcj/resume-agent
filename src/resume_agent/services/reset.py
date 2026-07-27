"""Workspace reset use case: truncate workspace rows, then clear derived files."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlmodel import SQLModel, Session

from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.workspace import WorkspacePaths
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    Notification,
    ResumeVersion,
    SkillSuggestion,
)


class ResetScope(StrEnum):
    jobs = "jobs"
    profile = "profile"
    all = "all"


_PIPELINE_TABLES: tuple[type[SQLModel], ...] = (
    Notification,
    Application,
    CoverLetter,
    ResumeVersion,
    SkillSuggestion,
    Job,
)
_PROFILE_TABLES: tuple[type[SQLModel], ...] = (SkillSuggestion,)
_PROFILE_DIRECTORIES = ("fragments",)
# The source manifest and its documents are user-owned intake, not derived
# profile output. Account-level resets preserve both; users remove/reset sources
# through the dedicated source controls where that destructive intent is explicit.
_PROFILE_FILES = ("facts.json", "matrix.json", "cluster_map.json")


@dataclass(frozen=True)
class ResetPaths:
    output_dir: Path
    runs_dir: Path
    progress_dir: Path
    profile_dir: Path
    taxonomy_file: Path
    scraper_recipes_dir: Path
    workday_facets_dir: Path
    connector_runs_file: Path

    @classmethod
    def from_workspace(cls, workspace: WorkspacePaths) -> ResetPaths:
        return cls(
            output_dir=workspace.output_dir,
            runs_dir=workspace.runs_root,
            progress_dir=workspace.root / "progress",
            profile_dir=workspace.profile_dir,
            taxonomy_file=workspace.root / "taxonomy" / "skill_groups.json",
            scraper_recipes_dir=workspace.scraper_recipes_dir,
            workday_facets_dir=workspace.workday_facets_dir,
            connector_runs_file=workspace.root / "connector_runs.json",
        )

    @classmethod
    def legacy(
        cls,
        *,
        data_dir: Path | str = Path("data"),
        output_dir: Path | str = Path("output"),
        runs_dir: Path | str | None = None,
    ) -> ResetPaths:
        data_root = Path(data_dir)
        return cls(
            output_dir=Path(output_dir),
            runs_dir=Path(runs_dir) if runs_dir is not None else data_root / "runs",
            progress_dir=data_root / "progress",
            profile_dir=data_root / "profile",
            taxonomy_file=data_root / "taxonomy" / "skill_groups.json",
            scraper_recipes_dir=data_root / "scraper_recipes",
            workday_facets_dir=data_root / "workday_facets",
            connector_runs_file=data_root / "connector_runs.json",
        )

    @classmethod
    def resolve(cls) -> ResetPaths:
        """Resolve CLI paths from the active tenant or legacy flat layout."""
        context = current_context()
        return cls.from_workspace(context.paths) if context else cls.legacy()


@dataclass
class ResetReport:
    scope: ResetScope
    rows_deleted: dict[str, int] = field(default_factory=dict)
    areas_cleared: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _ResetTarget:
    area: str
    path: Path
    is_directory: bool


def scope_tables(scope: ResetScope) -> tuple[type[SQLModel], ...]:
    return _PROFILE_TABLES if scope is ResetScope.profile else _PIPELINE_TABLES


def _scope_targets(paths: ResetPaths, scope: ResetScope) -> tuple[_ResetTarget, ...]:
    jobs = (
        _ResetTarget("output", paths.output_dir, True),
        _ResetTarget("runs", paths.runs_dir, True),
        _ResetTarget("progress", paths.progress_dir, True),
        _ResetTarget("connector_runs", paths.connector_runs_file, False),
    )
    profile = (
        *(
            _ResetTarget("profile", paths.profile_dir / name, True)
            for name in _PROFILE_DIRECTORIES
        ),
        *(
            _ResetTarget("profile", paths.profile_dir / name, False)
            for name in _PROFILE_FILES
        ),
        _ResetTarget("taxonomy", paths.taxonomy_file, False),
    )
    caches = (
        _ResetTarget("scraper_recipes", paths.scraper_recipes_dir, True),
        _ResetTarget("workday_facets", paths.workday_facets_dir, True),
    )
    if scope is ResetScope.jobs:
        return jobs
    if scope is ResetScope.profile:
        return profile
    return jobs + profile + caches


def scope_areas(paths: ResetPaths, scope: ResetScope) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target.area for target in _scope_targets(paths, scope)))


def scope_paths(paths: ResetPaths, scope: ResetScope) -> tuple[Path, ...]:
    return tuple(target.path for target in _scope_targets(paths, scope))


def count_rows(session: Session, scope: ResetScope) -> dict[str, int]:
    return {
        str(model.__tablename__): session.execute(
            select(func.count()).select_from(model)
        ).scalar_one()
        for model in scope_tables(scope)
    }


def reset_workspace(
    session: Session, paths: ResetPaths, scope: ResetScope
) -> ResetReport:
    try:
        rows_deleted = count_rows(session, scope)
        for model in scope_tables(scope):
            session.execute(delete(model))
        session.commit()
    except BaseException:
        session.rollback()
        raise

    report = ResetReport(scope=scope, rows_deleted=rows_deleted)
    area_success: dict[str, bool] = {}
    for target in _scope_targets(paths, scope):
        succeeded = (
            _clear_directory(target.path, report.failures)
            if target.is_directory
            else _remove_file(target.path, report.failures)
        )
        area_success[target.area] = area_success.get(target.area, True) and succeeded
    report.areas_cleared = [
        area for area in scope_areas(paths, scope) if area_success.get(area, False)
    ]
    return report


def _remove_file(target: Path, failures: dict[str, str]) -> bool:
    try:
        target.unlink(missing_ok=True)
    except OSError as error:
        failures[str(target)] = str(error)
        return False
    return True


def _clear_directory(directory: Path, failures: dict[str, str]) -> bool:
    """Clear and recreate a directory without following directory symlinks."""
    succeeded = True
    try:
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            directory.unlink()
        elif directory.exists():
            try:
                children = tuple(directory.iterdir())
            except OSError as error:
                failures[str(directory)] = str(error)
                return False
            for child in children:
                try:
                    if child.is_symlink() or not child.is_dir():
                        child.unlink()
                    else:
                        shutil.rmtree(child)
                except OSError as error:
                    failures[str(child)] = str(error)
                    succeeded = False
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        failures[str(directory)] = str(error)
        return False
    return succeeded
