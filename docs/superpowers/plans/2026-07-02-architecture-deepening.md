# Architecture Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 7 candidates from the 2026-07-02 architecture review: batch the board read-models, batch ingest writes + index dedup lookups, collapse the connector registry to a spec table, cache facts/aliases loads, fetch connectors concurrently, retry only transient LLM failures, and derive the board facet vocabulary from one table.

**Architecture:** Every change deepens an existing seam without changing its public interface — callers and the wire contract stay untouched, so the existing test suite doubles as the conformance check. DB work batches N+1 loops into constant-query loaders (the `_progressed_job_ids` pattern already in-repo); the registry and facet work replace hand-enumerated branching with data tables; concurrency reuses `gather_isolated`; retry moves from agno's bare-`Exception` policy into `AgentRunner` behind a transient-only predicate.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy (SQLite), FastAPI, agno, asyncio, pytest (offline suite — all agents/browsers faked).

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline — no API key, no network). Lint: `ruff check`.
- No new dependencies.
- The wire format (camelCase Pydantic schemas, facet keys like `employmentType`) must not change — none of these tasks may alter `contracts/openapi.json`.
- Core invariants from CLAUDE.md hold: source-priority upgrade-not-drop, archived rows excluded from dedupe, `has_progress` as the single irreversible-path gate, worker-owns-its-session.
- Ingest order = canonical dedup order (connector list order). Task 6 must preserve it.
- Commit after every task (style: present-tense third person, e.g. "Batches board read-model queries").

## Source findings this plan is built on (verified 2026-07-02)

| #   | Finding                                                                                                                                                                                                                                                                                                                                 | Evidence                                                                        |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1   | `pipeline_rows` issues `best_resume_version` (1 query) + `application_for_job` (1) + `has_progress` (up to 4) **per job**; `triage_rows`/`archived_rows` issue `has_progress` per job. `_progressed_job_ids` (repository.py:346) already demonstrates the 3-query batched fix.                                                          | `src/resume_agent/tracking/queries.py:295-393`, `repository.py:333-355`         |
| 2   | `ingest_jobs_with_outcomes` → `save_or_upgrade` → `save_job` commits **once per RawJob**; `find_existing` probes `Job.url` (unindexed) and `Job.jd_text` (unindexed) with full scans. `content_fingerprint` **is** indexed and is a pure function of `jd_text` (`compute_content_fingerprint`), so equal `jd_text` ⇒ equal fingerprint. | `ingest.py:128-170`, `repository.py:52-86`, `tables.py:42-54`, `dedup.py:47-52` |
| 3   | `registry.py` hand-enumerates all 7 connector kinds in two near-duplicate builders (`build_connectors`, `build_source_connectors`); adding an ATS touches both plus imports.                                                                                                                                                            | `registry.py:15-116`                                                            |
| 4   | `load_facts` re-reads + re-validates `facts.json` on every board/detail request (`services/board.py:280,324`); `load_aliases` re-reads on every `shortlist_rows`/`job_facets`/`job_detail_row` call.                                                                                                                                    | `profile/store.py:34-36`, `taxonomy/skills.py:56-61`                            |
| 5   | `run_pull` fetches connectors serially; pull latency = Σ connector latencies. `gather_isolated` exists for exactly this fan-out shape.                                                                                                                                                                                                  | `connectors/runner.py:67-125`, `concurrency.py:28`                              |
| 6   | `retry_kwargs()` gives agno `retries=llm_retries` which retries bare `Exception` (auth/schema failures burn retries × tokens); spread into 21 `Agent(...)` builders. `pipeline.py:160-165` swallows `classify_industries` outages with a silent `except Exception: additions = {}`.                                                     | `llm_runner.py:266-273`, `discovery/pipeline.py:158-165`                        |
| 7   | The facet vocabulary is stated 4 times in `services/board.py`: `BoardFilter` fields, `_row_value`, the `set_filters` tuple in `_passes_filter`, and the key tuple in `board_facets`. Drift = silent filter bug.                                                                                                                         | `services/board.py:53-74,101-124,171-183,244-265`                               |

Task order is safest-first and keeps the two tasks that touch `repository.py` (1 and 2) adjacent. Tasks are otherwise independent.

---

### Task 1: Batch the board read-models

**Files:**

- Modify: `src/resume_agent/tracking/repository.py` (add batched loaders near `_progressed_job_ids`, repository.py:346)
- Modify: `src/resume_agent/tracking/queries.py:295-393` (`pipeline_rows`, `_triage_row`, `triage_rows`, `archived_rows`)
- Test: `tests/test_tracking_queries.py` (append)

**Interfaces:**

- Consumes: existing `pick_best(versions) -> BestResume`, `_PROGRESS_STATUSES` (both already in repository.py).
- Produces (new public functions in `resume_agent.tracking.repository`):
  - `versions_by_job(session: Session) -> dict[int, list[ResumeVersion]]`
  - `applications_by_job(session: Session) -> dict[int, Application]`
  - `progressed_job_ids(session: Session) -> set[int]` (rename of `_progressed_job_ids`; update its one internal caller `_prune_rows`)
  - `job_has_progress(job: Job, progressed: set[int]) -> bool`
- `pipeline_rows` / `triage_rows` / `archived_rows` signatures and returned DTOs are **unchanged** — existing tests are the conformance check.

- [ ] **Step 1: Write the failing constant-query-count test**

Append to `tests/test_tracking_queries.py`:

```python
from sqlalchemy import event

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.queries import pipeline_rows, triage_rows
from resume_agent.tracking.tables import Application, Job, JobStatus, ResumeVersion


def _seeded_engine(job_count: int):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for i in range(job_count):
            job = Job(
                source="greenhouse",
                company=f"Co{i}",
                title=f"Role {i}",
                jd_text=f"jd {i}",
                status=JobStatus.tailored.value if i % 2 else JobStatus.raw.value,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            if i % 2:
                session.add(ResumeVersion(job_id=job.id, round=1, fact_check_passed=True))
                session.add(Application(job_id=job.id, status="ready"))
                session.commit()
    return engine


def _select_count(engine, fn) -> int:
    counts = {"n": 0}

    def _tally(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counts["n"] += 1

    event.listen(engine, "before_cursor_execute", _tally)
    try:
        with Session(engine) as session:
            fn(session)
    finally:
        event.remove(engine, "before_cursor_execute", _tally)
    return counts["n"]


def test_pipeline_rows_query_count_is_constant():
    small = _select_count(_seeded_engine(2), pipeline_rows)
    large = _select_count(_seeded_engine(12), pipeline_rows)
    assert small == large  # no per-job queries


def test_triage_rows_query_count_is_constant():
    small = _select_count(_seeded_engine(2), triage_rows)
    large = _select_count(_seeded_engine(12), triage_rows)
    assert small == large
```

