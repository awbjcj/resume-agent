# Workspace Data Reset Implementation Plan

> **Execution mode:** Implement this plan in-line with test-driven development.
> Do not delegate tasks to subagents. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Let a user clear their workspace data in three tiers — `jobs` (pipeline), `profile` (corpus), `all` (both + caches) — from the web UI, the API, and the CLI.

**Architecture:** One service function (`services/reset.py`) truncates the six workspace DB tables through the live engine and clears derived directories; a thin API endpoint, CLI command, and Account-page card call it. No engine eviction, no DB-file deletion (Windows lock-safe, works in single- and multi-user modes).

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy, Typer, React + TanStack Query + Vitest, openapi-typescript contract.

**Spec:** `docs/superpowers/specs/2026-07-13-data-reset-design.md`

## Global Constraints

- Implementation tests are offline: no API key or external network. Final
  verification also includes a local-browser walkthrough.
- `ruff check` must pass on all touched Python files.
- Wire format is camelCase via `CamelModel` (`api/schemas/base.py`); Python stays snake_case.
- `config/` and `secrets.env` are NEVER touched by any reset scope.
- Confirmation literals: API query param `confirm=RESET`; web dialog typed word `RESET`; CLI typed word = the scope value (`jobs`/`profile`/`all`).
- Never delete `resume_agent.db` or its WAL/SHM sidecars — truncate tables only.
- DB deletes commit in ONE transaction BEFORE any file removal; file-phase errors are collected into `ResetReport.failures`, never raised.
- After Task 2, regenerate the OpenAPI contract (`bash scripts/gen_ts_client.sh`);
  commit `contracts/openapi.json`, `contracts/ts/api.ts`, and
  `web/src/lib/api/schema.ts` together. `tests/api/test_openapi_contract.py` is
  the drift gate. On Windows, use the repository's direct PowerShell generation
  flow if the bash wrapper fails on CRLF `pipefail`.

## Correctness Amendments (authoritative over snippets below)

The initial plan was audited against the current runtime on 2026-07-14. Apply
these corrections wherever an older code snippet conflicts:

1. **Callers provide concrete paths.** `ResetPaths.resolve()` may be used by
   the CLI, but the API must not rely on cwd-relative resolution. Multi-user API
   requests derive paths from the active `WorkspacePaths`; single-user requests
   derive them from `app.state.data_dir`, `app.state.run_manager.root`, and the
   legacy `output/` root. Add a single-user configured-path regression test.
2. **Use the current profile layout.** Clear `documents/`, `fragments/`,
   `sources.json`, `facts.json`, `matrix.json`, and `cluster_map.json`. Do not
   invent or recreate an unused `profile/sources/` directory. Preserve
   `overrides.yaml` and unlisted profile children.
3. **Make the file-phase contract true.** Catch failures from inspection,
   unlinking, recursive removal, and directory recreation. Never follow a
   directory-root symlink; unlink it and recreate the intended empty directory.
   Add tests for root symlinks and recreation/inspection failures.
4. **Make rollback explicit.** If delete or commit fails, call
   `session.rollback()`, re-raise, and do not touch files. Add a regression test.
5. **Report exact outcomes.** Include `connector_runs` and `taxonomy` as
   explicit reset areas. `areasCleared` contains only areas whose file
   operations fully succeeded; `failures` contains exact path-to-reason entries.
   CLI preview lists every directory and file target, not only broad labels.
6. **Keep the generated SPA schema in sync.** Contract regeneration modifies
   three committed files, including `web/src/lib/api/schema.ts`.
7. **Use the installed Base UI/shadcn conventions.** Compose the scope picker
   and confirmation field from existing primitives (`ToggleGroup` or the
   installed choice control, `FieldSet`/`Field`, `AlertDialog`, `Card`). Use
   semantic tokens and existing variants rather than raw radio markup and
   one-off styling.
8. **Strengthen the destructive UX tests.** Test the POST method/query/body,
   clean reload behavior, partial-failure no-reload behavior, and confirmation
   reset when scope changes or the dialog is dismissed. Put the "Export backup
   first" action inside the confirmation dialog as promised by the design.
9. **Finish with the real repository gate.** In addition to Python tests, Ruff,
   and Vitest, run OpenAPI drift, web lint, web build, `git diff --check`, and a
   local Playwright/browser walkthrough of the reset flow.

---

### Task 1: Reset service (`services/reset.py`)

