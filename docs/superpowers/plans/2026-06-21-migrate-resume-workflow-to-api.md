# Backend API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing resume-tailoring workflow (currently driven by a Typer CLI and a Streamlit dashboard) through a FastAPI HTTP server, so a future independent React/shadcn frontend can consume it — without rewriting the domain logic.

**Architecture:** A new `src/resume_tailor_harness/api/` package is a _third thin adapter_ over the domain code, sitting alongside the CLI and Streamlit. First (Phase 0) we extract the orchestration logic currently inlined in `cli.py` (agent-building + config/facts loading + the read-model filter/sort/paginate) into a reusable `src/resume_tailor_harness/services/` use-case layer; the CLI is refactored to call it, and its existing tests are the safety net proving behavior is preserved. Then the API is built on top. Minutes-long operations (`pull`/`discover`/`tailor`/`cover-letter`/add-job-from-URL) run in a background thread and report progress through a `run_id`-keyed extension of the existing `ProgressReporter` JSON store; clients watch via Server-Sent Events with a polling fallback. The Pydantic schemas are the single source of truth — FastAPI emits OpenAPI, from which a TypeScript client is generated and committed under `contracts/`.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, sse-starlette, Pydantic v2 (camelCase alias generator), SQLModel/SQLite (unchanged), pytest. Contract codegen via `openapi-typescript` (Node, used only at codegen time).

**Locked decisions (from design interview):**

- **Single-user, local-first.** SQLite, `.env` keys, local-filesystem PDFs all stay. No auth by default; an optional static bearer token via env (off unless set). CORS allowlist for localhost dev origins.
- **Restructure services first**, then add the API as an adapter. CLI + Streamlit keep working throughout.
- **Long ops = Run resource + SSE**, backed by a `run_id`-keyed `ProgressReporter`; blocking LLM work runs in a threadpool with its _own_ DB session (never the request session).
- **FastAPI; Pydantic is the contract**, TS client generated from OpenAPI and committed.
- **Core pipeline scope only.** In: ingest (add-job/pull), discover, shortlist, approve/stage/archive/restore/delete, tailor, render, cover-letter, pipeline board + application updates, triage + prune. **Deferred** (out of scope, follow-up plan): Gmail `sync-status`, analytics, match-gap, `profile build`, LinkedIn `scrape`.
- **Contract artifact only, no React app.** `contracts/openapi.json` + `contracts/ts/` committed in this repo.
- **Thin paginated lists + core filters** (`status`, `minFit`, `q`, `sortBy`, `page`, `pageSize`). Rich faceting stays client-side for now.
- **camelCase JSON** via a Pydantic `to_camel` alias generator; Python stays snake_case.

---

## File Structure

**New — application-service layer (Phase 0):**

- `src/resume_tailor_harness/services/__init__.py` — package marker.
- `src/resume_tailor_harness/services/agents.py` — central agent-bundle builders (moved out of `cli.py`).
- `src/resume_tailor_harness/services/discovery.py` — `discover_jobs`, `pull_jobs`, `add_job_from_text`, `add_job_from_url`.
- `src/resume_tailor_harness/services/tailoring.py` — `tailor` (loads config/facts, builds agents, calls `tailor/service.tailor_jobs`).
- `src/resume_tailor_harness/services/cover_letters.py` — `write_cover_letters`.
- `src/resume_tailor_harness/services/rendering.py` — `render_resume_version`.
- `src/resume_tailor_harness/services/board.py` — read-models with filter/sort/paginate (`list_shortlist`/`list_pipeline`/`list_triage`) + mutations (`approve`, `set_stage`, `set_archived`, `delete`, `upsert_application`) + `Page` result.
- `src/resume_tailor_harness/services/pagination.py` — pure `paginate(items, page, page_size)` helper.

**New — API layer (Phases 1-4):**