(If `Session` is not already imported at the top of the test file, add `from sqlmodel import Session`.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v -k query_count`
Expected: both FAIL — the large seeding issues more SELECTs than the small one (per-job N+1).

- [ ] **Step 3: Add the batched loaders to repository.py**

In `src/resume_agent/tracking/repository.py`, rename `_progressed_job_ids` → `progressed_job_ids` (update the docstring's first line to "Job ids owning any child row, resolved in one query per child table." and its single caller in `_prune_rows`), then add below it:

```python
def versions_by_job(session: Session) -> dict[int, list[ResumeVersion]]:
    """Every resume version grouped by job_id — one query for whole-board reads."""
    grouped: dict[int, list[ResumeVersion]] = {}
    for version in session.exec(select(ResumeVersion)).all():
        grouped.setdefault(version.job_id, []).append(version)
    return grouped


def applications_by_job(session: Session) -> dict[int, Application]:
    """Lowest-id application per job — the batched mirror of application_for_job()."""
    id_col = cast(Any, Application.id)
    grouped: dict[int, Application] = {}
    for application in session.exec(select(Application).order_by(id_col)).all():
        grouped.setdefault(application.job_id, application)
    return grouped


def job_has_progress(job: Job, progressed: set[int]) -> bool:
    """Batched counterpart of has_progress(): same rule, zero per-job queries."""
    return job.status in _PROGRESS_STATUSES or (job.id is not None and job.id in progressed)
```

Note: `application_for_job` is `.first()` with no ORDER BY — SQLite returns rowid order, so `order_by(id)` + first-write-wins in `setdefault` picks the same row deterministically.

- [ ] **Step 4: Rewrite the two hot read-models in queries.py**

In `src/resume_agent/tracking/queries.py`, change the repository import block to:

```python
from resume_agent.tracking.repository import (
    application_for_job,
    applications_by_job,
    cover_letters_for_job,
    has_progress,
    job_has_progress,
    pick_best,
    progressed_job_ids,
    resume_versions_for_job,
    versions_by_job,
)
```

(`best_resume_version` is no longer imported — `pipeline_rows` was its only caller here; `job_detail_row` already uses `resume_versions_for_job` + `pick_best` directly and stays as-is.)

Replace the body of `pipeline_rows`:

```python
def pipeline_rows(session: Session) -> list[PipelineRow]:
    status_col = cast(Any, Job.status)
    company_col = cast(Any, Job.company)
    title_col = cast(Any, Job.title)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(archived_col.is_(None))
        .order_by(status_col, company_col, title_col)
    ).all()
    versions = versions_by_job(session)
    applications = applications_by_job(session)
    progressed = progressed_job_ids(session)
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        best = pick_best(versions.get(job_id, []))
        version = best.version
        application = applications.get(job_id)
        rows.append(
            PipelineRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                status=job.status,
                fit_score=job.fit_score,
                jd_text=clean_job_description_text(job.jd_text),
                # None means "never tailored" (no version); [] means a version
                # exists but reviewers raised nothing. The board reads them apart.
                critique_json=(version.critique_json or []) if version else None,
                # The surfaced version's own PDF, not any job's latest-rendered
                # round — otherwise a clean older round can pair with a PDF
                # from an unrelated (regressed) later round.
                pdf_path=version.pdf_path if version else None,
                application_status=application.status if application else None,
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                has_progress=job_has_progress(job, progressed),
                needs_attention=best.no_clean_round,
                regressed=best.regressed,
            )
        )
    return rows
```

Change `_triage_row` to take the precomputed set instead of a session, and update both callers:

```python
def _triage_row(job: Job, progressed: set[int]) -> TriageRow:
    job_id = _require_job_id(job)
    return TriageRow(
        job_id=job_id,
        company=job.company,
        title=job.title,
        location=job.location,
        source=job.source,
        status=job.status,
        fit_score=job.fit_score,
        posted_at=job.posted_at,
        archived_at=job.archived_at,
        has_progress=job_has_progress(job, progressed),
        reject_reason=job.reject_reason,
    )


def triage_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    status_col = cast(Any, Job.status)
    jobs = session.exec(
        select(Job)
        .where(status_col.in_(_TRIAGE_STATUSES), archived_col.is_(None))
        .order_by(cast(Any, Job.fit_score).asc().nullsfirst())
    ).all()
    progressed = progressed_job_ids(session)
    return [_triage_row(job, progressed) for job in jobs]


def archived_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job).where(archived_col.is_not(None)).order_by(archived_col.desc())
    ).all()
    progressed = progressed_job_ids(session)
    return [_triage_row(job, progressed) for job in jobs]
```

- [ ] **Step 5: Run the new tests, then the conformance suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py tests/test_services_board.py tests/test_repository.py tests/test_prune_run.py tests/api -v`
Expected: all PASS. The pre-existing DTO tests prove the projection didn't change; the query-count tests prove the batching.

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/tracking/repository.py src/resume_agent/tracking/queries.py tests/test_tracking_queries.py
git commit -m "Batches board read-model queries to constant count"
```

---

### Task 2: Batch ingest writes + index the dedup probes

**Files:**

- Modify: `src/resume_agent/tracking/tables.py:42` (`Job.url` gains `index=True`)
- Modify: `src/resume_agent/tracking/migrate.py` (add `ensure_url_index`)
- Modify: `src/resume_agent/db.py:54-63` (wire `ensure_url_index` into `init_db`)
- Modify: `src/resume_agent/tracking/repository.py:52-86` (`find_existing` jd probe uses the fingerprint index)
- Modify: `src/resume_agent/discovery/ingest.py` (one commit per batch)
- Modify: `src/resume_agent/discovery/connectors/runner.py:114-120` (rollback on failed connector ingest)
- Test: `tests/test_migrate.py`, `tests/test_ingest_jobs.py` (append)

**Interfaces:**

- Consumes: `compute_content_fingerprint(jd_text) -> str | None` (`tracking/dedup.py:47`), existing `IncomingJob` / `decide` merge seam.
- Produces: `save_or_upgrade(..., commit: bool = True)` — new keyword-only param, default preserves every existing caller. `find_existing` signature unchanged. `ingest_jobs_with_outcomes` signature unchanged, now transactional (one commit per call).
- Invariant relied on: every persisted `Job` carries `content_fingerprint` (the Insert/Rebase/RefreshText paths set it from `jd_text`, and `ensure_content_fingerprint_column` backfills legacy rows), so prefiltering the exact-`jd_text` probe by fingerprint cannot change which row matches.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrate.py`:

```python
def test_url_index_created(tmp_path):
    from sqlalchemy import text

    from resume_agent.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'idx.db'}")
    init_db(engine)
    with engine.begin() as conn:
        names = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
    assert "ix_jobs_url" in names
```