**Files:**
- Create: `src/resume_agent/services/reset.py`
- Test: `tests/test_reset_service.py`

**Interfaces:**
- Consumes: `resume_agent.tracking.tables` models (`Job`, `ResumeVersion`, `Application`, `CoverLetter`, `Notification`, `SkillSuggestion`); `resume_agent.tenancy.paths.resolve_tenant_path`.
- Produces (used by Tasks 2 and 3):
  - `class ResetScope(str, Enum)` with values `jobs`, `profile`, `all`
  - `@dataclass(frozen=True) ResetPaths` with fields `output_dir, runs_dir, progress_dir, profile_dir, taxonomy_file, scraper_recipes_dir, workday_facets_dir, connector_runs_file` (all `Path`) and classmethod `ResetPaths.resolve() -> ResetPaths`
  - `@dataclass ResetReport` with `scope: ResetScope`, `rows_deleted: dict[str, int]`, `areas_cleared: list[str]`, `failures: dict[str, str]`
  - `reset_workspace(session, paths: ResetPaths, scope: ResetScope) -> ResetReport`
  - `count_rows(session, scope: ResetScope) -> dict[str, int]`
  - `scope_areas(scope: ResetScope) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reset_service.py`:

```python
import pytest
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.services import reset as reset_module
from resume_agent.services.reset import ResetPaths, ResetScope, reset_workspace
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    Notification,
    ResumeVersion,
    SkillSuggestion,
)


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def paths(tmp_path):
    root = tmp_path / "workspace"
    built = ResetPaths(
        output_dir=root / "output",
        runs_dir=root / "runs",
        progress_dir=root / "progress",
        profile_dir=root / "profile",
        taxonomy_file=root / "taxonomy" / "skill_groups.json",
        scraper_recipes_dir=root / "scraper_recipes",
        workday_facets_dir=root / "workday_facets",
        connector_runs_file=root / "connector_runs.json",
    )
    for directory in (
        built.output_dir,
        built.runs_dir,
        built.progress_dir,
        built.profile_dir / "sources",
        built.profile_dir / "fragments",
        built.profile_dir / "documents",
        built.scraper_recipes_dir,
        built.workday_facets_dir,
        built.taxonomy_file.parent,
    ):
        directory.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    (root / "secrets.env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    return built


def _seed_pipeline(session: Session) -> None:
    job = Job(source="manual", company="Acme", title="Engineer", dedup_key="acme|engineer")
    session.add(job)
    session.commit()
    assert job.id is not None
    version = ResumeVersion(job_id=job.id)
    session.add(version)
    session.commit()
    assert version.id is not None
    letter = CoverLetter(job_id=job.id, resume_version_id=version.id)
    session.add(letter)
    session.commit()
    assert letter.id is not None
    application = Application(
        job_id=job.id, resume_version_id=version.id, cover_letter_id=letter.id
    )
    session.add(application)
    session.commit()
    assert application.id is not None
    session.add(
        Notification(
            application_id=application.id,
            kind="status",
            proposed_status="interview",
            evidence="e",
            message_id="m1",
        )
    )
    session.add(SkillSuggestion(kind="cluster", key="python"))
    session.commit()


def _seed_files(paths: ResetPaths) -> None:
    (paths.output_dir / "acme").mkdir()
    (paths.output_dir / "acme" / "resume.pdf").write_bytes(b"%PDF")
    (paths.runs_dir / "run.json").write_text("{}", encoding="utf-8")
    (paths.progress_dir / "pull.json").write_text("{}", encoding="utf-8")
    paths.connector_runs_file.write_text("{}", encoding="utf-8")
    (paths.profile_dir / "facts.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "cluster_map.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "overrides.yaml").write_text("ban: []\n", encoding="utf-8")
    (paths.profile_dir / "sources" / "resume.pdf").write_bytes(b"%PDF")
    (paths.profile_dir / "fragments" / "resume.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "documents" / "manifest.json").write_text("[]", encoding="utf-8")
    paths.taxonomy_file.write_text("{}", encoding="utf-8")
    (paths.scraper_recipes_dir / "recipe.json").write_text("{}", encoding="utf-8")
    (paths.workday_facets_dir / "acme-ext.json").write_text("{}", encoding="utf-8")


def test_jobs_scope_truncates_pipeline_and_clears_output(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)
    report = reset_workspace(session, paths, ResetScope.jobs)
    assert report.rows_deleted == {
        "notifications": 1,
        "applications": 1,
        "cover_letters": 1,
        "resume_versions": 1,
        "skill_suggestions": 1,
        "jobs": 1,
    }
    assert report.areas_cleared == ["output", "runs", "progress"]
    assert report.failures == {}
    assert session.exec(select(Job)).first() is None
    assert list(paths.output_dir.iterdir()) == []
    assert list(paths.runs_dir.iterdir()) == []
    assert not paths.connector_runs_file.exists()
    assert (paths.profile_dir / "facts.json").exists()  # profile untouched
    assert paths.taxonomy_file.exists()


def test_profile_scope_clears_corpus_and_derived_rows_only(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)
    report = reset_workspace(session, paths, ResetScope.profile)
    assert report.rows_deleted == {"skill_suggestions": 1}
    assert report.areas_cleared == ["profile"]
    assert session.exec(select(Job)).first() is not None  # pipeline survives
    assert session.exec(select(Application)).first() is not None
    assert session.exec(select(Notification)).first() is not None
    assert not (paths.profile_dir / "facts.json").exists()
    assert not (paths.profile_dir / "cluster_map.json").exists()
    assert (paths.profile_dir / "overrides.yaml").exists()  # hand-authored: kept
    assert paths.connector_runs_file.exists()  # pipeline telemetry: kept
    assert not paths.taxonomy_file.exists()
    for name in ("sources", "fragments", "documents"):
        sub = paths.profile_dir / name
        assert sub.is_dir() and list(sub.iterdir()) == []
    assert (paths.output_dir / "acme" / "resume.pdf").exists()


def test_all_scope_clears_everything_but_config_and_secrets(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)
    report = reset_workspace(session, paths, ResetScope.all)
    assert sum(report.rows_deleted.values()) == 6
    assert set(report.areas_cleared) == {
        "output",
        "runs",
        "progress",
        "profile",
        "scraper_recipes",
        "workday_facets",
    }
    root = paths.output_dir.parent
    assert (root / "config" / "search.yaml").read_text(encoding="utf-8") == "titles: []\n"
    assert (root / "secrets.env").exists()
    assert (paths.profile_dir / "overrides.yaml").exists()
    assert list(paths.scraper_recipes_dir.iterdir()) == []
    assert list(paths.workday_facets_dir.iterdir()) == []


def test_second_run_is_a_no_op(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)
    reset_workspace(session, paths, ResetScope.all)
    report = reset_workspace(session, paths, ResetScope.all)
    assert sum(report.rows_deleted.values()) == 0
    assert report.failures == {}


def test_file_failure_is_reported_not_raised(session, paths, monkeypatch):
    _seed_pipeline(session)
    _seed_files(paths)

    def explode(_path):
        raise OSError("locked by another process")

    monkeypatch.setattr(reset_module.shutil, "rmtree", explode)
    report = reset_workspace(session, paths, ResetScope.jobs)
    assert str(paths.output_dir / "acme") in report.failures
    assert session.exec(select(Job)).first() is None  # DB phase still committed


def test_missing_directories_are_recreated_empty(session, tmp_path):
    root = tmp_path / "fresh"
    built = ResetPaths(
        output_dir=root / "output",
        runs_dir=root / "runs",
        progress_dir=root / "progress",
        profile_dir=root / "profile",
        taxonomy_file=root / "taxonomy" / "skill_groups.json",
        scraper_recipes_dir=root / "scraper_recipes",
        workday_facets_dir=root / "workday_facets",
        connector_runs_file=root / "connector_runs.json",
    )
    report = reset_workspace(session, built, ResetScope.all)
    assert report.failures == {}
    assert built.output_dir.is_dir()
    assert (built.profile_dir / "sources").is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reset_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.services.reset'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/services/reset.py`:

```python
"""Workspace reset use-case: truncate pipeline tables + clear derived files.

Scopes (spec: docs/superpowers/specs/2026-07-13-data-reset-design.md):
- jobs:    all six workspace tables + output/, runs/, progress/, connector_runs.json
- profile: profile corpus files + derived notification/suggestion rows
- all:     both + scraper_recipes/, workday_facets/
config/, secrets.env, and profile/overrides.yaml are never touched; the
profile clear is an enumerated delete, so unlisted files survive. DB deletes
commit first; file failures are collected on the report (never raised) so a
re-run finishes the cleanup.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from resume_agent.tenancy.paths import resolve_tenant_path
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    Notification,
    ResumeVersion,
    SkillSuggestion,
)


class ResetScope(str, Enum):
    jobs = "jobs"
    profile = "profile"
    all = "all"


# Children-first: notifications reference applications; applications reference
# resume_versions and cover_letters; cover_letters reference resume_versions;
# resume_versions reference jobs. SkillSuggestion is standalone.
_PIPELINE_TABLES = (
    Notification,
    Application,
    CoverLetter,
    ResumeVersion,
    SkillSuggestion,
    Job,
)
# Match-gap advice derived from the profile; stale after a profile wipe.
# Notification is NOT here: notifications hang off applications (pipeline data).
_PROFILE_TABLES = (SkillSuggestion,)

_PROFILE_SUBDIRS = ("sources", "fragments", "documents")
# Enumerated delete: overrides.yaml (hand-authored corrections) and any
# unlisted future file survive a profile reset by default.
_PROFILE_FILES = ("facts.json", "matrix.json", "sources.json", "cluster_map.json")


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
    def resolve(cls) -> "ResetPaths":
        """Resolve against the active tenancy context (or the legacy flat layout)."""
        return cls(
            output_dir=resolve_tenant_path("output"),
            runs_dir=resolve_tenant_path("data/runs"),
            progress_dir=resolve_tenant_path("data/progress"),
            profile_dir=resolve_tenant_path("data/profile"),
            taxonomy_file=resolve_tenant_path("data/taxonomy/skill_groups.json"),
            scraper_recipes_dir=resolve_tenant_path("data/scraper_recipes"),
            workday_facets_dir=resolve_tenant_path("data/workday_facets"),
            connector_runs_file=resolve_tenant_path("data/connector_runs.json"),
        )


@dataclass
class ResetReport:
    scope: ResetScope
    rows_deleted: dict[str, int] = field(default_factory=dict)
    areas_cleared: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


def scope_tables(scope: ResetScope) -> tuple[type, ...]:
    return _PROFILE_TABLES if scope is ResetScope.profile else _PIPELINE_TABLES


def scope_areas(scope: ResetScope) -> tuple[str, ...]:
    if scope is ResetScope.jobs:
        return ("output", "runs", "progress")
    if scope is ResetScope.profile:
        return ("profile",)
    return ("output", "runs", "progress", "profile", "scraper_recipes", "workday_facets")


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
    report = ResetReport(scope=scope, rows_deleted=count_rows(session, scope))
    for model in scope_tables(scope):
        session.execute(delete(model))
    session.commit()
    directories = {
        "output": paths.output_dir,
        "runs": paths.runs_dir,
        "progress": paths.progress_dir,
        "scraper_recipes": paths.scraper_recipes_dir,
        "workday_facets": paths.workday_facets_dir,
    }
    for area in scope_areas(scope):
        if area == "profile":
            for name in _PROFILE_SUBDIRS:
                _clear_directory(paths.profile_dir / name, report.failures)
            for name in _PROFILE_FILES:
                _remove_file(paths.profile_dir / name, report.failures)
            _remove_file(paths.taxonomy_file, report.failures)
        else:
            _clear_directory(directories[area], report.failures)
            if area == "runs":
                # Pull telemetry (sync-status "last pull") lives beside the DB,
                # not under runs/ — stale over an empty jobs table, so it goes
                # with the runs area.
                _remove_file(paths.connector_runs_file, report.failures)
        report.areas_cleared.append(area)
    return report


def _remove_file(target: Path, failures: dict[str, str]) -> None:
    try:
        target.unlink(missing_ok=True)
    except OSError as error:
        failures[str(target)] = str(error)


def _clear_directory(directory: Path, failures: dict[str, str]) -> None:
    """Delete a directory's contents; keep (or create) the directory itself."""
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return
    for child in directory.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as error:
            failures[str(child)] = str(error)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reset_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint**

Run: `ruff check src/resume_agent/services/reset.py tests/test_reset_service.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/services/reset.py tests/test_reset_service.py
git commit -m "feat: add workspace reset service with tiered scopes"
```

---

### Task 2: API endpoint `POST /api/account/reset` + contract regen

**Files:**
- Modify: `src/resume_agent/api/schemas/account.py` (append schemas)
- Modify: `src/resume_agent/api/routers/account.py` (add endpoint + imports)
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`
- Test: `tests/api/test_account_reset.py`