- `src/resume_tailor_harness/api/__init__.py`
- `src/resume_tailor_harness/api/app.py` — `create_app(...)` factory: lifespan (`init_db`), CORS, error handlers, router registration, `RunManager` wiring.
- `src/resume_tailor_harness/api/deps.py` — `get_session`, `get_settings_dep`, `require_token`, `get_run_manager`.
- `src/resume_tailor_harness/api/errors.py` — `ApiException`, `ErrorBody`/`ErrorResponse` schemas, exception handlers.
- `src/resume_tailor_harness/api/schemas/base.py` — `CamelModel`, `Pagination`, `Page[T]`.
- `src/resume_tailor_harness/api/schemas/jobs.py` — `ShortlistItem`, `PipelineItem`, `TriageItem`, `JobDetail`, `JobPatch`, `ResumeVersionOut`, `ApplicationOut`, `ApplicationUpsert`, `PruneOverrides`, `PruneReportOut`, `SkillTagOut`.
- `src/resume_tailor_harness/api/schemas/runs.py` — `RunOut`, `PullParams`, `TailorParams`, `CoverLetterParams`, `AddJobUrlParams`, `AddJobTextRequest`.
- `src/resume_tailor_harness/api/mappers.py` — DTO/table → schema converters (mostly `Schema.model_validate(dto)`).
- `src/resume_tailor_harness/api/runs/__init__.py`
- `src/resume_tailor_harness/api/runs/manager.py` — `RunManager` (create/get runs; submit work to an executor; `run_id`-keyed `ProgressReporter`).
- `src/resume_tailor_harness/api/runs/sse.py` — SSE event generator tailing a run record.
- `src/resume_tailor_harness/api/routers/health.py`
- `src/resume_tailor_harness/api/routers/boards.py` — `GET /api/shortlist`, `/api/pipeline`, `/api/triage`.
- `src/resume_tailor_harness/api/routers/jobs.py` — `GET/PATCH/DELETE /api/jobs/{id}`, sub-resources (resume-versions, application), `POST /api/jobs` (sync text add).
- `src/resume_tailor_harness/api/routers/resumes.py` — `GET /api/resume-versions/{id}/pdf`, `POST /api/resume-versions/{id}/render`.
- `src/resume_tailor_harness/api/routers/prune.py` — `POST /api/prune`.
- `src/resume_tailor_harness/api/routers/runs.py` — `POST /api/discover|pull|tailor|cover-letters|jobs/from-url`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events`.

**New — contract tooling (Phase 5):**

- `scripts/export_openapi.py` — dump `create_app().openapi()` to `contracts/openapi.json`.
- `scripts/gen_ts_client.sh` — run `openapi-typescript`.
- `contracts/openapi.json`, `contracts/ts/api.ts` — committed artifacts.

**Modified:**

- `src/resume_tailor_harness/cli.py` — commands call `services/*`; add `serve` command.
- `src/resume_tailor_harness/config.py` — `Settings` gains `api_token`, `cors_origins`.
- `src/resume_tailor_harness/progress.py` — `ProgressReporter` accepts arbitrary `process` keys + a `RUNS_ROOT`; record gains `kind`/`result` via `**extra` (already supported).
- `pyproject.toml` — add `fastapi`, `uvicorn[standard]`, `sse-starlette`.

**New tests:** mirror under `tests/` (e.g. `tests/test_services_board.py`, `tests/api/test_*.py`). All offline — agent/LLM and Playwright calls faked, runs executed via an inline executor.

---

# Phase 0 — Extract the application-service layer

> The CLI's existing tests (`tests/test_cli_*.py`) are the regression net for this phase. After each task, the relevant `test_cli_*` behavior assertions must still pass; Task 5 may retarget monkeypatches from `cli.py` to the new service modules when implementation details move.

## Task 1: Centralize agent-bundle builders

**Files:**

- Create: `src/resume_tailor_harness/services/__init__.py`
- Create: `src/resume_tailor_harness/services/agents.py`
- Test: `tests/test_services_agents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_agents.py
from resume_tailor_harness.services import agents


def test_discovery_bundle_has_three_agents(monkeypatch):
    # Each builder is faked so no SDK/model is constructed (offline).
    monkeypatch.setattr(agents, "build_extract_agent", lambda: "extract")
    monkeypatch.setattr(agents, "build_fit_agent", lambda: "fit")
    monkeypatch.setattr(agents, "build_relevance_agent", lambda: "relevance")
    monkeypatch.setattr(agents, "build_skill_canonicalizer", lambda: "canonicalizer")
    bundle = agents.build_discovery_bundle()
    assert bundle.extract == "extract"
    assert bundle.fit == "fit"
    assert bundle.relevance == "relevance"
    assert bundle.canonicalizer == "canonicalizer"


def test_tailor_bundle_builds_one_reviewer_per_spec(monkeypatch):
    class Spec:
        def __init__(self, name): self.name = name; self.model_tier = "cheap"

    class Config:
        reviewers = [Spec("a"), Spec("b")]

    monkeypatch.setattr(agents, "build_tailor_agent", lambda style_guide=None: "tailor")
    monkeypatch.setattr(agents, "build_reviser_agent", lambda style_guide=None: "reviser")
    monkeypatch.setattr(agents, "build_reviewer_agent", lambda name, model, style_guide=None: f"rev:{name}")
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: "model")
    bundle = agents.build_tailor_bundle(Config(), style_guide=None)
    assert bundle.tailor == "tailor"
    assert set(bundle.reviewers) == {"a", "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: resume_tailor_harness.services`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/services/__init__.py
```

```python
# src/resume_tailor_harness/services/agents.py
"""Central agent-bundle builders.

These were previously inlined in cli.py. Keeping them here lets the CLI, the API,
and any future adapter build the same agent sets the same way. Imports of the
concrete `build_*_agent` functions are module-level so tests can monkeypatch them.
"""

from dataclasses import dataclass
from typing import Mapping

from resume_tailor_harness.cover_letter.agents import (
    build_cover_letter_agent,
    build_cover_letter_reviser_agent,
)
from resume_tailor_harness.discovery.extract import build_extract_agent
from resume_tailor_harness.discovery.fit import build_fit_agent
from resume_tailor_harness.discovery.relevance import build_relevance_agent
from resume_tailor_harness.discovery.url_ingest.llm import build_url_extract_agent
from resume_tailor_harness.llm_runner import Runner
from resume_tailor_harness.tailor.agents import (
    build_reviewer_agent,
    build_reviser_agent,
    build_tailor_agent,
    model_for_tier,
)
from resume_tailor_harness.tracking.canonicalize import build_skill_canonicalizer


@dataclass
class DiscoveryBundle:
    extract: Runner
    fit: Runner
    relevance: Runner
    canonicalizer: object


@dataclass
class TailorBundle:
    tailor: Runner
    reviser: Runner
    reviewers: Mapping[str, Runner]


@dataclass
class CoverLetterBundle:
    draft: Runner
    reviser: Runner


def build_discovery_bundle() -> DiscoveryBundle:
    return DiscoveryBundle(
        extract=build_extract_agent(),
        fit=build_fit_agent(),
        relevance=build_relevance_agent(),
        canonicalizer=build_skill_canonicalizer(),
    )


def build_tailor_bundle(config, style_guide: str | None = None) -> TailorBundle:
    reviewers = {
        spec.name: build_reviewer_agent(
            spec.name, model_for_tier(spec.model_tier), style_guide=style_guide
        )
        for spec in config.reviewers
    }
    return TailorBundle(
        tailor=build_tailor_agent(style_guide=style_guide),
        reviser=build_reviser_agent(style_guide=style_guide),
        reviewers=reviewers,
    )


def build_cover_letter_bundle() -> CoverLetterBundle:
    return CoverLetterBundle(
        draft=build_cover_letter_agent(),
        reviser=build_cover_letter_reviser_agent(),
    )


__all__ = [
    "DiscoveryBundle", "TailorBundle", "CoverLetterBundle",
    "build_discovery_bundle", "build_tailor_bundle", "build_cover_letter_bundle",
    "build_url_extract_agent",
    # re-exported so tests can monkeypatch them on this module:
    "build_extract_agent", "build_fit_agent", "build_relevance_agent",
    "build_tailor_agent", "build_reviser_agent", "build_reviewer_agent",
    "build_cover_letter_agent", "build_cover_letter_reviser_agent",
    "model_for_tier", "build_skill_canonicalizer",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/__init__.py src/resume_tailor_harness/services/agents.py tests/test_services_agents.py
git commit -m "feat(services): central agent-bundle builders"
```

---

## Task 2: Discovery/ingest use-cases

**Files:**

- Create: `src/resume_tailor_harness/services/discovery.py`
- Test: `tests/test_services_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_discovery.py
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services import discovery


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_add_job_from_text_inserts(tmp_path):
    with _session() as session:
        job = discovery.add_job_from_text(
            session, jd_text="We need a Python engineer.", company="Acme", title="SWE"
        )
    assert job is not None
    assert job.source == "manual"
    assert job.company == "Acme"


def test_discover_jobs_delegates_to_pipeline(monkeypatch, tmp_path):
    captured = {}

    def fake_discover(session, config, facts, extract, fit, relevance, canonicalizer=None, reporter=None):
        captured["called"] = True
        return {"raw": 0, "shortlisted": 2}

    monkeypatch.setattr(discovery, "discover", fake_discover)
    monkeypatch.setattr(discovery, "load_search_config", lambda p: object())
    monkeypatch.setattr(discovery, "load_facts", lambda p: object())
    monkeypatch.setattr(
        discovery, "build_discovery_bundle",
        lambda: discovery.DiscoveryBundle(extract="e", fit="f", relevance="r", canonicalizer="c"),
    )
    with _session() as session:
        counts = discovery.discover_jobs(session, search_path="x", facts_path="y")
    assert counts == {"raw": 0, "shortlisted": 2}
    assert captured["called"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/services/discovery.py
"""Discovery + ingest use-cases: load config/facts, build agents, run, return results.

Wraps the lower-level discovery.pipeline / discovery.connectors so adapters
(CLI, API) never duplicate the build-and-load wiring. Long-running calls accept
an optional ProgressReporter passed straight through.
"""

from __future__ import annotations

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.discovery.connectors.config import load_connectors_config
from resume_tailor_harness.discovery.connectors.registry import build_connectors
from resume_tailor_harness.discovery.connectors.runner import PullReport, run_pull
from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.discovery.pipeline import discover
from resume_tailor_harness.discovery.search_config import load_search_config
from resume_tailor_harness.discovery.url_ingest.service import job_from_url
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.progress import ProgressReporter
from resume_tailor_harness.services.agents import DiscoveryBundle, build_discovery_bundle, build_url_extract_agent
from resume_tailor_harness.tracking.tables import Job

DEFAULT_SEARCH = "config/search.yaml"
DEFAULT_FACTS = "data/profile/facts.json"
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"


def add_job_from_text(
    session: Session,
    *,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
) -> Job | None:
    """Add a manually-supplied job. Returns None when deduped away."""
    return add_job(
        session, source="manual", jd_text=jd_text, url=url,
        company=company, title=title, location=location,
    )


class UrlFetchError(RuntimeError):
    """Raised when a URL could not be fetched or no JD could be extracted."""


def add_job_from_url(
    session: Session,
    *,
    url: str,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    allow_browser: bool = True,
) -> Job | None:
    """Fetch a posting URL, auto-extract fields, and add it. Returns None when deduped."""
    try:
        raw = job_from_url(url, agent=build_url_extract_agent(), allow_browser=allow_browser)
    except (httpx.HTTPError, PlaywrightError) as exc:
        raise UrlFetchError(f"Couldn't fetch {url}: {exc}") from exc
    if raw is None:
        raise UrlFetchError("Couldn't extract a job description from that URL.")
    return add_job(
        session, source="url", jd_text=raw.jd_text, url=url,
        company=company or raw.company, title=title or raw.title,
        location=location or raw.location,
    )


def discover_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Run the full discovery funnel; return final status counts."""
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    bundle = bundle or build_discovery_bundle()
    return discover(
        session, config, facts, bundle.extract, bundle.fit, bundle.relevance,
        canonicalizer=bundle.canonicalizer, reporter=reporter,
    )


def pull_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
) -> PullReport:
    """Run every enabled connector and ingest results."""
    search_config = load_search_config(search_path)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_connectors(connectors_config, get_settings())
    return run_pull(
        session, connectors, search_config, telemetry_path, limit=limit, reporter=reporter
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/discovery.py tests/test_services_discovery.py
git commit -m "feat(services): discovery + ingest use-cases"
```

---

## Task 3: Tailoring, cover-letter, and rendering use-cases

**Files:**

- Create: `src/resume_tailor_harness/services/tailoring.py`
- Create: `src/resume_tailor_harness/services/cover_letters.py`
- Create: `src/resume_tailor_harness/services/rendering.py`
- Test: `tests/test_services_tailoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_tailoring.py
from pathlib import Path

from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services import rendering, tailoring
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_tailor_loads_config_and_calls_tailor_jobs(monkeypatch):
    captured = {}

    def fake_tailor_jobs(session, targets, facts, config, tailor, reviewers, reviser, reporter=None):
        captured["targets"] = [j.id for j in targets]
        return {targets[0].id: ["v1"]}

    monkeypatch.setattr(tailoring, "tailor_jobs", fake_tailor_jobs)
    monkeypatch.setattr(tailoring, "load_review_config", lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})())
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring, "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(tailor="t", reviser="r", reviewers={}),
    )
    with _session() as session:
        job = Job(source="manual", jd_text="x", status=JobStatus.approved.value)
        session.add(job); session.commit(); session.refresh(job)
        result = tailoring.tailor(session, job_ids=[job.id])
    assert captured["targets"] == [job.id]
    assert result


def test_render_resume_version_returns_path(monkeypatch, tmp_path):
    def fake_render_version(session, version_id, config, render_fn=None):
        return tmp_path / "out.pdf"

    monkeypatch.setattr(rendering, "render_version", fake_render_version)
    monkeypatch.setattr(rendering, "_load_config", lambda p: object())
    with _session() as session:
        job = Job(source="manual", jd_text="x"); session.add(job); session.commit(); session.refresh(job)
        v = ResumeVersion(job_id=job.id, round=0); session.add(v); session.commit(); session.refresh(v)
        path = rendering.render_resume_version(session, v.id)
    assert Path(path).name == "out.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/services/tailoring.py
"""Tailor use-case: resolve targets, load config/facts, build agents, run the loop."""

from __future__ import annotations

from sqlmodel import Session

from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.progress import ProgressReporter
from resume_tailor_harness.services.agents import TailorBundle, build_tailor_bundle
from resume_tailor_harness.tailor.review_config import load_review_config
from resume_tailor_harness.tailor.service import tailor_jobs
from resume_tailor_harness.tailor.style_guide import load_style_guide
from resume_tailor_harness.tracking.repository import get_job, jobs_by_status
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion

DEFAULT_REVIEW = "config/review.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


class TargetNotFound(RuntimeError):
    """Raised when a requested job id does not exist."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Job #{job_id} not found")


def resolve_targets(session: Session, *, job_ids: list[int] | None, approved: bool) -> list[Job]:
    if job_ids:
        targets: list[Job] = []
        for jid in job_ids:
            job = get_job(session, jid)
            if job is None:
                raise TargetNotFound(jid)
            targets.append(job)
        return targets
    if approved:
        return jobs_by_status(session, JobStatus.approved.value)
    return []


def tailor(
    session: Session,
    *,
    job_ids: list[int] | None = None,
    approved: bool = False,
    review_path: str = DEFAULT_REVIEW,
    facts_path: str = DEFAULT_FACTS,
    reporter: ProgressReporter | None = None,
) -> dict[int, list[ResumeVersion]]:
    targets = resolve_targets(session, job_ids=job_ids, approved=approved)
    if not targets:
        return {}
    config = load_review_config(review_path)
    facts = load_facts(facts_path)
    style_guide = load_style_guide(config.style_guide_path)
    bundle = build_tailor_bundle(config, style_guide=style_guide)
    return tailor_jobs(
        session, targets, facts, config,
        bundle.tailor, bundle.reviewers, bundle.reviser, reporter=reporter,
    )
```

```python
# src/resume_tailor_harness/services/cover_letters.py
"""Cover-letter use-case: resolve targets, build agents, draft + render each."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from resume_tailor_harness.cover_letter.render import render_cover_letter
from resume_tailor_harness.cover_letter.service import generate_cover_letter
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.progress import ProgressReporter
from resume_tailor_harness.services.agents import build_cover_letter_bundle
from resume_tailor_harness.services.tailoring import resolve_targets

DEFAULT_FACTS = "data/profile/facts.json"


@dataclass
class CoverLetterResult:
    job_id: int
    cover_letter_id: int
    fact_check_passed: bool
    pdf_path: str


def write_cover_letters(
    session: Session,
    *,
    job_ids: list[int] | None = None,
    approved: bool = False,
    facts_path: str = DEFAULT_FACTS,
    reporter: ProgressReporter | None = None,
) -> list[CoverLetterResult]:
    targets = resolve_targets(session, job_ids=job_ids, approved=approved)
    if not targets:
        return []
    facts = load_facts(facts_path)
    bundle = build_cover_letter_bundle()
    results: list[CoverLetterResult] = []
    if reporter:
        reporter.begin(len(targets), "Starting")
    for index, job in enumerate(targets, 1):
        if job.id is None:
            raise ValueError("Cannot write a cover letter for a job that has not been persisted")
        if reporter:
            reporter.step(index - 1, label=f"Cover letter for job #{job.id}")
        cover = generate_cover_letter(session, job, facts, bundle.draft, bundle.reviser)
        if cover.id is None:
            raise RuntimeError("Cover letter was not persisted")
        path = render_cover_letter(session, cover.id)
        results.append(
            CoverLetterResult(
                job_id=job.id, cover_letter_id=cover.id,
                fact_check_passed=cover.fact_check_passed, pdf_path=str(path),
            )
        )
        if reporter:
            reporter.step(index)
    if reporter:
        reporter.done()
    return results
```

```python
# src/resume_tailor_harness/services/rendering.py
"""Render use-case: load render config, render one resume version to PDF."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from resume_tailor_harness.render.render_config import RenderConfig, load_render_config
from resume_tailor_harness.render.service import render_version

DEFAULT_RENDER = "config/render.yaml"


def _load_config(path: str) -> RenderConfig:
    return load_render_config(path) if Path(path).exists() else RenderConfig()


def render_resume_version(
    session: Session, version_id: int, *, render_path: str = DEFAULT_RENDER
) -> Path | None:
    """Render a stored version to PDF; None if the version does not exist."""
    return render_version(session, version_id, _load_config(render_path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/tailoring.py src/resume_tailor_harness/services/cover_letters.py src/resume_tailor_harness/services/rendering.py tests/test_services_tailoring.py
git commit -m "feat(services): tailoring, cover-letter, rendering use-cases"
```

---

## Task 4: Board read-models (filter/sort/paginate) + mutations

**Files:**

- Create: `src/resume_tailor_harness/services/pagination.py`
- Create: `src/resume_tailor_harness/services/board.py`
- Test: `tests/test_services_board.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_board.py
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services import board
from resume_tailor_harness.services.pagination import paginate
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_paginate_slices_and_counts():
    page = paginate(list(range(0, 25)), page=2, page_size=10)
    assert page.data == list(range(10, 20))
    assert page.total_items == 25
    assert page.total_pages == 3
    assert page.page == 2


def test_paginate_clamps_page_below_one():
    page = paginate([1, 2, 3], page=0, page_size=10)
    assert page.page == 1
    assert page.data == [1, 2, 3]


def _job(session, **kw):
    job = Job(source="manual", jd_text="x", **kw)
    session.add(job); session.commit(); session.refresh(job)
    return job


def test_list_pipeline_filters_by_status_and_min_fit():
    with _session() as session:
        _job(session, status=JobStatus.tailored.value, fit_score=90, company="Acme")
        _job(session, status=JobStatus.raw.value, fit_score=10, company="Beta")
        page = board.list_pipeline(session, status="tailored", min_fit=50)
    assert page.total_items == 1
    assert page.data[0].company == "Acme"


def test_set_stage_changes_status():
    with _session() as session:
        job = _job(session, status=JobStatus.shortlisted.value)
        updated = board.set_stage(session, job.id, JobStatus.approved.value)
    assert updated is not None
    assert updated.status == JobStatus.approved.value


def test_delete_refuses_job_with_progress():
    with _session() as session:
        job = _job(session, status=JobStatus.rendered.value)  # rendered == has_progress
        assert board.delete(session, job.id) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/services/pagination.py
"""Pure pagination helper shared by every list use-case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    data: list[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def paginate(items: list[T], *, page: int = 1, page_size: int = 50) -> Page[T]:
    page = max(1, page)
    page_size = max(1, page_size)
    total = len(items)
    total_pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return Page(
        data=items[start : start + page_size],
        page=page, page_size=page_size,
        total_items=total, total_pages=total_pages,
    )
```

```python
# src/resume_tailor_harness/services/board.py
"""Board read-models (filter/sort/paginate over the query DTOs) and mutations.

Read side wraps tracking.queries with the core server-side filters the API
exposes; rich faceting stays client-side for now. Mutation side wraps
tracking.repository, preserving the exact semantics the CLI/Streamlit use today.
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.services.pagination import Page, paginate
from resume_tailor_harness.tracking.queries import (
    PipelineRow,
    ShortlistRow,
    TriageRow,
    archived_rows,
    pipeline_rows,
    shortlist_rows,
    triage_rows,
)
from resume_tailor_harness.tracking.repository import (
    application_for_job,
    archive_job,
    delete_job,
    get_job,
    restore_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_tailor_harness.tracking.tables import Application, Job

DEFAULT_FACTS = "data/profile/facts.json"


def _by_fit_desc(rows):
    return sorted(
        rows,
        key=lambda r: (r.fit_score is not None, r.fit_score if r.fit_score is not None else -1),
        reverse=True,
    )


def list_shortlist(
    session: Session, *, min_fit: int | None = None, sort: str = "fit",
    page: int = 1, page_size: int = 50, facts_path: str = DEFAULT_FACTS,
) -> Page[ShortlistRow]:
    facts = load_facts(facts_path) if Path(facts_path).exists() else None
    rows = shortlist_rows(session, facts=facts)
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "salary":
        rows = sorted(rows, key=lambda r: (r.salary_max or r.salary_min or 0), reverse=True)
    return paginate(rows, page=page, page_size=page_size)


def list_pipeline(
    session: Session, *, status: str | None = None, min_fit: int | None = None,
    q: str | None = None, sort: str = "stage", page: int = 1, page_size: int = 50,
) -> Page[PipelineRow]:
    rows = pipeline_rows(session)
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in f"{r.company or ''} {r.title or ''}".lower()]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)


def list_triage(
    session: Session, *, archived: bool = False, status: str | None = None,
    min_fit: int | None = None, sort: str = "fit", page: int = 1, page_size: int = 50,
) -> Page[TriageRow]:
    rows = archived_rows(session) if archived else triage_rows(session)
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)


# --- mutations (preserve current CLI/Streamlit semantics) -----------------

def set_stage(session: Session, job_id: int, status: str) -> Job | None:
    job = get_job(session, job_id)
    if job is None:
        return None
    job.status = status
    return save_job(session, job)


def set_archived(session: Session, job_id: int, archived: bool) -> Job | None:
    return archive_job(session, job_id) if archived else restore_job(session, job_id)


def delete(session: Session, job_id: int) -> bool:
    return delete_job(session, job_id)


def upsert_application(
    session: Session, job_id: int, *, status: str, notes: str | None = None
) -> Application:
    existing = application_for_job(session, job_id)
    if existing is None or existing.id is None:
        return save_application(session, Application(job_id=job_id, status=status, notes=notes))
    updated = update_application_status(session, existing.id, status, notes)
    assert updated is not None  # existing.id was just confirmed present
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/pagination.py src/resume_tailor_harness/services/board.py tests/test_services_board.py
git commit -m "feat(services): board read-models + mutations"
```

---

## Task 5: Refactor the CLI onto the service layer

**Files:**

- Modify: `src/resume_tailor_harness/cli.py` (commands: `addjob`, `discover_cmd`, `pull_cmd`, `tailor_cmd`, `cover_letter_cmd`, `render_cmd`; remove the inline `build_reviewer_agents` helper)
- Test: existing `tests/test_cli_*.py` remain the regression net. Some current tests monkeypatch `cli.py` implementation details that move into `services/*`; update those monkeypatch targets to the service module or service entrypoint while keeping the command invocations and behavioral assertions unchanged.

- [ ] **Step 1: Run the CLI tests to capture the green baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_discovery.py tests/test_cli_tailor.py tests/test_cli_cover_letter.py tests/test_cli_render.py tests/test_cli_pull.py tests/test_cli_addjob_url.py -v`
Expected: PASS (baseline before refactor).

Before editing code, note the tests that patch moved symbols (`load_search_config`, `build_*_agent`, `tailor_jobs`, `job_from_url`, `generate_cover_letter`, etc.). After the refactor, retarget those patches to `resume_tailor_harness.services.discovery`, `resume_tailor_harness.services.tailoring`, `resume_tailor_harness.services.cover_letters`, or `resume_tailor_harness.services.rendering` as appropriate; do not weaken the output/status assertions.

- [ ] **Step 2: Rewrite `discover_cmd`'s funnel branch to call the service**

Replace the funnel branch at the end of `discover_cmd` (`src/resume_tailor_harness/cli.py:206-217`) with:

```python
    from resume_tailor_harness.services.discovery import discover_jobs

    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover_jobs(
            session, search_path=search, facts_path=facts,
            reporter=ProgressReporter("discover"),
        )
    typer.echo(f"Discovery complete. Status counts: {counts}")
```

(The `--reextract` / `--rescore` branches above are out of scope and stay as-is.)

- [ ] **Step 3: Rewrite `pull_cmd` to call `pull_jobs`**

Replace the body of `pull_cmd` after the config-existence check (`src/resume_tailor_harness/cli.py:255-272`) with:

```python
    from resume_tailor_harness.services.discovery import pull_jobs

    engine = _engine(db_url)
    with get_session(engine) as session:
        report = pull_jobs(
            session, search_path=search, connectors_path=connectors_path,
            telemetry_path=CONNECTOR_RUNS_PATH, limit=limit,
            reporter=ProgressReporter("pull"),
        )
    if not report.totals and not report.failures:
        typer.echo("No connectors enabled. Edit connectors.yaml (and .env) to enable some.")
        raise typer.Exit(code=0)
    for name in sorted(report.totals):
        typer.echo(f"  {name:<12} +{report.totals.get(name, 0)}")
    for name, failures in report.failures.items():
        joined = ", ".join(f"{tok} ({reason})" for tok, reason in failures.items())
        typer.echo(f"  {name}: skipped {len(failures)} dead source(s): {joined}")
    typer.echo(f"Pull complete. Added {sum(report.totals.values())} new job(s).")
```

- [ ] **Step 4: Rewrite `tailor_cmd`, `cover_letter_cmd`, `render_cmd`, `addjob`**

In `tailor_cmd`, replace the target-resolution + config-loading + agent-building + `tailor_jobs` block with:

```python
    from resume_tailor_harness.services.tailoring import tailor as tailor_service
    from resume_tailor_harness.services.tailoring import TargetNotFound

    engine = _engine(db_url)
    with get_session(engine) as session:
        try:
            results = tailor_service(
                session, job_ids=[job_id] if job_id is not None else None,
                approved=approved, review_path=review, facts_path=facts,
                reporter=ProgressReporter("tailor"),
            )
        except TargetNotFound as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        if not results:
            typer.echo("Specify --job-id <id> or --approved (and ensure the job exists).")
            raise typer.Exit(code=1)
        for jid, versions in results.items():
            typer.echo(
                f"Job #{jid}: {len(versions)} version(s); "
                f"final fact_check_passed={versions[-1].fact_check_passed}"
            )
```

In `cover_letter_cmd`, replace its body with a call to `services.cover_letters.write_cover_letters(...)` and echo each `CoverLetterResult`; catch `TargetNotFound` the same way as `tailor_cmd`. In `render_cmd`, replace the `render_version` call with `services.rendering.render_resume_version(session, version_id, render_path=config)`. In `addjob`, route the manual/stdin path through `services.discovery.add_job_from_text(...)` and the URL path through `services.discovery.add_job_from_url(...)` (catching `UrlFetchError` → `typer.Exit(1)`). Preserve the existing URL-path CLI output by echoing `Extracted: {job.title or '?'} @ {job.company or '?'} ({job.location or '?'})` when a URL job is inserted or upgraded.

Delete the now-unused module-level `build_reviewer_agents` helper (`cli.py:331-338`) and prune imports that moved into the services (`build_*_agent`, `load_review_config`, `load_style_guide`, `load_search_config` where no longer referenced, `tailor_jobs`, `discover`, `run_pull`, `generate_cover_letter`, `render_version`, etc.). Keep imports still used by out-of-scope commands.

- [ ] **Step 5: Run the CLI tests + lint to verify behavior is preserved**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_discovery.py tests/test_cli_tailor.py tests/test_cli_cover_letter.py tests/test_cli_render.py tests/test_cli_pull.py tests/test_cli_addjob_url.py -v && .venv/Scripts/python.exe -m ruff check`
Expected: PASS, ruff clean. If a CLI test fails on command output/status/data, the refactor changed behavior — reconcile the service to match the prior output exactly. If it fails only because a monkeypatch target moved, update the monkeypatch target without changing the behavioral assertion.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/cli.py
git commit -m "refactor(cli): route commands through the services layer"
```

---

# Phase 1 — API foundation

## Task 6: Add deps + Settings fields + CamelModel/Page/error schemas

**Files:**

- Modify: `src/resume_tailor_harness/config.py:16-29` (add fields)
- Modify: `pyproject.toml:7-30` (add deps)
- Create: `src/resume_tailor_harness/api/__init__.py`
- Create: `src/resume_tailor_harness/api/schemas/__init__.py`
- Create: `src/resume_tailor_harness/api/schemas/base.py`
- Create: `src/resume_tailor_harness/api/errors.py`
- Test: `tests/api/__init__.py`, `tests/api/test_schemas_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/__init__.py
```

```python
# tests/api/test_schemas_base.py
from resume_tailor_harness.api.schemas.base import CamelModel, Page, Pagination


class Item(CamelModel):
    fit_score: int
    job_id: int


def test_camel_model_dumps_camelcase_by_alias():
    item = Item(fit_score=87, job_id=3)
    assert item.model_dump(by_alias=True) == {"fitScore": 87, "jobId": 3}


def test_camel_model_accepts_camelcase_input():
    item = Item.model_validate({"fitScore": 5, "jobId": 9})
    assert item.fit_score == 5


def test_camel_model_validates_from_attributes():
    class Dto:
        fit_score = 70
        job_id = 1
    item = Item.model_validate(Dto())
    assert item.fit_score == 70


def test_page_envelope_shape():
    page = Page[Item](
        data=[Item(fit_score=1, job_id=1)],
        pagination=Pagination(page=1, page_size=50, total_items=1, total_pages=1),
    )
    dumped = page.model_dump(by_alias=True)
    assert dumped["pagination"]["pageSize"] == 50
    assert dumped["data"][0]["fitScore"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_base.py -v`
Expected: FAIL with `ModuleNotFoundError: resume_tailor_harness.api`.

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` `dependencies` list:

```toml
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sse-starlette>=2.1.0",
```

Then install: `uv sync` (or `.venv/Scripts/python.exe -m pip install "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" "sse-starlette>=2.1.0"`).

Add to `Settings` in `src/resume_tailor_harness/config.py` (after `deepseek_api_key`):

```python
    api_token: str = ""  # when non-empty, the API requires Authorization: Bearer <token>
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
```

```python
# src/resume_tailor_harness/api/__init__.py
```

```python
# src/resume_tailor_harness/api/schemas/__init__.py
```

```python
# src/resume_tailor_harness/api/schemas/base.py
"""Shared API schema base: camelCase wire format + the pagination envelope."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """All request/response models serialize to camelCase on the wire.

    Python field names stay snake_case; the alias generator maps them to camelCase.
    `populate_by_name` lets construction work with either spelling;
    `from_attributes` lets `model_validate(dto)` read snake_case dataclass attrs.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class Pagination(CamelModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class Page(CamelModel, Generic[T]):
    data: list[T]
    pagination: Pagination
```

```python
# src/resume_tailor_harness/api/errors.py
"""Single error envelope + handlers. Every error response is { "error": {...} }."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from resume_tailor_harness.api.schemas.base import CamelModel


class ErrorBody(CamelModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(CamelModel):
    error: ErrorBody


class ApiException(Exception):
    """Raise to return a structured error with a chosen status + machine code."""

    def __init__(self, status_code: int, code: str, message: str, details: Any | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _envelope(code: str, message: str, details: Any | None = None) -> dict:
    return ErrorResponse(error=ErrorBody(code=code, message=message, details=details)).model_dump(
        by_alias=True
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api_exc(_: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 409: "CONFLICT"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_base.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/resume_tailor_harness/config.py src/resume_tailor_harness/api/ tests/api/__init__.py tests/api/test_schemas_base.py
git commit -m "feat(api): foundation — deps, settings, CamelModel + error envelope"
```

---

## Task 7: Dependencies (session, settings, auth) + app factory + health endpoint

**Files:**

- Create: `src/resume_tailor_harness/api/deps.py`
- Create: `src/resume_tailor_harness/api/routers/__init__.py`
- Create: `src/resume_tailor_harness/api/routers/health.py`
- Create: `src/resume_tailor_harness/api/app.py`
- Test: `tests/api/test_app_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_app_health.py
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def _client(**kw):
    return TestClient(create_app(db_url="sqlite://", **kw))


def test_health_ok():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_no_auth_by_default():
    assert _client().get("/api/health").status_code == 200


def test_bearer_required_when_token_set():
    client = _client(api_token="secret")
    assert client.get("/api/health").status_code == 200  # health is unguarded
    # a guarded route (added later) would 401; here we assert the dep itself:
    from resume_tailor_harness.api.deps import require_token
    from resume_tailor_harness.api.errors import ApiException
    import pytest
    with pytest.raises(ApiException) as ei:
        require_token(authorization=None, settings=type("S", (), {"api_token": "secret"})())
    assert ei.value.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_app_health.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/deps.py
"""FastAPI dependencies: per-request DB session, settings, optional bearer auth."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlmodel import Session

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.config import Settings, get_settings


def get_settings_dep() -> Settings:
    return get_settings()


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session bound to the app's engine; closed after the request."""
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """No-op when no api_token is configured; else enforce a bearer match."""
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid bearer token")
```

```python
# src/resume_tailor_harness/api/routers/__init__.py
```

```python
# src/resume_tailor_harness/api/routers/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

```python
# src/resume_tailor_harness/api/app.py
"""FastAPI application factory — the third adapter over the domain code."""

from __future__ import annotations

from contextlib import asynccontextmanager
from concurrent.futures import Executor
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from resume_tailor_harness.api.deps import get_settings_dep, require_token
from resume_tailor_harness.api.errors import install_error_handlers
from resume_tailor_harness.api.routers import health
from resume_tailor_harness.config import get_settings
from resume_tailor_harness.db import init_db, make_engine


def create_app(
    *,
    db_url: str | None = None,
    api_token: str | None = None,
    run_executor: Executor | None = None,
    runs_root: Path | str | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_db = db_url or settings.db_url
    resolved_token = settings.api_token if api_token is None else api_token
    resolved_settings = settings.model_copy(
        update={"db_url": resolved_db, "api_token": resolved_token}
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        init_db(engine)
        app.state.engine = engine
        yield

    app = FastAPI(title="Résumé Tailor Harness API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.db_url = resolved_db
    app.dependency_overrides[get_settings_dep] = lambda: resolved_settings

    origins = [o.strip() for o in resolved_settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    install_error_handlers(app)

    # Guard everything except /api/health behind the optional bearer token.
    guarded = [Depends(require_token)]
    app.include_router(health.router, prefix="/api")
    # (subsequent routers are included with dependencies=guarded in later tasks)

    return app
```

Note: routes that depend on lifespan-initialized state (`app.state.engine`) should use `with TestClient(...)` in tests; the health route does not need that state. The `api_token` and `db_url` overrides are copied into a per-app `Settings` object and installed via FastAPI's dependency override mechanism, so guarded routes see the app-specific token instead of the cached process-global settings.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_app_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/deps.py src/resume_tailor_harness/api/routers/ src/resume_tailor_harness/api/app.py tests/api/test_app_health.py
git commit -m "feat(api): app factory, deps, health endpoint"
```

---

# Phase 2 — Read endpoints

## Task 8: Board list endpoints (shortlist / pipeline / triage)

**Files:**

- Create: `src/resume_tailor_harness/api/schemas/jobs.py` (board item schemas)
- Create: `src/resume_tailor_harness/api/mappers.py`
- Create: `src/resume_tailor_harness/api/routers/boards.py`
- Modify: `src/resume_tailor_harness/api/app.py` (include `boards.router` with `guarded`)
- Test: `tests/api/test_boards.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_boards.py
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as session:
        job = Job(source="manual", jd_text="x", **kw)
        session.add(job); session.commit(); session.refresh(job)
        return job.id


def test_pipeline_returns_paginated_envelope():
    client = _client()
    with client:  # triggers lifespan -> engine
        _seed(client.app, status=JobStatus.tailored.value, fit_score=80, company="Acme")
        resp = client.get("/api/pipeline?pageSize=10")
        body = resp.json()
    assert resp.status_code == 200
    assert body["pagination"]["pageSize"] == 10
    assert body["data"][0]["company"] == "Acme"
    assert "fitScore" in body["data"][0]


def test_pipeline_status_filter():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.tailored.value, company="Keep")
        _seed(client.app, status=JobStatus.raw.value, company="Drop")
        body = client.get("/api/pipeline?status=tailored").json()
    assert [r["company"] for r in body["data"]] == ["Keep"]


def test_triage_archived_query():
    client = _client()
    with client:
        body = client.get("/api/triage?archived=true").json()
    assert body["data"] == []


def test_bearer_enforced_on_guarded_route():
    client = TestClient(create_app(db_url="sqlite://", api_token="secret"))
    with client:
        assert client.get("/api/pipeline").status_code == 401
        ok = client.get("/api/pipeline", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -v`
Expected: FAIL (no `/api/pipeline` route).

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/schemas/jobs.py
"""Job-side API schemas: board items, detail, patch, sub-resources, prune."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from resume_tailor_harness.api.schemas.base import CamelModel


class SkillTagOut(CamelModel):
    name: str
    covered: bool
    required: bool


class ShortlistItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTagOut]


class PipelineItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: int | None
    salary_max: int | None
    remote_policy: str | None
    seniority: str | None
    has_progress: bool


class TriageItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    source: str
    status: str
    fit_score: int | None
    posted_at: datetime | None
    archived_at: datetime | None
    has_progress: bool


class ResumeVersionOut(CamelModel):
    id: int
    job_id: int
    round: int
    review_score: int | None
    fact_check_passed: bool
    pdf_path: str | None
    critique_json: list[dict] | None
    created_at: datetime


class ApplicationOut(CamelModel):
    id: int
    job_id: int
    status: str
    notes: str | None
    submitted_at: datetime | None
    updated_at: datetime


class JobDetail(CamelModel):
    id: int
    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str
    status: str
    fit_score: int | None
    fit_rationale: str | None
    criteria_json: dict[str, Any] | None
    posted_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: ApplicationOut | None
    resume_versions: list[ResumeVersionOut]


class JobPatch(CamelModel):
    status: str | None = None
    archived: bool | None = None


class ApplicationUpsert(CamelModel):
    status: str
    notes: str | None = None


class PruneOverrides(CamelModel):
    dry_run: bool = True
    fit_threshold: int | None = None
    stale_days: int | None = None
    retention_days: int | None = None


class PruneReportOut(CamelModel):
    archived: int
    expired: int
    skipped: int
    rejected: int
    low_fit: int
    stale: int
```

```python
# src/resume_tailor_harness/api/mappers.py
"""DTO/table -> schema converters. Most are model_validate (from_attributes)."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import Page, Pagination
from resume_tailor_harness.services.pagination import Page as ServicePage


def to_page(service_page: ServicePage, item_model) -> Page:
    return Page(
        data=[item_model.model_validate(row) for row in service_page.data],
        pagination=Pagination(
            page=service_page.page,
            page_size=service_page.page_size,
            total_items=service_page.total_items,
            total_pages=service_page.total_pages,
        ),
    )
```

```python
# src/resume_tailor_harness/api/routers/boards.py
"""Read-only board lists: shortlist, pipeline, triage. Paginated + core filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.mappers import to_page
from resume_tailor_harness.api.schemas.base import Page
from resume_tailor_harness.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_tailor_harness.services import board

router = APIRouter()


@router.get("/shortlist", response_model=Page[ShortlistItem])
def get_shortlist(
    min_fit: int | None = Query(None, alias="minFit"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_shortlist(session, min_fit=min_fit, sort=sort, page=page, page_size=page_size)
    return to_page(result, ShortlistItem)


@router.get("/pipeline", response_model=Page[PipelineItem])
def get_pipeline(
    status: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    q: str | None = None,
    sort: str = Query("stage", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_pipeline(
        session, status=status, min_fit=min_fit, q=q, sort=sort, page=page, page_size=page_size
    )
    return to_page(result, PipelineItem)


@router.get("/triage", response_model=Page[TriageItem])
def get_triage(
    archived: bool = False,
    status: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_triage(
        session, archived=archived, status=status, min_fit=min_fit,
        sort=sort, page=page, page_size=page_size
    )
    return to_page(result, TriageItem)
```

In `src/resume_tailor_harness/api/app.py`, replace the comment line after the health include with the boards include using the bearer guard:

```python
    from resume_tailor_harness.api.routers import boards

    app.include_router(health.router, prefix="/api")
    app.include_router(boards.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/jobs.py src/resume_tailor_harness/api/mappers.py src/resume_tailor_harness/api/routers/boards.py src/resume_tailor_harness/api/app.py tests/api/test_boards.py
git commit -m "feat(api): shortlist/pipeline/triage list endpoints"
```

---

## Task 9: Job detail + resume-version PDF download

**Files:**

- Create: `src/resume_tailor_harness/api/routers/jobs.py` (detail only this task; mutations added in Task 10)
- Create: `src/resume_tailor_harness/api/routers/resumes.py`
- Modify: `src/resume_tailor_harness/api/app.py` (include both routers, guarded)
- Test: `tests/api/test_job_detail.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_job_detail.py
from pathlib import Path

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_job_detail_includes_versions_and_application():
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="hello", status=JobStatus.tailored.value)
            s.add(job); s.commit(); s.refresh(job)
            s.add(ResumeVersion(job_id=job.id, round=0, review_score=88)); s.commit()
            jid = job.id
        body = client.get(f"/api/jobs/{jid}").json()
    assert body["id"] == jid
    assert body["jdText"] == "hello"
    assert body["resumeVersions"][0]["reviewScore"] == 88


def test_job_detail_404():
    client = _client()
    with client:
        resp = client.get("/api/jobs/9999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_pdf_download_404_when_no_file(tmp_path):
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="x"); s.add(job); s.commit(); s.refresh(job)
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(tmp_path / "missing.pdf"))
            s.add(v); s.commit(); s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 404


def test_pdf_download_streams_file(tmp_path):
    client = _client()
    pdf = tmp_path / "ok.pdf"; pdf.write_bytes(b"%PDF-1.4 test")
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="x"); s.add(job); s.commit(); s.refresh(job)
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(pdf))
            s.add(v); s.commit(); s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/routers/jobs.py
"""Single-job endpoints: detail (this task), mutations (Task 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.jobs import (
    ApplicationOut,
    JobDetail,
    ResumeVersionOut,
)
from resume_tailor_harness.tracking.repository import (
    application_for_job,
    get_job,
    has_progress,
    resume_versions_for_job,
)

router = APIRouter()


def _job_detail(session: Session, job_id: int) -> JobDetail:
    job = get_job(session, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    application = application_for_job(session, job_id)
    versions = resume_versions_for_job(session, job_id)
    return JobDetail(
        id=job.id,
        source=job.source,
        url=job.url,
        company=job.company,
        title=job.title,
        location=job.location,
        jd_text=job.jd_text,
        status=job.status,
        fit_score=job.fit_score,
        fit_rationale=job.fit_rationale,
        criteria_json=job.criteria_json,
        posted_at=job.posted_at,
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, job_id),
        application=ApplicationOut.model_validate(application) if application else None,
        resume_versions=[ResumeVersionOut.model_validate(v) for v in versions],
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job_detail(job_id: int, session: Session = Depends(get_session)):
    return _job_detail(session, job_id)
```

```python
# src/resume_tailor_harness/api/routers/resumes.py
"""Resume-version PDF download + on-demand render (render added in Task 11)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.tracking.repository import get_resume_version

router = APIRouter()


@router.get("/resume-versions/{version_id}/pdf")
def download_pdf(version_id: int, session: Session = Depends(get_session)) -> FileResponse:
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    if not version.pdf_path or not Path(version.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this version")
    return FileResponse(
        version.pdf_path, media_type="application/pdf", filename=Path(version.pdf_path).name
    )
```

In `app.py`, add the includes (guarded):

```python
    from resume_tailor_harness.api.routers import jobs as jobs_router
    from resume_tailor_harness.api.routers import resumes

    app.include_router(jobs_router.router, prefix="/api", dependencies=guarded)
    app.include_router(resumes.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/jobs.py src/resume_tailor_harness/api/routers/resumes.py src/resume_tailor_harness/api/app.py tests/api/test_job_detail.py
git commit -m "feat(api): job detail + resume PDF download"
```

---

# Phase 3 — Mutations

## Task 10: Job mutations (PATCH status/archived, DELETE) + application upsert + manual add

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/jobs.py` (add PATCH, DELETE, PUT application, POST manual add)
- Test: `tests/api/test_job_mutations.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_job_mutations.py
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, **kw):
    with get_session(app.state.engine) as s:
        job = Job(source="manual", jd_text="x", **kw)
        s.add(job); s.commit(); s.refresh(job)
        return job.id


def test_patch_status_approves():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.shortlisted.value)
        resp = client.patch(f"/api/jobs/{jid}", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_patch_archived_then_restore():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.raw.value)
        archived = client.patch(f"/api/jobs/{jid}", json={"archived": True}).json()
        assert archived["archivedAt"] is not None
        restored = client.patch(f"/api/jobs/{jid}", json={"archived": False}).json()
        assert restored["archivedAt"] is None


def test_delete_conflict_when_has_progress():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.rendered.value)
        resp = client.delete(f"/api/jobs/{jid}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_delete_succeeds_zero_progress():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.raw.value)
        assert client.delete(f"/api/jobs/{jid}").status_code == 204


def test_put_application_upserts():
    client = _client()
    with client:
        jid = _seed(client.app, status=JobStatus.rendered.value)
        resp = client.put(f"/api/jobs/{jid}/application", json={"status": "submitted", "notes": "ref"})
        body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "submitted"
    assert body["notes"] == "ref"


def test_post_manual_job_creates():
    client = _client()
    with client:
        resp = client.post("/api/jobs", json={"jdText": "Need a dev", "company": "Acme"})
    assert resp.status_code == 201
    assert resp.json()["company"] == "Acme"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_mutations.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_tailor_harness/api/routers/jobs.py` (add imports at top: `Response` from fastapi; `JobPatch, ApplicationUpsert, ApplicationOut` already partly imported — ensure all present; `board` service; `add_job_from_text`):

```python
from fastapi import Response

from resume_tailor_harness.api.schemas.jobs import ApplicationUpsert, JobPatch
from resume_tailor_harness.api.schemas.runs import AddJobTextRequest  # defined in Task 12
from resume_tailor_harness.services import board
from resume_tailor_harness.services.discovery import add_job_from_text
from resume_tailor_harness.tracking.tables import ApplicationStatus, JobStatus


@router.patch("/jobs/{job_id}", response_model=JobDetail)
def patch_job(job_id: int, patch: JobPatch, session: Session = Depends(get_session)):
    if patch.status is not None:
        valid = {s.value for s in JobStatus}
        if patch.status not in valid:
            raise ApiException(422, "VALIDATION_ERROR", f"Unknown status '{patch.status}'")
        if board.set_stage(session, job_id, patch.status) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if patch.archived is not None:
        if board.set_archived(session, job_id, patch.archived) is None:
            raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return _job_detail(session, job_id)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job_endpoint(job_id: int, session: Session = Depends(get_session)) -> Response:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not board.delete(session, job_id):
        raise ApiException(409, "CONFLICT", "Job has progress and cannot be deleted")
    return Response(status_code=204)


@router.put("/jobs/{job_id}/application", response_model=ApplicationOut)
def upsert_application(job_id: int, body: ApplicationUpsert, session: Session = Depends(get_session)):
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    valid = {s.value for s in ApplicationStatus}
    if body.status not in valid:
        raise ApiException(422, "VALIDATION_ERROR", f"Unknown application status '{body.status}'")
    app_row = board.upsert_application(session, job_id, status=body.status, notes=body.notes)
    return ApplicationOut.model_validate(app_row)


@router.post("/jobs", response_model=JobDetail, status_code=201)
def create_manual_job(body: AddJobTextRequest, session: Session = Depends(get_session)):
    job = add_job_from_text(
        session, jd_text=body.jd_text, url=body.url,
        company=body.company, title=body.title, location=body.location,
    )
    if job is None:
        raise ApiException(409, "CONFLICT", "Duplicate job (same URL or JD already present)")
    assert job.id is not None
    return _job_detail(session, job.id)
```

(`AddJobTextRequest` is created in Task 12; if implementing strictly in order, define it inline here and move it in Task 12. To keep tasks independent, add the small schema now in `src/resume_tailor_harness/api/schemas/runs.py`:)

```python
# src/resume_tailor_harness/api/schemas/runs.py  (partial — completed in Task 12)
from __future__ import annotations

from resume_tailor_harness.api.schemas.base import CamelModel


class AddJobTextRequest(CamelModel):
    jd_text: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_mutations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/jobs.py src/resume_tailor_harness/api/schemas/runs.py tests/api/test_job_mutations.py
git commit -m "feat(api): job mutations, application upsert, manual add"
```

---

## Task 11: Prune endpoint + synchronous render endpoint

**Files:**

- Create: `src/resume_tailor_harness/api/routers/prune.py`
- Modify: `src/resume_tailor_harness/api/routers/resumes.py` (add POST render)
- Modify: `src/resume_tailor_harness/api/app.py` (include prune router, guarded)
- Test: `tests/api/test_prune_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_prune_render.py
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.routers import resumes
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_prune_dry_run_reports_counts():
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:
            s.add(Job(source="manual", jd_text="x", status=JobStatus.rejected.value)); s.commit()
        body = client.post("/api/prune", json={"dryRun": True}).json()
    assert body["rejected"] >= 1
    assert "archived" in body


def test_render_endpoint_invokes_service(monkeypatch, tmp_path):
    client = _client()
    pdf = tmp_path / "r.pdf"; pdf.write_bytes(b"%PDF-1.4")

    def fake_render(session, version_id, *, render_path="config/render.yaml"):
        v = __import__("resume_tailor_harness.tracking.repository", fromlist=["get_resume_version"]).get_resume_version(session, version_id)
        v.pdf_path = str(pdf)
        session.add(v); session.commit()
        return pdf

    monkeypatch.setattr(resumes, "render_resume_version", fake_render)
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="x"); s.add(job); s.commit(); s.refresh(job)
            v = ResumeVersion(job_id=job.id, round=0); s.add(v); s.commit(); s.refresh(v)
            vid = v.id
        body = client.post(f"/api/resume-versions/{vid}/render").json()
    assert body["pdfPath"].endswith("r.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_prune_render.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/routers/prune.py
"""Prune endpoint: preview (dryRun) or run, with optional config overrides."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.schemas.jobs import PruneOverrides, PruneReportOut
from resume_tailor_harness.tracking.prune_config import load_prune_config
from resume_tailor_harness.tracking.repository import prune_preview, prune_run

router = APIRouter()
_PRUNE_CONFIG_PATH = "config/prune.yaml"


@router.post("/prune", response_model=PruneReportOut)
def prune(body: PruneOverrides, session: Session = Depends(get_session)):
    config = load_prune_config(_PRUNE_CONFIG_PATH)
    overrides = {
        k: v for k, v in (
            ("fit_threshold", body.fit_threshold),
            ("stale_days", body.stale_days),
            ("retention_days", body.retention_days),
        ) if v is not None
    }
    if overrides:
        config = config.model_copy(update=overrides)
    report = prune_preview(session, config) if body.dry_run else prune_run(session, config)
    return PruneReportOut.model_validate(report)
```

Append to `src/resume_tailor_harness/api/routers/resumes.py`:

```python
from resume_tailor_harness.api.schemas.jobs import ResumeVersionOut
from resume_tailor_harness.services.rendering import render_resume_version


@router.post("/resume-versions/{version_id}/render", response_model=ResumeVersionOut)
def render_endpoint(version_id: int, session: Session = Depends(get_session)):
    path = render_resume_version(session, version_id)
    if path is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    return ResumeVersionOut.model_validate(version)
```

In `app.py` add (guarded):

```python
    from resume_tailor_harness.api.routers import prune as prune_router

    app.include_router(prune_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_prune_render.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/prune.py src/resume_tailor_harness/api/routers/resumes.py src/resume_tailor_harness/api/app.py tests/api/test_prune_render.py
git commit -m "feat(api): prune + synchronous render endpoints"
```

---

# Phase 4 — Run substrate + SSE

## Task 12: RunManager (run_id-keyed progress + background executor)

**Files:**

- Create: `src/resume_tailor_harness/api/runs/__init__.py`
- Create: `src/resume_tailor_harness/api/runs/manager.py`
- Modify: `src/resume_tailor_harness/api/schemas/runs.py` (add `RunOut` + param schemas)
- Modify: `src/resume_tailor_harness/progress.py:21-24` (add `RUNS_ROOT`)
- Test: `tests/api/test_run_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_run_manager.py
from concurrent.futures import Executor, Future

from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.progress import ProgressReporter


class InlineExecutor(Executor):
    """Runs submitted callables immediately, in-thread — deterministic for tests."""

    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


def test_create_run_starts_pending(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("discover")
    rec = mgr.get(run_id)
    assert rec["kind"] == "discover"
    assert rec["state"] in ("pending", "running", "done")


def test_submit_runs_fn_and_records_result(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def work(reporter: ProgressReporter):
        reporter.begin(1, "working")
        reporter.step(1)
        return {"statusCounts": {"shortlisted": 3}}

    run_id = mgr.submit("discover", work)
    rec = mgr.get(run_id)
    assert rec["state"] == "done"
    assert rec["result"] == {"statusCounts": {"shortlisted": 3}}


def test_submit_records_error(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())

    def boom(reporter):
        raise ValueError("nope")

    run_id = mgr.submit("pull", boom)
    rec = mgr.get(run_id)
    assert rec["state"] == "error"
    assert "nope" in rec["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/resume_tailor_harness/progress.py` near `PROGRESS_ROOT`:

```python
RUNS_ROOT = Path("data/runs")
```

```python
# src/resume_tailor_harness/api/runs/__init__.py
```

```python
# src/resume_tailor_harness/api/runs/manager.py
"""Background run substrate.

A run is a unit of long work (discover/pull/tailor/cover-letter/add-job-from-url).
It is keyed by a uuid4 and persisted as one JSON record per run under RUNS_ROOT,
reusing ProgressReporter (so percent/ETA come for free). Work runs in an Executor
(a ThreadPool in production, an inline executor in tests). The worker callable
receives a ProgressReporter and returns a JSON-serializable result dict, which is
stamped onto the terminal record via reporter.done(result=...).

The worker must open its OWN DB session (a request's Session is not thread-safe),
so callables here are closures created by the run router with their own engine.
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from resume_tailor_harness.progress import (
    RUNS_ROOT,
    ProgressReporter,
    clear_progress,
    read_progress,
)

RunFn = Callable[[ProgressReporter], object]


class RunProgressReporter(ProgressReporter):
    """ProgressReporter variant that preserves the run kind on every write."""

    def __init__(self, run_id: str, kind: str, root: Path | str) -> None:
        super().__init__(run_id, root=root)
        self.kind = kind

    def begin(
        self,
        total: int,
        label: str,
        *,
        phase_index: int | None = None,
        phase_count: int | None = None,
        **extra: object,
    ) -> None:
        super().begin(
            total,
            label,
            phase_index=phase_index,
            phase_count=phase_count,
            kind=self.kind,
            **extra,
        )

    def done(self, *, error: str | None = None, **extra: object) -> None:
        super().done(error=error, kind=self.kind, **extra)


class RunManager:
    def __init__(self, *, root: Path | str = RUNS_ROOT, executor: Executor | None = None) -> None:
        self.root = Path(root)
        self.executor = executor or ThreadPoolExecutor(max_workers=2)
        self._owns_executor = executor is None

    def create(self, kind: str) -> str:
        run_id = uuid.uuid4().hex
        # Seed a terminal-less "pending" record so GET works before work begins.
        self._write(run_id, {
            "process": run_id, "kind": kind, "state": "pending",
            "label": "Queued", "current": 0, "total": 0,
            "started_at": _now(), "result": None, "error": None,
            "updated_at": _now(),
        })
        return run_id

    def reporter(self, run_id: str, kind: str) -> RunProgressReporter:
        return RunProgressReporter(run_id, kind, self.root)

    def submit(self, kind: str, fn: RunFn) -> str:
        run_id = self.create(kind)
        reporter = self.reporter(run_id, kind)

        def _runner() -> None:
            try:
                result = fn(reporter)
                reporter.done(result=result)
            except Exception as exc:  # noqa: BLE001 — surface any failure as run error
                reporter.done(error=f"{type(exc).__name__}: {exc}", result=None)

        self.executor.submit(_runner)
        return run_id

    def get(self, run_id: str) -> dict | None:
        return read_progress(run_id, root=self.root)

    def clear(self, run_id: str) -> None:
        clear_progress(run_id, root=self.root)

    def shutdown(self) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=False)

    def _write(self, run_id: str, record: dict) -> None:
        path = self.root / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

Note: `RunProgressReporter` injects `kind` into every `begin()`/`done()` write, so a running record never loses its run type after the worker starts. The `create()` seed writes `kind`/`result`/`error` keys directly so the record shape is stable from the first read without touching `ProgressReporter` private fields.

Add to `src/resume_tailor_harness/api/schemas/runs.py` (append to the file started in Task 10):

```python
from typing import Any


class RunOut(CamelModel):
    run_id: str
    kind: str
    state: str  # pending | running | done | error
    label: str
    percent: int
    current: int
    total: int
    eta_text: str | None = None
    result: Any | None = None
    error: str | None = None


class PullParams(CamelModel):
    limit: int | None = None


class TailorParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False


class CoverLetterParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False


class AddJobUrlParams(CamelModel):
    url: str
    company: str | None = None
    title: str | None = None
    location: str | None = None
    allow_browser: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/ src/resume_tailor_harness/api/schemas/runs.py src/resume_tailor_harness/progress.py tests/api/test_run_manager.py
git commit -m "feat(api): run manager — run_id-keyed background work"
```

---

## Task 13: Run launch endpoints + GET run

**Files:**

- Create: `src/resume_tailor_harness/api/runs/sse.py` (record→RunOut mapper used here and by SSE)
- Create: `src/resume_tailor_harness/api/routers/runs.py`
- Modify: `src/resume_tailor_harness/api/app.py` (construct `RunManager`, store on `app.state`, include router guarded, accept `run_executor`)
- Modify: `src/resume_tailor_harness/api/deps.py` (add `get_run_manager`)
- Test: `tests/api/test_runs_launch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_runs_launch.py
from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.routers import runs as runs_router


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


def _client(tmp_path):
    return TestClient(
        create_app(db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path)
    )


def test_discover_launch_returns_run(monkeypatch, tmp_path):
    # Fake the service so no LLM/network runs; assert the run wiring works.
    def fake_discover_jobs(session, *, reporter=None, **kw):
        reporter.begin(1, "x"); reporter.step(1)
        return {"shortlisted": 2}

    monkeypatch.setattr(runs_router, "discover_jobs", fake_discover_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/discover", json={})
        assert resp.status_code == 202
        run_id = resp.json()["runId"]
        got = client.get(f"/api/runs/{run_id}").json()
    assert got["kind"] == "discover"
    assert got["state"] == "done"
    assert got["result"] == {"statusCounts": {"shortlisted": 2}}
    assert got["percent"] == 100


def test_get_unknown_run_404(tmp_path):
    client = _client(tmp_path)
    with client:
        assert client.get("/api/runs/deadbeef").status_code == 404


def test_tailor_launch_passes_params(monkeypatch, tmp_path):
    captured = {}

    def fake_tailor(session, *, job_ids=None, approved=False, reporter=None, **kw):
        captured["job_ids"] = job_ids; captured["approved"] = approved
        reporter.begin(1, "x"); reporter.step(1)
        return {}

    monkeypatch.setattr(runs_router, "tailor", fake_tailor)
    client = _client(tmp_path)
    with client:
        client.post("/api/tailor", json={"jobIds": [1, 2], "approved": False})
    assert captured["job_ids"] == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/runs/sse.py
"""Shared record -> RunOut projection (used by GET /runs/{id} and the SSE stream)."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.runs import RunOut
from resume_tailor_harness.progress import progress_stats


def record_to_run(run_id: str, record: dict) -> RunOut:
    stats = progress_stats(record)
    return RunOut(
        run_id=run_id,
        kind=str(record.get("kind") or ""),
        state=stats.state if record.get("state") != "pending" else "pending",
        label=stats.label,
        percent=stats.pct,
        current=stats.current,
        total=stats.total,
        eta_text=stats.eta_text,
        result=record.get("result"),
        error=stats.error,
    )
```

```python
# src/resume_tailor_harness/api/routers/runs.py
"""Run launch endpoints + GET run. Each launch returns 202 with the run record.

The work callables open their OWN session inside the worker thread — never the
request session, which is not safe to share across threads. The session is bound
to the app engine so `create_app(db_url=...)` and in-memory test databases are
honored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from resume_tailor_harness.api.deps import get_run_manager
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.api.runs.sse import record_to_run
from resume_tailor_harness.api.schemas.runs import (
    AddJobUrlParams,
    CoverLetterParams,
    PullParams,
    RunOut,
    TailorParams,
)
from resume_tailor_harness.db import get_session
from resume_tailor_harness.services.cover_letters import write_cover_letters
from resume_tailor_harness.services.discovery import add_job_from_url, discover_jobs, pull_jobs
from resume_tailor_harness.services.tailoring import tailor

router = APIRouter()


def _engine(request: Request):
    return request.app.state.engine


@router.post("/discover", response_model=RunOut, status_code=202)
def launch_discover(request: Request, mgr: RunManager = Depends(get_run_manager)):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return {"statusCounts": discover_jobs(session, reporter=reporter)}

    run_id = mgr.submit("discover", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/pull", response_model=RunOut, status_code=202)
def launch_pull(params: PullParams, request: Request, mgr: RunManager = Depends(get_run_manager)):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            report = pull_jobs(session, limit=params.limit, reporter=reporter)
            return {"totals": report.totals, "failures": report.failures}

    run_id = mgr.submit("pull", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/tailor", response_model=RunOut, status_code=202)
def launch_tailor(params: TailorParams, request: Request, mgr: RunManager = Depends(get_run_manager)):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            results = tailor(
                session, job_ids=params.job_ids, approved=params.approved, reporter=reporter
            )
            return {"jobs": [
                {"jobId": jid, "versionCount": len(v),
                 "factCheckPassed": v[-1].fact_check_passed if v else False}
                for jid, v in results.items()
            ]}

    run_id = mgr.submit("tailor", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/cover-letters", response_model=RunOut, status_code=202)
def launch_cover_letters(
    params: CoverLetterParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            results = write_cover_letters(
                session, job_ids=params.job_ids, approved=params.approved, reporter=reporter
            )
            return {"coverLetters": [
                {"jobId": r.job_id, "coverLetterId": r.cover_letter_id,
                 "factCheckPassed": r.fact_check_passed} for r in results
            ]}

    run_id = mgr.submit("coverLetter", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/jobs/from-url", response_model=RunOut, status_code=202)
def launch_add_from_url(
    params: AddJobUrlParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        reporter.begin(1, f"Fetching {params.url}")
        with get_session(engine) as session:
            job = add_job_from_url(
                session, url=params.url, company=params.company, title=params.title,
                location=params.location, allow_browser=params.allow_browser,
            )
            job_id = job.id if job else None
            duplicate = job is None
        reporter.step(1)
        return {"jobId": job_id, "duplicate": duplicate}

    run_id = mgr.submit("addJobUrl", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    record = mgr.get(run_id)
    if record is None:
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    return record_to_run(run_id, record)
```

Add to `src/resume_tailor_harness/api/deps.py`:

```python
def get_run_manager(request: Request):
    return request.app.state.run_manager
```

In `src/resume_tailor_harness/api/app.py`: import `RunManager`; in `create_app`, after CORS, construct and store the manager and include the router:

```python
    from resume_tailor_harness.api.runs.manager import RunManager
    from resume_tailor_harness.api.routers import runs as runs_router

    app.state.run_manager = (
        RunManager(root=runs_root, executor=run_executor)
        if runs_root is not None
        else RunManager(executor=run_executor)
    )
    ...
    app.include_router(runs_router.router, prefix="/api", dependencies=guarded)
```

(`create_app` already accepts `run_executor: Executor | None = None` and `runs_root: Path | str | None = None` from Task 7's signature.)

Also update the lifespan cleanup to stop the owned threadpool:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(resolved_db)
        init_db(engine)
        app.state.engine = engine
        yield
        app.state.run_manager.shutdown()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/sse.py src/resume_tailor_harness/api/routers/runs.py src/resume_tailor_harness/api/deps.py src/resume_tailor_harness/api/app.py tests/api/test_runs_launch.py
git commit -m "feat(api): run launch endpoints + GET run"
```

---

## Task 14: SSE progress stream

**Files:**

- Modify: `src/resume_tailor_harness/api/runs/sse.py` (add async event generator)
- Modify: `src/resume_tailor_harness/api/routers/runs.py` (add `GET /runs/{id}/events`)
- Test: `tests/api/test_runs_sse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_runs_sse.py
import json
from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.routers import runs as runs_router


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        fut.set_result(fn(*args, **kwargs))
        return fut


def test_sse_stream_emits_terminal_event(monkeypatch, tmp_path):
    def fake_discover_jobs(session, *, reporter=None, **kw):
        reporter.begin(1, "scoring"); reporter.step(1)
        return {"shortlisted": 1}

    monkeypatch.setattr(runs_router, "discover_jobs", fake_discover_jobs)
    client = TestClient(
        create_app(db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path)
    )
    with client:
        run_id = client.post("/api/discover", json={}).json()["runId"]
        # InlineExecutor means the run is already terminal; the stream should
        # emit at least one event ending in a done state, then close.
        with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
                    if events[-1]["state"] in ("done", "error"):
                        break
    assert events[-1]["state"] == "done"
    assert events[-1]["percent"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_sse.py -v`
Expected: FAIL (no events route).

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_tailor_harness/api/runs/sse.py`:

```python
import asyncio
import json
from collections.abc import AsyncIterator


async def run_events(mgr, run_id: str, *, poll_interval: float = 0.5) -> AsyncIterator[dict]:
    """Yield sse-starlette event dicts until the run reaches a terminal state.

    Emits an event whenever the projected RunOut changes, plus a final event on
    the terminal record, then stops (closing the stream). A missing record yields
    a single not-found-shaped terminal event so the client never hangs.
    """
    last: str | None = None
    while True:
        record = mgr.get(run_id)
        if record is None:
            yield {"data": json.dumps({"state": "error", "error": "run not found", "percent": 0})}
            return
        run = record_to_run(run_id, record)
        payload = run.model_dump(mode="json", by_alias=True)
        serialized = json.dumps(payload)
        if serialized != last:
            yield {"data": serialized}
            last = serialized
        if run.state in ("done", "error"):
            return
        await asyncio.sleep(poll_interval)
```

Append to `src/resume_tailor_harness/api/routers/runs.py` (import `EventSourceResponse`):

```python
from sse_starlette.sse import EventSourceResponse

from resume_tailor_harness.api.runs.sse import run_events


@router.get("/runs/{run_id}/events")
async def stream_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    if mgr.get(run_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    return EventSourceResponse(run_events(mgr, run_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_sse.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/sse.py src/resume_tailor_harness/api/routers/runs.py tests/api/test_runs_sse.py
git commit -m "feat(api): SSE progress stream for runs"
```

---

# Phase 5 — Contract artifact (OpenAPI + TypeScript client)

## Task 15: OpenAPI export script + committed schema + drift test

**Files:**

- Create: `scripts/export_openapi.py`
- Create: `contracts/openapi.json` (generated, committed)
- Test: `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_openapi_contract.py
import json
from pathlib import Path

from resume_tailor_harness.api.app import create_app

CONTRACT = Path("contracts/openapi.json")


def test_openapi_exposes_core_paths():
    spec = create_app(db_url="sqlite://").openapi()
    paths = spec["paths"]
    for p in ("/api/shortlist", "/api/pipeline", "/api/triage", "/api/jobs/{job_id}",
              "/api/discover", "/api/runs/{run_id}", "/api/runs/{run_id}/events"):
        assert p in paths, f"missing {p}"


def test_committed_openapi_is_current():
    """The committed contract must match the live app — regenerate if this fails."""
    assert CONTRACT.exists(), "run scripts/export_openapi.py and commit contracts/openapi.json"
    live = create_app(db_url="sqlite://").openapi()
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == live, "contracts/openapi.json is stale — re-run scripts/export_openapi.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: FAIL on `test_committed_openapi_is_current` (`contracts/openapi.json` missing).

- [ ] **Step 3: Write the script and generate the contract**

```python
# scripts/export_openapi.py
"""Dump the FastAPI OpenAPI schema to contracts/openapi.json (the published contract)."""

import json
from pathlib import Path

from resume_tailor_harness.api.app import create_app


def main() -> None:
    spec = create_app(db_url="sqlite://").openapi()
    out = Path("contracts/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
```

Run: `.venv/Scripts/python.exe scripts/export_openapi.py`
Expected: writes `contracts/openapi.json`.

Make the drift test deterministic: the live `.openapi()` dict ordering must match the committed file. Since the test compares parsed dicts (`==`), ordering does not matter — only content. Good.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/export_openapi.py contracts/openapi.json tests/api/test_openapi_contract.py
git commit -m "feat(contracts): export + commit OpenAPI schema with drift test"
```

---

## Task 16: Generate + commit the TypeScript client

**Files:**

- Create: `scripts/gen_ts_client.sh`
- Create: `contracts/ts/api.ts` (generated, committed)
- Create: `contracts/README.md`

- [ ] **Step 1: Write the generation script**

```bash
# scripts/gen_ts_client.sh
#!/usr/bin/env bash
# Regenerate the committed TypeScript client from the OpenAPI contract.
# Requires Node (npx). Run after scripts/export_openapi.py.
set -euo pipefail
.venv/Scripts/python.exe scripts/export_openapi.py
mkdir -p contracts/ts
npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
echo "Wrote contracts/ts/api.ts"
```

- [ ] **Step 2: Run it to generate the client**

Run: `bash scripts/gen_ts_client.sh`
Expected: writes `contracts/ts/api.ts` containing a `paths` interface with the core routes (`/api/shortlist`, `/api/discover`, etc.) and `components.schemas` with camelCase fields (`fitScore`, `jobId`).

- [ ] **Step 3: Verify the generated types are camelCase and consumable**

Run: `grep -c "fitScore" contracts/ts/api.ts`
Expected: ≥ 1 (proves camelCase propagated to TS — the contract is frontend-consumable).

- [ ] **Step 4: Write the contracts README**

````markdown
# contracts/

Published API contract for the future React/shadcn frontend.

- `openapi.json` — OpenAPI 3.1 schema, emitted by `scripts/export_openapi.py`.
- `ts/api.ts` — TypeScript types generated by `openapi-typescript`.

## Regenerate (after any API schema change)

```bash
bash scripts/gen_ts_client.sh   # exports openapi.json + regenerates ts/api.ts
```
````

The Python Pydantic models are the single source of truth. `tests/api/test_openapi_contract.py`
fails if `openapi.json` drifts from the live app — regenerate and commit.

The frontend imports these types directly; no API client is hand-written.

````

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_ts_client.sh contracts/ts/api.ts contracts/README.md
git commit -m "feat(contracts): generate + commit TypeScript client"
````

---

# Phase 6 — Wiring + docs

## Task 17: `resume-tailor-harness serve` command + README/CLAUDE.md

**Files:**

- Modify: `src/resume_tailor_harness/cli.py` (add `serve` command)
- Modify: `README.md`, `CLAUDE.md`
- Test: `tests/test_cli_serve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_serve.py
from typer.testing import CliRunner

from resume_tailor_harness import cli


def test_serve_invokes_uvicorn(monkeypatch):
    captured = {}

    def fake_run(app, host, port, **kw):  # uvicorn.run signature (subset)
        captured["host"] = host
        captured["port"] = port

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = CliRunner().invoke(cli.app, ["serve", "--host", "127.0.0.1", "--port", "9123"])
    assert result.exit_code == 0
    assert captured == {"host": "127.0.0.1", "port": 9123}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_serve.py -v`
Expected: FAIL (no `serve` command).

- [ ] **Step 3: Add the command**

Append to `src/resume_tailor_harness/cli.py`:

```python
@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", help="Bind host (use 0.0.0.0 to expose on LAN)."),
    port: int = typer.Option(8000, help="Bind port."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the FastAPI backend (for the React frontend / API clients)."""
    import uvicorn

    from resume_tailor_harness.api.app import create_app

    uvicorn.run(create_app(db_url=db_url), host=host, port=port)
```

- [ ] **Step 4: Run test + full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_serve.py -v && .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -15 && .venv/Scripts/python.exe -m ruff check 2>&1 | tail -5`
Expected: serve test PASS; full suite green; ruff clean.

- [ ] **Step 5: Update docs**

In `README.md`, add an "API server" section: `resume-tailor-harness serve` starts the backend at `http://127.0.0.1:8000`; interactive docs at `/docs`; OpenAPI at `/openapi.json`; the committed contract for the frontend lives in `contracts/`; long ops (`POST /api/discover|pull|tailor|cover-letters|jobs/from-url`) return a run you watch via `GET /api/runs/{id}/events` (SSE) or poll at `GET /api/runs/{id}`; set `API_TOKEN` in `.env` to require a bearer token; set `CORS_ORIGINS` for the frontend dev server.

In `CLAUDE.md`, add an "API layer (`api/`)" section: the API is the third thin adapter over `services/`; Pydantic schemas are the contract source of truth (camelCase via `to_camel`); runs reuse `ProgressReporter` keyed by `run_id` under `data/runs/`; blocking work runs in a threadpool with its own session; regenerate `contracts/` after schema changes (`scripts/gen_ts_client.sh`); deferred (not yet exposed): Gmail sync, analytics, match-gap, profile build, scrape.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/cli.py README.md CLAUDE.md tests/test_cli_serve.py
git commit -m "feat(api): serve command + docs"
```

---

## Self-Review

**Spec coverage** (against locked decisions):

- Single-user/local-first, optional bearer, CORS → Task 6 (Settings), Task 7 (`require_token`, CORS), Task 8 (guard enforcement test). ✓
- Restructure services first → Phase 0 (Tasks 1-5), CLI tests as the net. ✓
- Run + SSE, run_id-keyed ProgressReporter, threadpool + own session → Tasks 12-14. ✓
- FastAPI + Pydantic-as-contract → Phases 1-4; camelCase via `CamelModel` (Task 6). ✓
- Pydantic → generated TS client, committed under `contracts/` → Tasks 15-16. ✓
- Core scope only; Gmail/analytics/match-gap/profile/scrape deferred → noted in header + CLAUDE.md (Task 17); no endpoints added for them. ✓
- Thin paginated lists + core filters → Task 4 (`board`), Task 8 (endpoints). ✓
- Error envelope, FileResponse PDFs, file-based config → Task 6, Task 9, services load files server-side. ✓
- Contract artifact only, no React app → no `../ui` app task; artifact in this repo. ✓

**Type/name consistency checks:**

- `services.pagination.Page` (dataclass) vs `api.schemas.base.Page` (Pydantic, with `Pagination`) are distinct types; `mappers.to_page` converts one to the other. Consistent and intentional. ✓
- `RunOut` fields (`run_id`, `kind`, `state`, `percent`, `eta_text`, `result`, `error`) match `record_to_run` projection and `progress_stats` outputs (`pct`→`percent`, `eta_text`, `state`, `error`). ✓
- `ProgressReporter.done(**extra)` carries `kind`/`result`/`error` → consumed by `record_to_run` via `record.get("kind"/"result")`. ✓
- `AddJobTextRequest` defined in `schemas/runs.py` (Task 10), used by `jobs.create_manual_job`. ✓
- `create_app(run_executor=...)` signature introduced in Task 7, used by Task 13 endpoints + all run tests. ✓
- Board mutation semantics (`set_stage` unconstrained, `delete` guarded by `has_progress`) mirror current CLI/Streamlit behavior. ✓

**Known follow-ups (out of scope, flagged):** Gmail `sync-status`, analytics, match-gap, `profile build`, LinkedIn `scrape`; rich faceted server-side filtering; multi-user/auth; durable task queue. Each is additive on this foundation.