Append to `tests/test_ingest_jobs.py` (reuse that file's existing session fixture/helpers for constructing a `Session`; the `RawJob` import already exists there):

```python
def test_ingest_batch_commits_once(session):
    raws = [
        RawJob(source="greenhouse", company="Acme", title=f"Engineer {i}", jd_text=f"jd {i}")
        for i in range(3)
    ]
    commits = []
    original_commit = session.commit

    def counting_commit():
        commits.append(1)
        original_commit()

    session.commit = counting_commit  # type: ignore[method-assign]
    counts = ingest_jobs_with_outcomes(session, raws)
    session.commit = original_commit  # type: ignore[method-assign]
    assert counts.added == {"greenhouse": 3}
    assert len(commits) == 1


def test_ingest_dedupes_within_uncommitted_batch(session):
    raw = RawJob(source="greenhouse", company="Acme", title="Engineer", jd_text="same jd")
    counts = ingest_jobs_with_outcomes(session, [raw, raw])
    assert counts.added == {"greenhouse": 1}
    assert counts.skipped == {"greenhouse": 1}
```

(If `tests/test_ingest_jobs.py` has no session fixture, create one inline at the top of the appended block: `make_engine("sqlite://")` + `init_db` + `Session(engine)` — mirroring Task 1's `_seeded_engine`.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate.py::test_url_index_created "tests/test_ingest_jobs.py::test_ingest_batch_commits_once" "tests/test_ingest_jobs.py::test_ingest_dedupes_within_uncommitted_batch" -v`
Expected: `test_url_index_created` FAILS (no `ix_jobs_url`); `test_ingest_batch_commits_once` FAILS (3 commits); the dedupe test may already pass (commit-per-row also makes rows visible) — that's fine, it pins the flush-visibility behavior the batching must keep.

- [ ] **Step 3: Add the index (model + migration)**

`src/resume_agent/tracking/tables.py:42`:

```python
    url: str | None = Field(default=None, index=True)
```

`src/resume_agent/tracking/migrate.py`, append:

```python
def ensure_url_index(engine: Engine) -> None:
    """Idempotently index jobs.url (find_existing's first dedupe probe)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_url ON jobs (url)"))
```

`src/resume_agent/db.py`: import `ensure_url_index` alongside the other `ensure_*` imports and append `ensure_url_index(engine)` at the end of `init_db`.

- [ ] **Step 4: Use the fingerprint index for the exact-JD probe**

In `src/resume_agent/tracking/repository.py`, add the import `from resume_agent.tracking.dedup import compute_content_fingerprint` and replace the `if jd_text:` block of `find_existing` with:

```python
    if jd_text:
        # Equal jd_text implies equal content_fingerprint (a pure function of
        # jd_text), so the indexed fingerprint column narrows the scan without
        # changing which row matches; jd_text equality stays the real predicate.
        fingerprint = compute_content_fingerprint(jd_text)
        conditions = [Job.jd_text == jd_text, archived_col.is_(None)]
        if fingerprint:
            conditions.insert(0, Job.content_fingerprint == fingerprint)
        by_jd = session.exec(select(Job).where(*conditions)).first()
        if by_jd is not None:
            return by_jd
```

- [ ] **Step 5: Batch the commits in ingest.py**

In `src/resume_agent/discovery/ingest.py`:

1. Drop the `save_job` import (`from resume_agent.tracking.repository import find_existing`) and add a local persist helper:

```python
def _persist(session: Session, job: Job, commit: bool) -> Job:
    session.add(job)
    if commit:
        session.commit()
        session.refresh(job)
    else:
        # flush() assigns the id and makes the row visible to find_existing
        # for later items in the same batch, without ending the transaction.
        session.flush()
    return job
```

1. Thread a `commit` flag through `save_or_upgrade` and `_apply` (defaults keep `add_job` and every other existing caller commit-per-call):

```python
def save_or_upgrade(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    posted_at: datetime | None = None,
    commit: bool = True,
) -> tuple[Job | None, IngestOutcome]:
```

…pass `commit` to `_apply(session, existing, incoming, decide(existing, incoming), commit)`, and in `_apply` replace both `save_job(session, job)` / `save_job(session, existing)` calls with `_persist(session, job, commit)` / `_persist(session, existing, commit)` (add `commit: bool` as `_apply`'s last parameter).

1. In `ingest_jobs_with_outcomes`, pass `commit=False` in the per-row `save_or_upgrade(...)` call and add a single `session.commit()` immediately before the `return IngestCounts(...)` statement.

- [ ] **Step 6: Roll back a failed connector batch in run_pull**

In `src/resume_agent/discovery/connectors/runner.py`, the `except Exception as exc:` branch of `run_pull` (line 114) gains a rollback as its first statement so a mid-batch crash leaves no partial rows pending on the shared session:

```python
        except Exception as exc:
            session.rollback()
            record_run(
                telemetry_path,
                connector.name,
                added=0,
                error=f"{type(exc).__name__}: {exc}",
            )
```

- [ ] **Step 7: Run the new tests, then the ingest/dedup conformance suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate.py tests/test_ingest_jobs.py tests/test_discovery_ingest.py tests/test_discovery_merge.py tests/test_repository.py tests/test_tracking_dedup.py -v`
Expected: all PASS. If any fixture hand-crafts a `Job` with `jd_text` but **no** `content_fingerprint` and relies on the exact-JD dedupe branch, the fingerprint prefilter is still correct for it (the incoming fingerprint filters DB rows; a NULL-fingerprint row simply won't match) — such a fixture must be updated to set `content_fingerprint=compute_content_fingerprint(jd_text)`, which is what production inserts always do.

- [ ] **Step 8: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/tracking/tables.py src/resume_agent/tracking/migrate.py src/resume_agent/db.py src/resume_agent/tracking/repository.py src/resume_agent/discovery/ingest.py src/resume_agent/discovery/connectors/runner.py tests/test_migrate.py tests/test_ingest_jobs.py
git commit -m "Batches ingest commits and indexes dedup probes"
```

---

### Task 3: Connector registry as a data table

**Files:**

- Modify: `src/resume_agent/discovery/connectors/registry.py` (full rewrite around `ConnectorSpec`)
- Test: `tests/test_connectors_registry.py` (existing tests are the conformance gate; append one drift test)

**Interfaces:**

- Consumes: all existing connector constructors and id helpers already imported by registry.py (`GreenhouseConnector`, `LeverConnector`, `CompaniesConnector`, `DashboardScraper`, `RemoteOKConnector`, `AdzunaConnector`, `build_linkedin_scraper`, `company_url_id`, `host_key`).
- Produces: `build_connectors(config, settings)` and `build_source_connectors(config, settings, source_ids=None)` — **signatures and output order unchanged** (spec table order = today's canonical dedup order). New exported types: `ConnectorUnit`, `ConnectorSpec`, `CONNECTOR_SPECS`.
- To add a new ATS after this task: append one `ConnectorSpec` entry. Nothing else.

- [ ] **Step 1: Run the existing registry tests to baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py -v`
Expected: PASS (baseline — these must still pass after the rewrite, unmodified).

- [ ] **Step 2: Rewrite registry.py around a spec table**

Replace the entire body of `src/resume_agent/discovery/connectors/registry.py` with:

```python
from dataclasses import dataclass, field
from typing import Any, Callable

from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.base import Connector
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.connectors.sources import company_url_id
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.scraper.recipe_store import host_key


@dataclass(frozen=True)
class ConnectorUnit:
    """One pullable sub-source of a connector kind (a board, URL, target, or the
    whole singleton), addressable by its stable source id."""

    source_id: str
    enabled: bool
    payload: Any  # board / url / target object; None for singleton kinds


@dataclass(frozen=True)
class ConnectorSpec:
    """Everything the registry knows about one connector kind.

    ``build`` receives the enabled payloads — all of them for the aggregate
    builder, exactly one for the per-source builder — so both public builders
    collapse to loops over this table. Table order is the canonical dedup order.
    """

    kind: str
    section_enabled: Callable[[ConnectorsConfig], bool]
    units: Callable[[ConnectorsConfig], list[ConnectorUnit]]
    build: Callable[[list[Any], ConnectorsConfig, Settings], Connector]
    pullable: Callable[[Settings], bool] = field(default=lambda settings: True)


CONNECTOR_SPECS: tuple[ConnectorSpec, ...] = (
    ConnectorSpec(
        kind="greenhouse",
        section_enabled=lambda c: c.greenhouse.enabled,
        units=lambda c: [
            ConnectorUnit(f"greenhouse:{b.token}", b.enabled, b) for b in c.greenhouse.boards
        ],
        build=lambda payloads, c, s: GreenhouseConnector(payloads),
    ),
    ConnectorSpec(
        kind="lever",
        section_enabled=lambda c: c.lever.enabled,
        units=lambda c: [
            ConnectorUnit(f"lever:{b.token}", b.enabled, b) for b in c.lever.boards
        ],
        build=lambda payloads, c, s: LeverConnector(payloads),
    ),
    ConnectorSpec(
        kind="companies",
        section_enabled=lambda c: c.companies.enabled,
        units=lambda c: [
            ConnectorUnit(company_url_id(e.url), e.enabled, e.url) for e in c.companies.urls
        ],
        build=lambda payloads, c, s: CompaniesConnector(payloads),
    ),
    ConnectorSpec(
        kind="scrape",
        section_enabled=lambda c: c.scrape.enabled,
        units=lambda c: [
            ConnectorUnit(f"scrape:{host_key(t.url)}", t.enabled, t) for t in c.scrape.targets
        ],
        build=lambda payloads, c, s: DashboardScraper(payloads),
    ),
    ConnectorSpec(
        kind="remoteok",
        section_enabled=lambda c: c.remoteok.enabled,
        units=lambda c: [ConnectorUnit("remoteok", c.remoteok.enabled, None)],
        build=lambda payloads, c, s: RemoteOKConnector(),
    ),
    ConnectorSpec(
        kind="adzuna",
        section_enabled=lambda c: c.adzuna.enabled,
        units=lambda c: [ConnectorUnit("adzuna", c.adzuna.enabled, None)],
        build=lambda payloads, c, s: AdzunaConnector(
            s.adzuna_app_id, s.adzuna_app_key, c.adzuna.country
        ),
        pullable=lambda s: bool(s.adzuna_app_id and s.adzuna_app_key),
    ),
    ConnectorSpec(
        kind="linkedin",
        section_enabled=lambda c: c.linkedin.enabled,
        units=lambda c: [ConnectorUnit("linkedin", c.linkedin.enabled, None)],
        build=lambda payloads, c, s: build_linkedin_scraper(),
    ),
)


def build_connectors(config: ConnectorsConfig, settings: Settings) -> list[Connector]:
    """Instantiate enabled connectors in canonical dedup order."""
    connectors: list[Connector] = []
    for spec in CONNECTOR_SPECS:
        if not spec.section_enabled(config) or not spec.pullable(settings):
            continue
        payloads = [unit.payload for unit in spec.units(config) if unit.enabled]
        if not payloads:
            continue
        connectors.append(spec.build(payloads, config, settings))
    return connectors


def _named(connector: Connector, source_id: str) -> Connector:
    connector.name = source_id
    return connector


def build_source_connectors(
    config: ConnectorsConfig,
    settings: Settings,
    source_ids: list[str] | None = None,
) -> list[Connector]:
    """Build one connector per enabled, pullable, selected source."""
    selected = set(source_ids) if source_ids is not None else None
    connectors: list[Connector] = []
    for spec in CONNECTOR_SPECS:
        if not spec.section_enabled(config) or not spec.pullable(settings):
            continue
        for unit in spec.units(config):
            if not unit.enabled:
                continue
            if selected is not None and unit.source_id not in selected:
                continue
            connectors.append(
                _named(spec.build([unit.payload], config, settings), unit.source_id)
            )
    return connectors
```

Behavioral notes to preserve (all encoded above — verify, don't re-derive):

- Aggregate builder: a multi-unit kind with zero enabled units appends nothing (the `if not payloads` guard); a singleton kind contributes `payloads == [None]` when enabled, so it always builds.
- Old `build_connectors` gated adzuna on keys, old `build_source_connectors` gated it via `pullable` — both now flow through `spec.pullable`.
- Singleton `unit.enabled` mirrors its section flag, so per-source selection (`source_ids=["remoteok"]`) behaves exactly as before.

- [ ] **Step 3: Add the drift test**

Append to `tests/test_connectors_registry.py`:

```python
def test_spec_table_is_the_single_enumeration():
    from resume_agent.discovery.connectors.registry import CONNECTOR_SPECS

    kinds = [spec.kind for spec in CONNECTOR_SPECS]
    assert kinds == [
        "greenhouse", "lever", "companies", "scrape", "remoteok", "adzuna", "linkedin",
    ]  # canonical dedup order
    assert len(set(kinds)) == len(kinds)
```

- [ ] **Step 4: Run the conformance + drift tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py tests/test_cli_sources.py tests/test_connector_sources.py tests/test_connectors_config.py -v`
Expected: all PASS with zero edits to the pre-existing tests. If any pre-existing registry test fails, the rewrite has a semantic drift — fix the registry, never the test.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/connectors/registry.py tests/test_connectors_registry.py
git commit -m "Collapses connector registry to one spec table"
```

---

### Task 4: mtime-keyed caches for load_facts / load_aliases

**Files:**

- Modify: `src/resume_agent/profile/store.py:34-36`
- Modify: `src/resume_agent/taxonomy/skills.py:56-61`
- Test: `tests/test_taxonomy_skills.py` (append), Create: `tests/test_profile_store_cache.py`

**Interfaces:**

- Consumes: nothing new.
- Produces: `load_facts(path) -> ProfileFacts` and `load_aliases(path) -> dict[str, str]` — signatures, error behavior (missing facts file still raises `FileNotFoundError`; missing aliases file still returns `{}`), and return types unchanged. New contract: **returned objects are shared and must be treated as read-only** (verified by grep in Step 4).

- [ ] **Step 1: Write the failing cache tests**

Create `tests/test_profile_store_cache.py`:

```python
import os

import pytest

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.store import load_facts, save_facts


def test_load_facts_caches_until_file_changes(tmp_path):
    path = tmp_path / "facts.json"
    save_facts(ProfileFacts(), path)
    first = load_facts(path)
    assert load_facts(path) is first  # unchanged file -> cached object

    # save_facts replaces the file (new mtime/size) -> cache invalidates
    os.utime(path, ns=(os.stat(path).st_mtime_ns + 1_000_000,) * 2)
    assert load_facts(path) is not first


def test_load_facts_missing_file_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_facts(tmp_path / "absent.json")
```

(If `ProfileFacts()` requires fields, construct the minimal valid instance the way existing profile tests do — check `tests/test_profile_validate.py` for the smallest fixture and reuse it.)

Append to `tests/test_taxonomy_skills.py`:

```python
def test_load_aliases_caches_until_file_changes(tmp_path):
    import json
    import os

    from resume_agent.taxonomy.skills import load_aliases

    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"js": "javascript"}), "utf-8")
    first = load_aliases(path)
    assert load_aliases(path) is first

    path.write_text(json.dumps({"js": "javascript", "ts": "typescript"}), "utf-8")
    os.utime(path, ns=(os.stat(path).st_mtime_ns + 1_000_000,) * 2)
    assert load_aliases(path)["ts"] == "typescript"


def test_load_aliases_missing_file_returns_empty(tmp_path):
    from resume_agent.taxonomy.skills import load_aliases

    assert load_aliases(tmp_path / "absent.json") == {}
```

- [ ] **Step 2: Run to verify the identity assertions fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_store_cache.py tests/test_taxonomy_skills.py -v -k cache`
Expected: FAIL on the `is first` assertions (every call currently re-parses).

- [ ] **Step 3: Implement both caches**

`src/resume_agent/profile/store.py` — replace `load_facts`:

```python
_FACTS_CACHE: dict[Path, tuple[int, int, ProfileFacts]] = {}


def load_facts(path: str | Path) -> ProfileFacts:
    """Read ProfileFacts from a JSON file, cached on (mtime_ns, size).

    The returned model is shared across callers — treat it as read-only.
    save_facts() replaces the file atomically, which bumps the key.
    """
    resolved = Path(path).resolve()
    stat = resolved.stat()
    cached = _FACTS_CACHE.get(resolved)
    if cached is not None and (cached[0], cached[1]) == (stat.st_mtime_ns, stat.st_size):
        return cached[2]
    facts = ProfileFacts.model_validate_json(resolved.read_text(encoding="utf-8"))
    _FACTS_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, facts)
    return facts
```

`src/resume_agent/taxonomy/skills.py` — replace `load_aliases`:

```python
_ALIAS_CACHE: dict[Path, tuple[int, int, dict[str, str]]] = {}


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load the token->canonical map; missing file -> empty (identity).

    Cached on (mtime_ns, size); the returned dict is shared — treat it as
    read-only (merge_aliases already copies before mutating).
    """
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return {}
    resolved = p.resolve()
    cached = _ALIAS_CACHE.get(resolved)
    if cached is not None and (cached[0], cached[1]) == (stat.st_mtime_ns, stat.st_size):
        return cached[2]
    data = json.loads(p.read_text("utf-8"))
    _ALIAS_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, data)
    return data
```

- [ ] **Step 4: Verify no caller mutates the shared returns**

Run: `grep -rn "load_facts(\|load_aliases(" src/resume_agent --include=*.py`
Inspect each call site: confirm none assigns into the returned dict/model (`aliases[...] =`, `facts.x =`, `.append(`, `.update(` on the return). Known-safe today: `merge_aliases` copies (`merged = dict(new)`), `queries.py` only reads. If a mutating caller exists, give it a copy at that call site (`dict(load_aliases(...))`) — do not weaken the cache.

- [ ] **Step 5: Run the new tests + everything touching facts/aliases**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_store_cache.py tests/test_taxonomy_skills.py tests/test_tracking_queries.py tests/test_services_board.py tests/api -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/profile/store.py src/resume_agent/taxonomy/skills.py tests/test_profile_store_cache.py tests/test_taxonomy_skills.py
git commit -m "Caches facts and alias loads on file mtime"
```

---

### Task 5: One facet table in the Board seam

**Files:**

- Modify: `src/resume_agent/services/board.py:89-265` (`_row_value`, `_passes_filter`, `board_facets`)
- Test: `tests/test_services_board.py` (existing tests are the conformance gate; append one drift test)

**Interfaces:**

- Consumes: `BoardFilter` (unchanged — its fields stay explicit for the API layer).
- Produces: `FacetSpec` dataclass + `FACET_SPECS` tuple exported from `services.board`; `_row_value`, `_passes_filter`, `board_facets` behavior identical (wire facet keys — `source`…`companySize` camelCase — unchanged, so no OpenAPI regen).

- [ ] **Step 1: Baseline the board tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v`
Expected: PASS (must still pass unmodified after the change).

- [ ] **Step 2: Introduce the table and derive the three call sites**

In `src/resume_agent/services/board.py`, immediately after the `BulkResult` dataclass, add:

```python
@dataclass(frozen=True)
class FacetSpec:
    """One facet: its wire key, the row attribute it reads, and the BoardFilter
    field that selects on it. The single statement of the facet vocabulary —
    _row_value, _passes_filter, and board_facets all derive from this table."""

    key: str          # camelCase wire key (facet payload + filter query param)
    row_attr: str     # attribute on the row DTO
    filter_attr: str  # field name on BoardFilter
    skip_unset_rows: bool = False  # rows without the value pass the filter


FACET_SPECS: tuple[FacetSpec, ...] = (
    FacetSpec("source", "source", "source"),
    FacetSpec("status", "status", "status"),
    FacetSpec("remote", "remote_policy", "remote"),
    FacetSpec("sponsorship", "sponsorship_signal", "sponsorship"),
    FacetSpec("seniority", "seniority", "seniority"),
    FacetSpec("employmentType", "employment_type", "employment_type"),
    FacetSpec("industry", "industry", "industry", skip_unset_rows=True),
    FacetSpec("country", "location_country", "country"),
    FacetSpec("region", "location_region", "region"),
    FacetSpec("city", "location_city", "city"),
    FacetSpec("companySize", "company_size", "company_size"),
)

_FACETS_BY_KEY = {spec.key: spec for spec in FACET_SPECS}
```

Replace `_row_value` (the 11-branch if-chain):

```python
def _row_value(row: Any, key: str) -> str | None:
    spec = _FACETS_BY_KEY.get(key)
    if spec is None:
        return None
    return getattr(row, spec.row_attr, None)
```

In `_passes_filter`, replace the `set_filters = (...)` tuple **and** its `for key, raw_selected in set_filters:` loop with:

```python
    for spec in FACET_SPECS:
        selected = _selected(getattr(f, spec.filter_attr))
        value = getattr(row, spec.row_attr, None)
        if spec.skip_unset_rows and value is None:
            continue
        if selected and value not in selected:
            return False
```

(The original loop's `if key == "industry" and value is None: continue` special case is now the `skip_unset_rows` flag. Note the original checked it _before_ the `selected and value not in selected` test — the replacement preserves that order.)

In `board_facets`, replace the hardcoded key tuple:

```python
def board_facets(rows: list[Any]) -> Facets:
    facets: Facets = {}
    for spec in FACET_SPECS:
        counts = _count_values(rows, spec.key)
        if counts:
            facets[spec.key] = counts
    skills = _count_skills(rows)
    if skills:
        facets["skills"] = skills
    return facets
```

- [ ] **Step 3: Add the drift test**

Append to `tests/test_services_board.py`:

```python
def test_facet_specs_match_board_filter_fields():
    import dataclasses

    from resume_agent.services.board import FACET_SPECS, BoardFilter

    filter_fields = {f.name for f in dataclasses.fields(BoardFilter)}
    keys = [spec.key for spec in FACET_SPECS]
    assert len(set(keys)) == len(keys)
    for spec in FACET_SPECS:
        assert spec.filter_attr in filter_fields, spec.key
```

- [ ] **Step 4: Run conformance + contract gate**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py tests/api -v`
Expected: all PASS with zero edits to pre-existing tests (`tests/api/test_openapi_contract.py` proves the wire contract is untouched).

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/board.py tests/test_services_board.py
git commit -m "Derives board facet vocabulary from one spec table"
```

---

### Task 6: Concurrent connector fetch in run_pull

**Files:**

- Modify: `src/resume_agent/config.py` (add `pull_concurrency` next to `llm_concurrency`, config.py:36)
- Modify: `src/resume_agent/discovery/connectors/base.py` (class attribute `concurrent_fetch: bool = True` on `Connector`)
- Modify: `src/resume_agent/discovery/scraper/dashboard.py`, `src/resume_agent/discovery/scraper/linkedin.py` (or wherever its scraper class lives — grep `build_linkedin_scraper`), `src/resume_agent/discovery/connectors/adzuna.py` (set `concurrent_fetch = False` — they drive a real browser)
- Modify: `src/resume_agent/discovery/connectors/runner.py` (fetch phase fans out; ingest phase stays serial)
- Test: `tests/test_pull_runner_concurrency.py` (create)

**Interfaces:**

- Consumes: `gather_isolated(items, fn) -> list[Result]` (`concurrency.py:28` — ordered, error-isolated), `Result.ok/.value/.error`.
- Produces: `run_pull` signature and `PullReport` unchanged. New `Settings.pull_concurrency: int` (default 4, `ge=1`). New `Connector.concurrent_fetch: bool` class attribute (default `True`; browser-driven connectors opt out and are serialized among themselves).
- Invariants preserved: ingest happens **serially, on the calling thread, in connector-list order** (canonical dedup order — Task 2's single Session batching depends on this); per-connector failure isolation and telemetry unchanged; `skip_seen` closes over a prebuilt read-only index (dict lookups — safe to share across fetch threads).

- [ ] **Step 1: Write the failing overlap test**

Create `tests/test_pull_runner_concurrency.py`:

```python
import threading

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.runner import run_pull
from resume_agent.discovery.search_config import SearchConfig


class _HandshakeConnector:
    """fetch() blocks until its peer has also started -> only passes if the two
    fetches run concurrently."""

    concurrent_fetch = True

    def __init__(self, name: str, mine: threading.Event, peer: threading.Event):
        self.name = name
        self._mine = mine
        self._peer = peer

    def fetch(self, search, limit=None, skip_seen=None) -> FetchResult:
        self._mine.set()
        assert self._peer.wait(timeout=10), "peer fetch never started concurrently"
        return FetchResult(
            jobs=[RawJob(source=self.name, company="Acme", title=f"{self.name} role",
                         jd_text=f"jd from {self.name}")]
        )


class _FailingConnector:
    concurrent_fetch = True
    name = "broken"

    def fetch(self, search, limit=None, skip_seen=None) -> FetchResult:
        raise RuntimeError("boom")


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'pull.db'}")
    init_db(engine)
    return Session(engine)


def test_fetches_overlap_and_ingest_is_ordered(tmp_path):
    a_started, b_started = threading.Event(), threading.Event()
    connectors = [
        _HandshakeConnector("alpha", a_started, b_started),
        _HandshakeConnector("beta", b_started, a_started),
    ]
    with _session(tmp_path) as session:
        report = run_pull(
            session, connectors, SearchConfig(), tmp_path / "telemetry.json"
        )
    assert report.totals == {"alpha": 1, "beta": 1}


def test_failed_fetch_is_isolated(tmp_path):
    a_started, b_started = threading.Event(), threading.Event()
    b_started.set()  # no peer to wait for
    connectors = [
        _FailingConnector(),
        _HandshakeConnector("alpha", a_started, b_started),
    ]
    with _session(tmp_path) as session:
        report = run_pull(
            session, connectors, SearchConfig(), tmp_path / "telemetry.json"
        )
    assert report.totals == {"alpha": 1}
    assert "broken" not in report.totals
```

(Check `FetchResult` / `RawJob` constructor fields against `connectors/base.py` and `SearchConfig()` default-constructibility against `discovery/search_config.py` before running; adjust the fixtures' keyword args to the real dataclass fields — existing tests like `tests/test_connector_harvest.py` show the working shapes.)

- [ ] **Step 2: Run to verify the handshake test fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pull_runner_concurrency.py -v`
Expected: `test_fetches_overlap_and_ingest_is_ordered` FAILS (serial `run_pull` deadlocks the first handshake until its 10s timeout assertion trips). `test_failed_fetch_is_isolated` already passes — it pins isolation behavior that must survive.

- [ ] **Step 3: Add the setting and the connector attribute**

`src/resume_agent/config.py`, next to `llm_concurrency` (line 36):

```python
    pull_concurrency: int = Field(default=4, ge=1)
```

`src/resume_agent/discovery/connectors/base.py`, on the `Connector` base (class-level, near `name`):

```python
    # Whether fetch() may run on a worker thread alongside other connectors.
    # Browser-driven connectors opt out; they are serialized among themselves.
    concurrent_fetch: bool = True
```

Set `concurrent_fetch = False` as a class attribute on `DashboardScraper`, the LinkedIn scraper class (grep `build_linkedin_scraper` for the class it constructs), and `AdzunaConnector` (its enrichment drives one visible browser).

- [ ] **Step 4: Split run_pull into concurrent fetch + serial ingest**

In `src/resume_agent/discovery/connectors/runner.py`, add imports:

```python
import asyncio

from resume_agent.concurrency import Result, gather_isolated
from resume_agent.config import get_settings
```

Add the fetch fan-out helper above `run_pull`:

```python
def _fetch_all(
    connectors: list[Connector],
    search: SearchConfig,
    limit: int | None,
    skip_seen,
) -> list[Result[FetchResult]]:
    """Fetch every connector concurrently on worker threads (their APIs are sync
    and network-bound). Browser-driven connectors (concurrent_fetch=False) are
    serialized among themselves via one lock. Results come back in input order
    with failures isolated, so ingest can stay serial and canonical-ordered."""
    sem = asyncio.Semaphore(get_settings().pull_concurrency)
    browser_lock = asyncio.Lock()

    async def fetch_one(connector: Connector) -> FetchResult:
        if getattr(connector, "concurrent_fetch", True):
            async with sem:
                return await asyncio.to_thread(
                    connector.fetch, search, limit=limit, skip_seen=skip_seen
                )
        async with browser_lock:
            return await asyncio.to_thread(
                connector.fetch, search, limit=limit, skip_seen=skip_seen
            )

    return asyncio.run(gather_isolated(connectors, fetch_one))
```

Rewrite the body of `run_pull` (signature and docstring intent unchanged; the progress bar still advances per connector, now during the ingest walk):

```python
    report = PullReport()
    skip_seen = make_skip_seen(build_known_index(session)) if skip_known else None
    if reporter:
        reporter.begin(total=len(connectors), label="Fetching sources", added=0)
    fetches = _fetch_all(connectors, search, limit, skip_seen)
    added_total = 0
    for index, (connector, fetched) in enumerate(zip(connectors, fetches), 1):
        if reporter:
            reporter.step(index - 1, label=f"Ingesting {connector.name}")
        if not fetched.ok or fetched.value is None:
            exc = fetched.error
            record_run(
                telemetry_path,
                connector.name,
                added=0,
                error=f"{type(exc).__name__}: {exc}" if exc else "fetch failed",
            )
            if reporter:
                reporter.step(index, added=added_total, result=_pull_result(report))
            continue
        result = fetched.value
        try:
            summary = ingest_jobs_with_outcomes(session, result.jobs)
            added_count = summary.added.get(connector.name, sum(summary.added.values()))
            upgraded_count = summary.upgraded.get(
                connector.name, sum(summary.upgraded.values())
            )
            skipped_count = summary.skipped.get(
                connector.name, sum(summary.skipped.values())
            )
            report.totals[connector.name] = added_count
            report.upgraded[connector.name] = upgraded_count
            report.skipped[connector.name] = skipped_count
            report.changed_raw_job_ids.extend(summary.changed_raw_job_ids)
            added_total += added_count
            if result.failures:
                report.failures[connector.name] = result.failures
            record_run(
                telemetry_path,
                connector.name,
                added=added_count,
                error=_run_note(result, added_count, upgraded_count, skipped_count),
            )
        except Exception as exc:
            session.rollback()
            record_run(
                telemetry_path,
                connector.name,
                added=0,
                error=f"{type(exc).__name__}: {exc}",
            )
        if reporter:
            reporter.step(index, added=added_total, result=_pull_result(report))
    if reporter and finish:
        reporter.done(added=added_total, result=_pull_result(report))
    return report
```

Add the imports the new code needs (`FetchResult` is already imported; `SearchConfig` already imported).

Semantics change to be aware of: `skip_seen`'s known-index is built once **before** any fetch — previously connector B's fetch could observe rows ingested from connector A within the same pull. That cross-connector visibility was never guaranteed (the index predates the loop already — it's built at line 84 today, before any ingest), so nothing weakens. The ingest-side dedupe (`find_existing`) still runs serially and catches cross-connector duplicates exactly as before.

- [ ] **Step 5: Run the new tests + every pull/CLI suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pull_runner_concurrency.py tests/test_cli_discovery.py tests/test_connector_harvest.py tests/test_connectors_telemetry.py tests/api/test_runs_sse.py -v`
Expected: all PASS. `run_pull` is also driven by the API's RunManager workers (each owns its session) — `tests/api` covers that seam.

- [ ] **Step 6: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/config.py src/resume_agent/discovery/connectors/base.py src/resume_agent/discovery/connectors/runner.py src/resume_agent/discovery/connectors/adzuna.py src/resume_agent/discovery/scraper/dashboard.py src/resume_agent/discovery/scraper/linkedin.py tests/test_pull_runner_concurrency.py
git commit -m "Fetches connectors concurrently with serial ordered ingest"
```

---

### Task 7: Transient-only LLM retry at the model seam

**Files:**

- Modify: `src/resume_agent/llm_runner.py` (`AgentRunner.run/arun` gain the retry loop; new `is_transient`; `retry_kwargs` stops feeding agno)
- Modify: `src/resume_agent/discovery/pipeline.py:158-165` (log classifier outages instead of swallowing)
- Test: `tests/test_llm_runner_retry.py` (create)

**Interfaces:**

- Consumes: `Settings.llm_retries` / `llm_retry_delay` (config.py:37-38, already validated `ge=0`).
- Produces: `is_transient(exc: BaseException) -> bool` exported from `llm_runner`. `AgentRunner.run/arun` signatures unchanged. `retry_kwargs()` still exists and is still spread into all 21 `Agent(...)` builders — its body now returns `{"retries": 0}` so agno's bare-`Exception` retry is off and none of the 21 call sites need touching.
- Behavior change (intended): a `ValidationError`/auth failure now surfaces after **one** call instead of `1 + llm_retries`; only network/rate-limit/5xx-shaped failures retry.

- [ ] **Step 1: Write the failing retry tests**

Create `tests/test_llm_runner_retry.py`:

```python
import asyncio

import pytest

import resume_agent.llm_runner as llm_runner
from resume_agent.llm_runner import AgentRunner, is_transient


class _TransientError(Exception):
    status_code = 429


class _FlakyAgent:
    def __init__(self, failures: int, exc: Exception):
        self.calls = 0
        self._failures = failures
        self._exc = exc

    def run(self, prompt):
        self.calls += 1
        if self.calls <= self._failures:
            raise self._exc
        return "ok"

    async def arun(self, prompt):
        return self.run(prompt)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm_runner.time, "sleep", lambda s: None)

    async def _instant(_s):
        return None

    monkeypatch.setattr(llm_runner.asyncio, "sleep", _instant)


def test_transient_failure_is_retried():
    agent = _FlakyAgent(1, _TransientError())
    assert AgentRunner(agent).run("p") == "ok"
    assert agent.calls == 2


def test_permanent_failure_surfaces_immediately():
    agent = _FlakyAgent(5, ValueError("schema mismatch"))
    with pytest.raises(ValueError):
        AgentRunner(agent).run("p")
    assert agent.calls == 1


def test_transient_failure_exhausts_then_raises():
    agent = _FlakyAgent(99, _TransientError())
    with pytest.raises(_TransientError):
        AgentRunner(agent).run("p")
    assert agent.calls >= 2  # llm_retries default is 2 -> 3 calls


def test_arun_retries_transient_failures():
    agent = _FlakyAgent(1, _TransientError())
    assert asyncio.run(AgentRunner(agent).arun("p")) == "ok"
    assert agent.calls == 2


def test_is_transient_predicate():
    assert is_transient(_TransientError())
    assert not is_transient(ValueError("bad output"))

    class _NamedLikeSdk(Exception):
        pass

    _NamedLikeSdk.__name__ = "RateLimitError"
    assert is_transient(_NamedLikeSdk())


def test_retry_kwargs_disables_agno_retry():
    assert llm_runner.retry_kwargs() == {"retries": 0}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_retry.py -v`
Expected: FAIL — `is_transient` doesn't exist; `AgentRunner.run` doesn't retry; `retry_kwargs()` returns three keys.

- [ ] **Step 3: Implement the predicate and the retry loop**

In `src/resume_agent/llm_runner.py`, add `import time` to the imports, then add above `AgentRunner`:

```python
# Failures worth retrying: rate limits, overload, timeouts, dropped connections.
# Matched by status code and class name so no provider SDK is imported here
# (the same lazy-import rule build_model follows).
_TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_TRANSIENT_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "InternalServerError",
    "OverloadedError",
    "PoolTimeout",
    "RateLimitError",
    "ReadTimeout",
    "RemoteProtocolError",
    "ServiceUnavailableError",
    "TimeoutException",
    "WriteTimeout",
}


def is_transient(exc: BaseException) -> bool:
    """Whether an LLM-call failure is worth retrying.

    Auth, schema, and parse failures are deterministic — retrying them burns
    llm_retries x tokens for the same answer — so anything unrecognized is
    treated as permanent.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS
    return any(klass.__name__ in _TRANSIENT_NAMES for klass in type(exc).__mro__)
```

Replace `AgentRunner.run` and `AgentRunner.arun`:

```python
    def run(self, prompt: str) -> Any:
        settings = get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                return self._agent.run(prompt)
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    raise
                time.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")

    async def arun(self, prompt: str) -> Any:
        settings = get_settings()
        for attempt in range(settings.llm_retries + 1):
            try:
                return await self._agent.arun(prompt)
            except Exception as exc:
                if attempt >= settings.llm_retries or not is_transient(exc):
                    raise
                await asyncio.sleep(settings.llm_retry_delay * (2**attempt))
        raise AssertionError("unreachable")
```

Replace `retry_kwargs`:

```python
def retry_kwargs() -> dict[str, Any]:
    """agno per-agent retry config, spread into every ``Agent(...)`` we build.

    Retries live in AgentRunner behind the is_transient predicate; agno's own
    bare-``Exception`` retry is disabled so a deterministic failure (auth,
    schema, parse) surfaces after one call instead of 1 + llm_retries.
    """
    return {"retries": 0}
```

Note: the retry sleeps run while `acall`'s semaphore permit is held — identical to today, where agno's internal retry also ran inside the permit.

- [ ] **Step 4: Surface classifier outages in pipeline.py**

In `src/resume_agent/discovery/pipeline.py`, add near the top (after the imports):

```python
import logging

logger = logging.getLogger(__name__)
```

Replace the silent handler in `_normalize_job_industries` (lines 160-165):

```python
        try:
            additions = classify_industries(
                list(unresolved.values()), existing, classifier
            ).assignments
        except Exception:
            logger.warning(
                "industry classification failed; %d industr%s left unresolved this run",
                len(unresolved),
                "y" if len(unresolved) == 1 else "ies",
                exc_info=True,
            )
            additions = {}
```

(The fallback behavior — proceed with `additions = {}`, retry next run via `_industry_candidate` — is correct and stays; only the silence goes.)

- [ ] **Step 5: Run the new tests + every agent-touching suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_retry.py tests/test_agent_json_mode.py tests/test_discovery_relevance.py tests/test_tailor_tailoring.py tests/test_cover_letter_drafting.py -v`
Expected: all PASS (fake agents in the suite don't raise transient errors, so the loop is a pass-through for them).

- [ ] **Step 6: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/llm_runner.py src/resume_agent/discovery/pipeline.py tests/test_llm_runner_retry.py
git commit -m "Retries only transient LLM failures at the runner seam"
```

---

### Task 8: Documentation sweep

**Files:**

- Modify: `CLAUDE.md` (three touched claims)

**Interfaces:** none — docs only.

- [ ] **Step 1: Update the stale claims**

In `CLAUDE.md`:

1. "Known design notes" bullet on LLM retry — replace "note it retries bare `Exception`, so a parse failure costs `llm_retries` extra calls — kept low (default 2)" with: "retries live in `AgentRunner` behind the `is_transient` predicate (rate-limit/timeout/5xx retry with exponential backoff; auth/schema/parse failures surface after one call); agno's own retry is disabled via `retry_kwargs() == {\"retries\": 0}`."
2. "Companies connector dispatch" section — append one line: "Connector construction itself is table-driven: `CONNECTOR_SPECS` in `registry.py` is the single enumeration of connector kinds; adding an ATS appends one `ConnectorSpec`."
3. Hot-paths table — the `runner.py` row's role becomes "Pull orchestration: concurrent fetch (bounded by `pull_concurrency`), serial canonical-order ingest, `+N added` telemetry".

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Documents retry seam, connector spec table, and concurrent pull"
```

---

## Final verification (after all tasks)

- [ ] Run: `.venv/Scripts/python.exe -m pytest -q` — expected: full suite PASS.
- [ ] Run: `ruff check` — expected: clean.
- [ ] Run: `git diff main --stat -- contracts/` — expected: **empty** (wire contract untouched).
- [ ] Use superpowers:requesting-code-review before merging the branch.

## Self-review notes (already applied)

- **Coverage:** review candidates 1→Task 1, 2→Task 2, 3→Task 3, 4→Task 4, 7→Task 5, 5→Task 6, 6→Task 7; docs drift → Task 8.
- **Type consistency:** `progressed_job_ids`/`job_has_progress`/`versions_by_job`/`applications_by_job` (Task 1) are the exact names Task 1's queries.py code imports; `CONNECTOR_SPECS` (Task 3) is the name Task 3's drift test imports; `FACET_SPECS`/`FacetSpec` (Task 5) match its drift test; `is_transient` (Task 7) matches its tests; `concurrent_fetch`/`pull_concurrency` (Task 6) are read via `getattr`/`get_settings` in the same task's code.
- **Known judgment calls:** (a) Task 2's fingerprint prefilter relies on the "every persisted row has a fingerprint" invariant — flagged in Step 7 with the fixture remedy. (b) Task 6 serializes browser connectors instead of excluding them — one lock, no partition machinery. (c) Task 7 keeps `retry_kwargs()` at all 21 call sites rather than deleting it, trading a vestigial spread for a 1-file diff.