**Interfaces:**
- Consumes (from Task 1): `ResetPaths.resolve()`, `ResetScope`, `reset_workspace(session, paths, scope) -> ResetReport`.
- Produces (used by Task 4): route `POST /api/account/reset?confirm=RESET`, body `{"scope": "jobs"|"profile"|"all"}`, 200 response `{scope, rowsDeleted, areasCleared, failures}`; errors `400 CONFIRM_REQUIRED`, `409 RUNS_ACTIVE`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_account_reset.py` (fixtures `mu_app`/`mu_client` come from `tests/api/conftest.py`; the `_add_user` helper is the same pattern as `tests/api/test_admin_tenancy.py`):

```python
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import provision_workspace, workspace_paths
from resume_agent.tracking.tables import Job


def _login(client, username="owner", password="owner-password"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _add_user(app, username="alice") -> str:
    user_id = f"{username:0<12}"[:12]
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_hash=hash_password("alice-password"),
                role="user",
            )
        )
        session.commit()
    provision_workspace(
        app.state.data_dir, user_id, template_dir=app.state.template_config_dir
    )
    return user_id


def _seed_workspace(app, user_id):
    paths = workspace_paths(app.state.data_dir, user_id)
    engine = make_engine(paths.db_url)
    init_db(engine)
    from sqlmodel import Session as WorkspaceSession

    with WorkspaceSession(engine) as session:
        session.add(
            Job(source="manual", company="Acme", title="Engineer", dedup_key="a|e")
        )
        session.commit()
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    (paths.output_dir / "resume.pdf").write_bytes(b"%PDF")
    paths.secrets_env.write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    return paths, engine


def test_reset_requires_confirm(mu_app, mu_client):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200
    response = mu_client.post("/api/account/reset", json={"scope": "jobs"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_reset_refuses_with_active_runs(mu_app, mu_client, monkeypatch):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200
    monkeypatch.setattr(
        mu_app.state.run_manager, "list_active", lambda user_id=None: ["run"]
    )
    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "jobs"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUNS_ACTIVE"


def test_reset_jobs_wipes_pipeline_and_keeps_secrets(mu_app, mu_client):
    user_id = _add_user(mu_app)
    paths, engine = _seed_workspace(mu_app, user_id)
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "jobs"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "jobs"
    assert body["rowsDeleted"]["jobs"] == 1
    assert "output" in body["areasCleared"]
    assert body["failures"] == {}
    assert list(paths.output_dir.iterdir()) == []
    assert paths.secrets_env.exists()
    from sqlmodel import Session as WorkspaceSession
    from sqlmodel import select

    with WorkspaceSession(engine) as session:
        assert session.exec(select(Job)).first() is None


def test_reset_profile_clears_corpus_files(mu_app, mu_client):
    user_id = _add_user(mu_app)
    paths, _engine = _seed_workspace(mu_app, user_id)
    facts = paths.profile_dir / "facts.json"
    facts.parent.mkdir(parents=True, exist_ok=True)
    facts.write_text("{}", encoding="utf-8")
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "profile"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["areasCleared"] == ["profile"]
    assert not facts.exists()
    assert (paths.profile_dir / "sources").is_dir()
    assert (paths.output_dir / "resume.pdf").exists()  # jobs artifacts untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_reset.py -v`
Expected: FAIL — all four tests get 404/405 (route does not exist yet)

- [ ] **Step 3: Add the schemas**

Append to `src/resume_agent/api/schemas/account.py`:

```python
class ResetRequest(CamelModel):
    scope: Literal["jobs", "profile", "all"]


class ResetReportOut(CamelModel):
    scope: str
    rows_deleted: dict[str, int]
    areas_cleared: list[str]
    failures: dict[str, str]
```

And add to that file's imports (top of file):

```python
from typing import Literal
```

- [ ] **Step 4: Add the endpoint**

In `src/resume_agent/api/routers/account.py`, extend the existing imports:

```python
from fastapi import APIRouter, Depends, Request, Response, UploadFile  # Depends already present
from resume_agent.api.deps import get_session, get_settings_dep
from resume_agent.api.schemas.account import (
    AccountUsage,
    PasswordChangeRequest,
    ResetRequest,
    ResetReportOut,
    TokenCreated,
    TokenCreateRequest,
    TokenInfo,
    TokenList,
)
from resume_agent.services.reset import ResetPaths, ResetScope, reset_workspace
from resume_agent.tenancy.context import current_context, require_context
```

(Only `get_session`, `ResetRequest`, `ResetReportOut`, the `services.reset` line, and `current_context` are new; keep every existing import.) Then add the endpoint after `change_password`:

```python
@router.post("/reset")
def reset_data(
    body: ResetRequest,
    request: Request,
    confirm: str = "",
    session: Session = Depends(get_session),
) -> ResetReportOut:
    if confirm != "RESET":
        raise ApiException(
            400, "CONFIRM_REQUIRED", "Reset destroys data; pass ?confirm=RESET"
        )
    context = current_context()
    user_id = context.user_id if context is not None else None
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    report = reset_workspace(session, ResetPaths.resolve(), ResetScope(body.scope))
    return ResetReportOut(
        scope=report.scope.value,
        rows_deleted=report.rows_deleted,
        areas_cleared=report.areas_cleared,
        failures=report.failures,
    )
```

Note: `session` here is the request-scoped workspace session from `api/deps.py:get_session` — the tenancy dependency has already bound it to the caller's workspace engine, and `ResetPaths.resolve()` reads the same request context, so paths and DB always belong to the same user. `current_context()` (not `require_context()`) keeps the endpoint working in legacy single-user mode, where `list_active(user_id=None)` correctly means "any active run".

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_reset.py -v`
Expected: 4 passed

- [ ] **Step 6: Regenerate the contract and run the drift gate**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS; `git status` shows `contracts/openapi.json`,
`contracts/ts/api.ts`, and `web/src/lib/api/schema.ts` modified.

- [ ] **Step 7: Lint**

Run: `ruff check src/resume_agent/api/routers/account.py src/resume_agent/api/schemas/account.py tests/api/test_account_reset.py`
Expected: All checks passed

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/api/schemas/account.py src/resume_agent/api/routers/account.py tests/api/test_account_reset.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: add POST /api/account/reset with confirm gate and run guard"
```

---

### Task 3: CLI `resume-agent reset`

**Files:**
- Modify: `src/resume_agent/cli.py` (new command, place directly after the `prune` command around line 860)
- Test: `tests/test_reset_cli.py`

**Interfaces:**
- Consumes (from Task 1): `ResetPaths.resolve()`, `ResetScope`, `count_rows`, `scope_areas`, `reset_workspace`. Also `cli.py`'s existing `_engine(db_url)` helper and `get_session` (already imported there for `prune`).
- Produces: command `resume-agent reset --scope jobs|profile|all [--yes] [--db-url URL]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reset_cli.py`:

```python
from sqlmodel import Session, select
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Job

runner = CliRunner()


def _seed(db_url: str) -> None:
    engine = make_engine(db_url)
    init_db(engine)
    with Session(engine) as session:
        session.add(
            Job(source="manual", company="Acme", title="Engineer", dedup_key="a|e")
        )
        session.commit()


def _job_count(db_url: str) -> int:
    with Session(make_engine(db_url)) as session:
        return len(session.exec(select(Job)).all())


def test_reset_rejects_unknown_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["reset", "--scope", "bogus", "--yes"])
    assert result.exit_code != 0


def test_reset_aborts_on_wrong_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    _seed(db_url)
    result = runner.invoke(
        app, ["reset", "--scope", "jobs", "--db-url", db_url], input="nope\n"
    )
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert _job_count(db_url) == 1


def test_reset_with_typed_confirmation_wipes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    _seed(db_url)
    result = runner.invoke(
        app, ["reset", "--scope", "jobs", "--db-url", db_url], input="jobs\n"
    )
    assert result.exit_code == 0, result.output
    assert "jobs: 1" in result.output  # pre-delete count shown
    assert _job_count(db_url) == 0


def test_reset_with_yes_skips_prompt_and_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    _seed(db_url)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "resume.pdf").write_bytes(b"%PDF")
    result = runner.invoke(
        app, ["reset", "--scope", "jobs", "--yes", "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "Deleted 1 rows" in result.output
    assert list((tmp_path / "output").iterdir()) == []
    assert _job_count(db_url) == 0
```

(`monkeypatch.chdir(tmp_path)` matters: with no `data/` root the CLI callback finds no local context, so `ResetPaths.resolve()` falls back to CWD-relative `output/`, `data/runs`, … inside the tmp dir — nothing in the repo is touched.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reset_cli.py -v`
Expected: FAIL — `No such command 'reset'` (non-zero exit, missing output assertions)

- [ ] **Step 3: Add the command**

In `src/resume_agent/cli.py`, directly after the `prune` command:

```python
@app.command("reset")
def reset_cmd(
    scope: str = typer.Option(
        ..., "--scope", help="What to clear: jobs | profile | all."
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the typed confirmation."),
    db_url: str | None = typer.Option(
        None, "--db-url", help="Override the configured DB URL."
    ),
) -> None:
    """Clear workspace data: the job pipeline, the profile corpus, or everything.

    Config files and secrets.env always survive. Jobs with progress
    (applications, tailored resumes) are deleted too — export a backup first.
    """
    from resume_agent.services.reset import (
        ResetPaths,
        ResetScope,
        count_rows,
        reset_workspace,
        scope_areas,
    )

    try:
        reset_scope = ResetScope(scope)
    except ValueError:
        raise typer.BadParameter("scope must be jobs, profile, or all") from None
    paths = ResetPaths.resolve()
    with get_session(_engine(db_url)) as session:
        if not yes:
            typer.echo(f"Reset scope '{reset_scope.value}' will delete:")
            for table, count in count_rows(session, reset_scope).items():
                typer.echo(f"  {table}: {count} rows")
            typer.echo(
                f"  directories cleared: {', '.join(scope_areas(reset_scope))}"
            )
            answer = typer.prompt(f"Type {reset_scope.value} to confirm")
            if answer != reset_scope.value:
                typer.echo("Aborted.")
                raise typer.Exit(code=1)
        report = reset_workspace(session, paths, reset_scope)
    total = sum(report.rows_deleted.values())
    typer.echo(
        f"Deleted {total} rows; cleared: {', '.join(report.areas_cleared)}"
    )
    for path, reason in report.failures.items():
        typer.echo(f"  warning: {path}: {reason}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reset_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint**

Run: `ruff check src/resume_agent/cli.py tests/test_reset_cli.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cli.py tests/test_reset_cli.py
git commit -m "feat: add resume-agent reset command with typed confirmation"
```

---

### Task 4: Web danger zone on the Account page

**Files:**
- Create: `web/src/features/account/DangerZoneCard.tsx`
- Modify: `web/src/features/account/AccountPage.tsx`
- Test: `web/src/features/account/DangerZoneCard.test.tsx`

**Interfaces:**
- Consumes (from Task 2, via the regenerated `contracts/ts/api.ts`): `api.POST("/api/account/reset", { params: { query: { confirm: "RESET" } }, body: { scope } })` returning `{ scope, rowsDeleted, areasCleared, failures }`; existing `openDownload` and `unwrap` from `@/lib/api/client`.
- Produces: `<DangerZoneCard />` (no props), rendered on the Account page.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/account/DangerZoneCard.test.tsx` (mirrors `DataArchiveCard.test.tsx`, which is gating-only and needs no network mock):

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DangerZoneCard } from "./DangerZoneCard";

describe("DangerZoneCard", () => {
  it("gates the reset behind typed destructive confirmation", async () => {
    render(<DangerZoneCard />);

    expect(
      screen.getByRole("button", { name: "Export backup first" }),
    ).toBeEnabled();
    // Match on description text: the "Everything" option's accessible name
    // also contains the word "Jobs", so /jobs/i alone would be ambiguous.
    expect(screen.getByRole("radio", { name: /pulled jobs/i })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /profile sources/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reset data" }));
    const submit = screen.getByRole("button", { name: "Erase selected data" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/type reset/i), "RESET");
    expect(submit).toBeEnabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/account/DangerZoneCard.test.tsx`
Expected: FAIL — cannot resolve `./DangerZoneCard`

- [ ] **Step 3: Write the component**

Create `web/src/features/account/DangerZoneCard.tsx`:

```tsx
import { useId, useState } from "react";
import { Download, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, openDownload, unwrap } from "@/lib/api/client";

const SCOPES = [
  {
    value: "jobs",
    label: "Jobs",
    description:
      "Pulled jobs, applications, tailored resumes, cover letters, rendered files, and run history.",
  },
  {
    value: "profile",
    label: "Profile",
    description:
      "Profile sources, extracted facts, skill matrix, fragments, and uploaded documents. Hand-written overrides are kept.",
  },
  {
    value: "all",
    label: "Everything",
    description:
      "Jobs and profile plus discovery caches. Configuration and API keys are kept.",
  },
] as const;

type Scope = (typeof SCOPES)[number]["value"];

export function DangerZoneCard() {
  const groupName = useId();
  const confirmId = useId();
  const [scope, setScope] = useState<Scope>("jobs");
  const [confirmText, setConfirmText] = useState("");
  const [resetting, setResetting] = useState(false);

  async function runReset() {
    if (confirmText !== "RESET" || resetting) return;
    setResetting(true);
    try {
      const report = await unwrap(
        api.POST("/api/account/reset", {
          params: { query: { confirm: "RESET" } },
          body: { scope },
        }),
      );
      const failureCount = Object.keys(report.failures ?? {}).length;
      if (failureCount > 0) {
        // No reload: it would destroy this warning before it renders. The
        // dialog stays open and reset is idempotent — re-running finishes
        // the cleanup.
        toast.warning(
          `Reset finished with ${failureCount} file(s) left behind; run it again to finish.`,
        );
        setResetting(false);
        return;
      }
      window.location.reload();
    } catch (error) {
      toast.error((error as Error).message);
      setResetting(false);
    }
  }

  const selected = SCOPES.find((option) => option.value === scope);
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle>Danger zone</CardTitle>
        <CardDescription>
          Clear this workspace's data. Configuration and API keys are always
          kept. Export a backup first if you might want the data back.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">What to clear</legend>
          {SCOPES.map((option) => (
            <label
              key={option.value}
              className="flex items-start gap-2 text-sm"
            >
              <input
                type="radio"
                name={groupName}
                value={option.value}
                checked={scope === option.value}
                onChange={() => setScope(option.value)}
                className="mt-1"
              />
              <span>
                <span className="font-medium">{option.label}</span>{" "}
                <span className="text-muted-foreground">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            onClick={() => void openDownload("/api/account/export")}
          >
            <Download data-icon="inline-start" />
            Export backup first
          </Button>
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="destructive" />}>
              <TriangleAlert data-icon="inline-start" />
              Reset data
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  Reset {selected?.label.toLowerCase()}?
                </AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently deletes: {selected?.description} Configuration
                  and API keys are kept. Type RESET to continue.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <div className="py-2">
                <label
                  className="block space-y-2 text-sm font-medium"
                  htmlFor={confirmId}
                >
                  Type RESET to confirm
                  <Input
                    id={confirmId}
                    value={confirmText}
                    autoComplete="off"
                    onChange={(event) => setConfirmText(event.target.value)}
                  />
                </label>
              </div>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={resetting}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  disabled={confirmText !== "RESET" || resetting}
                  onClick={(event) => {
                    event.preventDefault();
                    void runReset();
                  }}
                >
                  {resetting ? <Spinner data-icon="inline-start" /> : null}
                  Erase selected data
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardContent>
    </Card>
  );
}
```

(The page reload after a clean success mirrors `DataArchiveCard`'s import flow — the simplest way to guarantee every cached view refreshes empty, with no cache-key list to maintain. On failures the component deliberately does NOT reload, so the warning toast survives and the user can re-run from the still-open dialog.)

- [ ] **Step 4: Wire into the Account page**

In `web/src/features/account/AccountPage.tsx`:
1. Add the import next to the existing card import: `import { DangerZoneCard } from "./DangerZoneCard";`
2. Find the `<DataArchiveCard` element (inside the `grid gap-6 xl:grid-cols-2` container) and insert `<DangerZoneCard />` immediately after it as a sibling.

- [ ] **Step 5: Run the web tests**

Run: `cd web && npx vitest run src/features/account/`
Expected: DangerZoneCard.test.tsx and DataArchiveCard.test.tsx both PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/features/account/DangerZoneCard.tsx web/src/features/account/DangerZoneCard.test.tsx web/src/features/account/AccountPage.tsx
git commit -m "feat: add danger-zone reset card to the account page"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole Python suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all tests pass (900+, includes the new 14)

- [ ] **Step 2: Run lint**

Run: `ruff check`
Expected: All checks passed

- [ ] **Step 3: Run the web suite**

Run: `cd web && npx vitest run`
Expected: all web tests pass

- [ ] **Step 4: Run web lint and production build**

Run: `cd web && npm run lint && npm run build`
Expected: both pass

- [ ] **Step 5: Run contract and diff gates**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Then: `git diff --check`
Expected: both pass

- [ ] **Step 6: Walk the reset story in a local browser**

Use the webapp-testing server helper and Playwright to verify scope selection,
typed confirmation, the reset request, the empty post-reset state, and a clean
browser console. Keep the test workspace isolated from repository data.

- [ ] **Step 7: Commit anything outstanding**

```bash
git status --short
```

Expected: clean tree (every task already committed). If generated contract files changed again, commit them with `chore: refresh generated API contract`.
