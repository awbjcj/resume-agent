# Redo Pipeline Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user redo any pipeline stage — re-pull the JD, re-extract criteria, re-tailor, re-render — on explicitly chosen jobs at any status, without destroying prior work, and triage per-job failures from the dashboard.

**Architecture:** A status rank ladder (`tracking/stages.py`) makes every status write forward-only under a flag, so redo never regresses a job. A `StageScope` parameter unfuses "which rows" and "what status to write" from the funnel stages in `discovery/pipeline.py`, letting them run over explicit ids at any status. `services/redo.py` orchestrates the four stages stage-major over a job list. Per-job failures — previously swallowed by `gather_isolated` and reported as an opaque count — become `StageFailure` values written to the existing `ErrorRecord` substrate and surfaced in the dashboard's `AttentionCard` with a Retry action.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy, Pydantic v2, pytest. Web: React 19, TypeScript, TanStack Query, Base UI, Vitest + Testing Library.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-25-redo-pipeline-stages-design.md`. Read it before Task 1.
- **Branch:** work on `feat/redo-pipeline-stages` (already exists, branched off `dev`). Never commit to `main`.
- **Tests are offline.** No API key, no network. All agents and the Playwright browser are faked. Run with `.venv/Scripts/python.exe -m pytest`.
- **Lint:** `ruff check` must pass before every commit.
- **Wire format is camelCase.** All API schemas extend `CamelModel` (`api/schemas/base.py`), which sets `alias_generator=to_camel`. Python stays snake_case.
- **Contract regeneration:** any change to an API schema requires `bash scripts/gen_ts_client.sh`, and `tests/api/test_openapi_contract.py` is the drift gate.
- **Redo never regresses a job's status, never rejects a job, and never deletes a `ResumeVersion`, `pdf_path`, `Application`, or `CoverLetter`.** These are the invariants the whole feature exists to preserve. Every task must leave them true.
- **The automatic paths are untouched.** `pull`, `discover`, `refresh`, and `reprocess` keep their existing guards and status transitions. `StageScope()` with no arguments must reproduce today's behaviour exactly.
- **`decide()` in `discovery/merge.py` is not modified.** Re-pull deliberately bypasses the ingest merge rather than loosening it.

---

## File Structure

**New backend files**

| Path | Responsibility |
|---|---|
| `src/resume_agent/tracking/stages.py` | The status rank ladder and the single `advance()` status-write helper. No I/O. |
| `src/resume_agent/services/redo.py` | The redo use-case: `RedoStage`, `StageOutcome`, `repull_job`, `redo_jobs`. Orchestration only — delegates every stage to existing services. |

**Modified backend files**

| Path | Change |
|---|---|
| `src/resume_agent/discovery/pipeline.py` | `StageScope` dataclass; `_stage_jobs` honours it; every status write routes through `advance`; per-job failures logged. |
| `src/resume_agent/tailor/service.py` | `TailorOutcome`; `_persist_rounds` uses `advance`; writes `attempt`/`tailor_model`; logs and returns failures. |
| `src/resume_agent/services/tailoring.py` | Carries failures through; `fail_on_partial` raises only on total failure, naming the cause. |
| `src/resume_agent/services/errors.py` | `"job"` kind, `StageFailure`, `record_job_failure`, `resolve_job_failures`. |
| `src/resume_agent/tracking/tables.py` | `ResumeVersion.attempt`, `ResumeVersion.tailor_model`. |
| `src/resume_agent/services/discovery.py` | Pass `StageScope` instead of `job_ids`. |
| `src/resume_agent/api/schemas/runs.py` | `RedoParams`, `StageOutcomeOut`, `RedoResultOut`. |
| `src/resume_agent/api/schemas/errors.py` | `JobFailureDetails`, `ErrorRecordOut.job_details`, `ErrorRecordsOut.pagination`. |
| `src/resume_agent/api/routers/runs.py` | `POST /api/redo`. |
| `src/resume_agent/api/routers/errors.py` | `_row()` projects typed job details; list gains `page`/`pageSize`. |

**New web files**

| Path | Responsibility |
|---|---|
| `web/src/features/runs/use-redo-run.ts` | Launch a redo run through the existing `useLaunchRun`. |
| `web/src/features/runs/RedoDialog.tsx` | Stage picker + count confirmation. Used by the board, the job modal, and Retry. |
| `web/src/features/dashboard/JobFailureRow.tsx` | One formatted job-failure row with expander and actions. |

**Modified web files**

| Path | Change |
|---|---|
| `web/src/features/pipeline/PipelineContainer.tsx` | `Redo…` bulk action. |
| `web/src/components/JobModal.tsx` | Per-job `Redo…`. |
| `web/src/features/dashboard/AttentionCard.tsx` | Group by kind; delegate job rows to `JobFailureRow`; wire Retry. |

---

## Task 1: Status ladder

**Files:**
- Create: `src/resume_agent/tracking/stages.py`
- Test: `tests/test_tracking_stages.py`

**Interfaces:**
- Consumes: `JobStatus`, `Job` from `resume_agent.tracking.tables`.
- Produces: `rank(status: str) -> int`; `advance(job: Job, target: str, *, never_regress: bool) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracking_stages.py`:

```python
from resume_agent.tracking.stages import advance, rank
from resume_agent.tracking.tables import Job, JobStatus


def _job(status: str) -> Job:
    return Job(source="manual", jd_text="jd", status=status)


def test_rank_orders_the_pipeline():
    assert rank(JobStatus.raw.value) < rank(JobStatus.extracted.value)
    assert rank(JobStatus.extracted.value) < rank(JobStatus.filtered.value)
    assert rank(JobStatus.filtered.value) < rank(JobStatus.shortlisted.value)
    assert rank(JobStatus.shortlisted.value) < rank(JobStatus.approved.value)
    assert rank(JobStatus.approved.value) < rank(JobStatus.tailored.value)
    assert rank(JobStatus.tailored.value) < rank(JobStatus.rendered.value)


def test_rejected_ranks_below_raw():
    # This is what makes "redo never rejects" fall out of "redo never regresses"
    # instead of needing its own branch.
    assert rank(JobStatus.rejected.value) < rank(JobStatus.raw.value)


def test_unknown_status_ranks_as_raw():
    assert rank("nonsense") == rank(JobStatus.raw.value)


def test_advance_writes_forward_moves_when_never_regress():
    job = _job(JobStatus.approved.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is True
    assert job.status == JobStatus.tailored.value


def test_advance_refuses_backward_moves_when_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is False
    assert job.status == JobStatus.rendered.value


def test_advance_refuses_rejection_when_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.rejected.value, never_regress=True) is False
    assert job.status == JobStatus.rendered.value


def test_advance_allows_backward_moves_when_not_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.raw.value, never_regress=False) is True
    assert job.status == JobStatus.raw.value


def test_advance_is_a_noop_write_at_equal_rank():
    job = _job(JobStatus.tailored.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is True
    assert job.status == JobStatus.tailored.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_stages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking.stages'`

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/tracking/stages.py`:

```python
"""The pipeline status ladder and the single status-write helper.

Status doubles as "where a job is in the funnel" and "how far it has got".
Redo needs the second reading: a rendered job that is re-tailored is still
rendered. `advance` is the one place that distinction is enforced.
"""

from __future__ import annotations

from resume_agent.tracking.tables import Job, JobStatus

# rejected sits below raw deliberately: it makes "redo never rejects" a
# consequence of "redo never regresses" rather than a separate rule.
_RANK: dict[str, int] = {
    JobStatus.rejected.value: -1,
    JobStatus.raw.value: 0,
    JobStatus.extracted.value: 1,
    JobStatus.filtered.value: 2,
    JobStatus.shortlisted.value: 3,
    JobStatus.approved.value: 4,
    JobStatus.tailored.value: 5,
    JobStatus.rendered.value: 6,
}


def rank(status: str) -> int:
    """Ladder position of a status. Unknown statuses rank as raw."""
    return _RANK.get(status, 0)


def advance(job: Job, target: str, *, never_regress: bool) -> bool:
    """Move job.status toward target. Returns whether it wrote."""
    if never_regress and rank(target) < rank(job.status):
        return False
    job.status = target
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_stages.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/tracking/stages.py tests/test_tracking_stages.py
git commit -m "feat(tracking): add the pipeline status ladder and advance()"
```

---

## Task 2: `StageScope` — run the funnel over explicit jobs

**Files:**
- Modify: `src/resume_agent/discovery/pipeline.py`
- Modify: `src/resume_agent/services/discovery.py`
- Test: `tests/test_pipeline_stage_scope.py`

**Interfaces:**
- Consumes: `advance`, `rank` from `resume_agent.tracking.stages` (Task 1).
- Produces: `StageScope(job_ids: frozenset[int] | None, any_status: bool, never_regress: bool)` exported from `resume_agent.discovery.pipeline`. Every stage function (`run_relevance`, `run_extract`, `run_filter`, `run_score`) and `discover` take `scope: StageScope = StageScope()` in place of `job_ids`.

**Context:** stage functions currently take `job_ids: set[int] | None` and select rows with `_stage_jobs(session, <status>, job_ids)`, then assign `job.status = ...` directly. Callers to update: `discover()` (internal, 4 call sites), `services/discovery.py::discover_jobs` and `reprocess_jobs` (pass `job_ids=`), `discovery/pipeline.py::reprocess` (passes `job_ids=set(selected)`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_stage_scope.py`:

```python
import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.pipeline import StageScope, _stage_jobs, run_filter
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def _job(session, status: str, **criteria) -> Job:
    return save_job(
        session,
        Job(
            source="manual",
            jd_text="jd",
            status=status,
            criteria_json=JobCriteria(**criteria).model_dump(mode="json"),
        ),
    )


# apply_filters rejects when the job's yoe_min exceeds the config's yoe_max.
# That is the cheapest deterministic rejection available (see discovery/filter.py).
REJECTING_CONFIG = SearchConfig(yoe_max=0)
REJECTED_CRITERIA = {"yoe_min": 5}


def test_default_scope_selects_by_status_only(session):
    extracted = _job(session, JobStatus.extracted.value)
    _job(session, JobStatus.rendered.value)

    rows = _stage_jobs(session, JobStatus.extracted.value, StageScope())

    assert [row.id for row in rows] == [extracted.id]


def test_id_scope_still_filters_by_status(session):
    extracted = _job(session, JobStatus.extracted.value)
    rendered = _job(session, JobStatus.rendered.value)

    scope = StageScope(job_ids=frozenset({extracted.id, rendered.id}))
    rows = _stage_jobs(session, JobStatus.extracted.value, scope)

    assert [row.id for row in rows] == [extracted.id]


def test_any_status_scope_selects_the_ids_whatever_their_status(session):
    rendered = _job(session, JobStatus.rendered.value)

    scope = StageScope(job_ids=frozenset({rendered.id}), any_status=True)
    rows = _stage_jobs(session, JobStatus.extracted.value, scope)

    assert [row.id for row in rows] == [rendered.id]


def test_never_regress_scope_suppresses_rejection(session):
    rendered = _job(session, JobStatus.rendered.value, **REJECTED_CRITERIA)

    run_filter(
        session,
        REJECTING_CONFIG,
        StageScope(
            job_ids=frozenset({rendered.id}), any_status=True, never_regress=True
        ),
    )

    session.refresh(rendered)
    assert rendered.status == JobStatus.rendered.value
    # A suppressed rejection must not leave a reason behind: the triage board
    # filters on reject_reason.
    assert rendered.reject_reason is None


def test_default_scope_still_rejects(session):
    extracted = _job(session, JobStatus.extracted.value, **REJECTED_CRITERIA)

    run_filter(session, REJECTING_CONFIG, StageScope())

    session.refresh(extracted)
    assert extracted.status == JobStatus.rejected.value
    assert extracted.reject_reason == "requires more experience than yoe_max"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline_stage_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'StageScope'`

- [ ] **Step 3: Add `StageScope` and rewire `_stage_jobs`**

In `src/resume_agent/discovery/pipeline.py`, add the import and the dataclass near the top (after the existing imports):

```python
from dataclasses import dataclass

from resume_agent.tracking.stages import advance


@dataclass(frozen=True)
class StageScope:
    """Which rows a funnel stage runs over, and how it may write status.

    The default reproduces the automatic funnel exactly: select by status,
    write status freely. Redo passes explicit ids with any_status=True and
    never_regress=True so a rendered job can be re-extracted without being
    dragged back down the ladder.
    """

    job_ids: frozenset[int] | None = None
    any_status: bool = False
    never_regress: bool = False
```

Replace `_stage_jobs`:

```python
def _stage_jobs(session: Session, status: str, scope: StageScope) -> list[Job]:
    if scope.any_status and scope.job_ids is not None:
        rows = [session.get(Job, job_id) for job_id in sorted(scope.job_ids)]
        return [job for job in rows if job is not None]
    jobs = jobs_by_status(session, status)
    if scope.job_ids is None:
        return jobs
    return [job for job in jobs if job.id in scope.job_ids]
```

- [ ] **Step 4: Thread `scope` through every stage function**

In each of `run_relevance`, `run_extract`, `run_filter`, `run_score`, and
`discover`, replace the parameter `job_ids: set[int] | None = None` with
`scope: StageScope = StageScope()`, and replace each `_stage_jobs(session, X, job_ids)`
call with `_stage_jobs(session, X, scope)`.

Then replace every direct status assignment in those functions with `advance`:

```python
# run_extract — was: job.status = JobStatus.extracted.value
advance(job, JobStatus.extracted.value, never_regress=scope.never_regress)

# run_filter — was the keep/reject branch
if decision.keep or job.gate_override:
    advance(job, JobStatus.filtered.value, never_regress=scope.never_regress)
elif advance(job, JobStatus.rejected.value, never_regress=scope.never_regress):
    job.reject_reason = decision.reject_reason
    job.reject_category = "filtered"
session.add(job)

# run_score — was: job.status = JobStatus.shortlisted.value
advance(job, JobStatus.shortlisted.value, never_regress=scope.never_regress)

# run_relevance — was the reject branch
if not verdict.keep and advance(
    job, JobStatus.rejected.value, never_regress=scope.never_regress
):
    reason = (verdict.reason or "model rejected").strip()
    job.reject_reason = f"off-target role: {reason}"
    job.reject_category = "relevance"
    session.add(job)
    rejected += 1
```

Note the `reject_reason`/`reject_category` writes moved *inside* the `advance`
guard. A suppressed rejection must not leave a reject reason behind — the triage
board filters on it.

In `discover`, pass `scope=scope` to all four stage calls.

- [ ] **Step 5: Update the three external callers**

In `src/resume_agent/discovery/pipeline.py::reprocess`, change the `discover(...)` call's `job_ids=set(selected)` to `scope=StageScope(job_ids=frozenset(selected))`.

In `src/resume_agent/services/discovery.py`:
- add `from resume_agent.discovery.pipeline import StageScope` to the existing pipeline import,
- in `discover_jobs`, change the signature's `job_ids: set[int] | None = None` to stay as-is (it is the public service API) but pass
  `scope=StageScope(job_ids=frozenset(job_ids)) if job_ids else StageScope()` to `discover(...)`.

- [ ] **Step 6: Run the new tests and the full discovery suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline_stage_scope.py tests/test_discovery_ingest.py tests/test_cli_discovery.py -v`
Expected: PASS — new tests green, existing discovery tests unchanged and green.

- [ ] **Step 7: Run the whole backend suite to prove the default scope is behaviour-preserving**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS — no regressions. This run is the real proof that `StageScope()` reproduces today's funnel.

- [ ] **Step 8: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/pipeline.py src/resume_agent/services/discovery.py tests/test_pipeline_stage_scope.py
git commit -m "refactor(discovery): add StageScope so funnel stages can run over explicit jobs"
```

---

## Task 3: Durable per-job failures

**Files:**
- Modify: `src/resume_agent/services/errors.py`
- Test: `tests/test_errors_service.py` (append)

**Interfaces:**
- Consumes: existing `record_error`, `_WRITE_LOCK`, `_KINDS` in `services/errors.py`.
- Produces:
  - `StageFailure(error_type: str, message: str, traceback_tail: str)` with `StageFailure.from_exception(exc: BaseException) -> StageFailure`
  - `record_job_failure(session, *, job: Job, stage: str, failure: StageFailure, run_id: str | None = None, model: str | None = None) -> ErrorRecord`
  - `resolve_job_failures(session, job_id: int, stage: str) -> int`
  - `job_failure_label(job_id: int, stage: str) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_errors_service.py`:

```python
def test_record_job_failure_stores_formatted_details(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(
        session, Job(source="manual", jd_text="jd", company="Acme", title="Staff")
    )
    try:
        raise ValueError("match_plan_enabled requires a match-plan agent")
    except ValueError as exc:
        failure = StageFailure.from_exception(exc)

    record = record_job_failure(
        session,
        job=job,
        stage="tailor",
        failure=failure,
        run_id="r1",
        model="openai:gpt-5",
    )

    assert record.kind == "job"
    assert record.source_label == f"job:{job.id}:tailor"
    assert record.message.startswith("ValueError: match_plan_enabled")
    details = record.details_json or {}
    assert details["jobId"] == job.id
    assert details["company"] == "Acme"
    assert details["title"] == "Staff"
    assert details["stage"] == "tailor"
    assert details["errorType"] == "ValueError"
    assert details["model"] == "openai:gpt-5"
    assert "ValueError" in details["tracebackTail"]


def test_repeated_job_failure_dedupes_and_counts(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")

    first = record_job_failure(session, job=job, stage="tailor", failure=failure)
    second = record_job_failure(session, job=job, stage="tailor", failure=failure)

    assert second.id == first.id
    assert second.count == 2


def test_different_stages_are_separate_records(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")

    tailor = record_job_failure(session, job=job, stage="tailor", failure=failure)
    pull = record_job_failure(session, job=job, stage="pull", failure=failure)

    assert tailor.id != pull.id


def test_success_resolves_open_job_failure(session):
    from resume_agent.services.errors import (
        StageFailure,
        record_job_failure,
        resolve_job_failures,
    )
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    record = record_job_failure(session, job=job, stage="tailor", failure=failure)

    resolved = resolve_job_failures(session, job.id, "tailor")

    session.refresh(record)
    assert resolved == 1
    assert record.status == "resolved"


def test_resolve_leaves_other_stages_open(session):
    from resume_agent.services.errors import (
        StageFailure,
        record_job_failure,
        resolve_job_failures,
    )
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    pull = record_job_failure(session, job=job, stage="pull", failure=failure)
    record_job_failure(session, job=job, stage="tailor", failure=failure)

    resolve_job_failures(session, job.id, "tailor")

    session.refresh(pull)
    assert pull.status == "open"


def test_stage_failure_truncates_message_and_traceback():
    from resume_agent.services.errors import (
        MAX_MESSAGE_CHARS,
        MAX_TRACEBACK_CHARS,
        StageFailure,
    )

    try:
        raise ValueError("x" * 5000)
    except ValueError as exc:
        failure = StageFailure.from_exception(exc)

    assert len(failure.message) == MAX_MESSAGE_CHARS
    assert len(failure.traceback_tail) <= MAX_TRACEBACK_CHARS
    assert failure.error_type == "ValueError"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_errors_service.py -v -k "job_failure or stage_failure"`
Expected: FAIL — `ImportError: cannot import name 'StageFailure'`

- [ ] **Step 3: Write the implementation**

In `src/resume_agent/services/errors.py`, add imports at the top:

```python
import traceback
from dataclasses import dataclass

from resume_agent.tracking.tables import ErrorRecord, Job, utcnow
```

Change the kinds set:

```python
_KINDS = {"run", "source", "job"}
```

Add the constants and the value object after `_WRITE_LOCK`:

```python
MAX_MESSAGE_CHARS = 300
MAX_TRACEBACK_CHARS = 4000
TRACEBACK_FRAMES = 5


@dataclass(frozen=True)
class StageFailure:
    """One job's stage failure, formatted for storage and display.

    Built where the exception is still in hand. The full traceback goes to the
    log via exc_info; only the tail is persisted, so a 400-job failed run does
    not write megabytes into a user-facing table.
    """

    error_type: str
    message: str
    traceback_tail: str

    @classmethod
    def from_exception(cls, exc: BaseException) -> "StageFailure":
        frames = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tail = "".join(frames[-TRACEBACK_FRAMES:])[-MAX_TRACEBACK_CHARS:]
        return cls(
            error_type=type(exc).__name__,
            message=str(exc)[:MAX_MESSAGE_CHARS],
            traceback_tail=tail,
        )


def job_failure_label(job_id: int, stage: str) -> str:
    """The dedupe key for a job+stage failure."""
    return f"job:{job_id}:{stage}"
```

Add the writer and the resolver at the end of the module:

```python
def record_job_failure(
    session: Session,
    *,
    job: Job,
    stage: str,
    failure: StageFailure,
    run_id: str | None = None,
    model: str | None = None,
) -> ErrorRecord:
    """Persist one job's stage failure, deduped on job+stage."""
    if job.id is None:
        raise ValueError("cannot record a failure for an unsaved job")
    return record_error(
        session,
        kind="job",
        source_label=job_failure_label(job.id, stage),
        message=f"{failure.error_type}: {failure.message}",
        run_id=run_id,
        # camelCase so JobFailureDetails (a CamelModel, which validates by
        # alias) reads this straight back.
        details={
            "jobId": job.id,
            "company": job.company,
            "title": job.title,
            "stage": stage,
            "errorType": failure.error_type,
            "message": failure.message,
            "model": model,
            "tracebackTail": failure.traceback_tail,
        },
    )


def resolve_job_failures(session: Session, job_id: int, stage: str) -> int:
    """Close any open failure for this job+stage. Returns how many closed.

    Called on every stage success. Without it a failure outlives the run that
    fixed it and the dashboard fills with already-resolved noise.
    """
    with _WRITE_LOCK:
        records = session.exec(
            select(ErrorRecord).where(
                ErrorRecord.kind == "job",
                ErrorRecord.source_label == job_failure_label(job_id, stage),
                ErrorRecord.status == "open",
            )
        ).all()
        if not records:
            return 0
        now = utcnow()
        for record in records:
            record.status = "resolved"
            record.updated_at = now
            session.add(record)
        session.commit()
        return len(records)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_errors_service.py -v`
Expected: PASS — all existing plus 6 new tests.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/errors.py tests/test_errors_service.py
git commit -m "feat(errors): record and auto-resolve durable per-job stage failures"
```

---

## Task 4: Version attempts and forward-only tailor status

**Files:**
- Modify: `src/resume_agent/tracking/tables.py`
- Modify: `src/resume_agent/tailor/service.py:27-53` (`_persist_rounds`)
- Test: `tests/test_tailor_service.py` (append)

**Interfaces:**
- Consumes: `advance` from `resume_agent.tracking.stages` (Task 1).
- Produces: `ResumeVersion.attempt: int` and `ResumeVersion.tailor_model: str | None`; `_persist_rounds(session, job, rounds, *, model: str | None = None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tailor_service.py`:

```python
def test_retailoring_a_rendered_job_keeps_it_rendered():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.rendered.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        tailor_job(
            s,
            job,
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert job.status == JobStatus.rendered.value


def test_retailoring_appends_a_new_attempt_and_keeps_old_versions():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        first = tailor_job(
            s, job, facts, config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )
        second = tailor_job(
            s, job, facts, config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert first[0].attempt == 1
        assert second[0].attempt == 2
        stored = resume_versions_for_job(s, _require_id(job.id))
        assert len(stored) == 2  # nothing was replaced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_service.py -v -k "retailoring"`
Expected: FAIL — `AttributeError: 'ResumeVersion' object has no attribute 'attempt'`

- [ ] **Step 3: Add the columns**

In `src/resume_agent/tracking/tables.py`, inside `class ResumeVersion`, add after `critique_json`:

```python
    attempt: int = Field(default=0, index=True)
    tailor_model: str | None = None
```

Both are additive with defaults, so existing rows read back as `attempt=0, tailor_model=None`.

- [ ] **Step 4: Rewrite `_persist_rounds`**

In `src/resume_agent/tailor/service.py`, add the import:

```python
from resume_agent.tracking.stages import advance
```

Replace `_persist_rounds` (lines 27-53):

```python
def _next_attempt(session: Session, job_id: int) -> int:
    existing = resume_versions_for_job(session, job_id)
    return max((version.attempt for version in existing), default=0) + 1


def _persist_rounds(
    session: Session,
    job: Job,
    rounds: list[TailorRound],
    *,
    model: str | None = None,
) -> list[ResumeVersion]:
    """Persist each review round as a ResumeVersion and mark the job tailored.

    Status moves forward only: re-tailoring a rendered job leaves it rendered.
    Versions are appended under a fresh attempt number; nothing is replaced.
    """
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    attempt = _next_attempt(session, job.id)
    versions: list[ResumeVersion] = []
    for r in rounds:
        version = ResumeVersion(
            job_id=job.id,
            round=r.round_num,
            attempt=attempt,
            tailor_model=model,
            content_json=r.content.model_dump(mode="json"),
            review_score=r.verdict.aggregate_score,
            fact_check_passed=r.verdict.gate_passed,
            critique_json=[c.model_dump(mode="json") for c in r.verdict.critiques],
        )
        versions.append(save_resume_version(session, version))
    advance(job, JobStatus.tailored.value, never_regress=True)
    save_job(session, job)
    logger.info(
        "tailor job=%s attempt=%s rounds=%s total_llm_seconds=%.1f stages=%s",
        job.id,
        attempt,
        len(rounds),
        sum(sum(round_.stage_seconds.values()) for round_ in rounds),
        [round_.stage_seconds for round_ in rounds],
    )
    return versions
```

Add `resume_versions_for_job` to the existing `resume_agent.tracking.repository` import at the top of the file.

> `never_regress=True` is unconditional here. Tailoring only ever moves a job to
> `tailored`, and no caller wants that to demote a rendered job — including the
> normal approved-job path, where the job is at `approved` and the move is
> forward anyway.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_service.py tests/test_cli_tailor.py -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/tracking/tables.py src/resume_agent/tailor/service.py tests/test_tailor_service.py
git commit -m "feat(tailor): append versions under an attempt number, never regress status"
```

---

## Task 5: Surface the real tailoring failure

This is the task that fixes `RuntimeError: Tailoring failed for x of x jobs`.

**Files:**
- Modify: `src/resume_agent/tailor/service.py:95-165` (`tailor_jobs`)
- Modify: `src/resume_agent/services/tailoring.py:44-92` (`tailor`)
- Test: `tests/test_tailor_service.py` (append), `tests/test_services_tailoring.py` (create)

**Interfaces:**
- Consumes: `StageFailure` from `resume_agent.services.errors` (Task 3).
- Produces: `TailorOutcome(versions: dict[int, list[ResumeVersion]], failures: dict[int, StageFailure])` exported from `resume_agent.tailor.service`. `tailor_jobs(...) -> TailorOutcome`. `services.tailoring.tailor(...) -> TailorOutcome`.

**Breaking-change note:** `tailor_jobs` and `services.tailoring.tailor` currently return `dict[int, list[ResumeVersion]]`. Both are internal (no HTTP consumer returns them directly), so this is a safe internal change — but the router in Task 8 and `api/routers/runs.py:276` both read the result and must be updated in the same commit.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tailor_service.py`:

```python
class _ExplodingAgent:
    def __init__(self, message: str = "model is not configured"):
        self.message = message
        self.closed = False

    def run(self, prompt):
        raise ValueError(self.message)

    async def arun(self, prompt):
        return self.run(prompt)

    async def aclose(self):
        self.closed = True


def test_tailor_jobs_reports_the_failure_cause():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json"),
            ),
        )
        outcome = tailor_jobs(
            s,
            [job],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ExplodingAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        job_id = _require_id(job.id)
        assert outcome.versions == {}
        failure = outcome.failures[job_id]
        assert failure.error_type == "ValueError"
        assert "model is not configured" in failure.message
        assert "ValueError" in failure.traceback_tail
        # The job is left where it was so the next run retries it.
        assert job.status == JobStatus.approved.value


def test_tailor_jobs_keeps_successful_siblings_when_one_fails():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        good = save_job(
            s,
            Job(source="manual", jd_text="ok", status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json")),
        )
        outcome = tailor_jobs(
            s,
            [good],
            ProfileFacts(contact=Contact(name="Ada")),
            config,  # type: ignore[call-arg]
            tailor_agent=_ContentAgent(),
            reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_ContentAgent(),
        )

        assert list(outcome.versions) == [_require_id(good.id)]
        assert outcome.failures == {}
```

Create `tests/test_services_tailoring.py`:

```python
import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.services.errors import StageFailure
from resume_agent.tailor.service import TailorOutcome


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def test_fail_on_partial_raises_only_when_everything_failed(monkeypatch, session):
    from resume_agent.services import tailoring
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job, JobStatus

    job = save_job(
        session, Job(source="manual", jd_text="jd", status=JobStatus.approved.value)
    )
    failure = StageFailure(
        error_type="ValueError",
        message="match_plan_enabled requires a match-plan agent",
        traceback_tail="",
    )
    monkeypatch.setattr(
        tailoring,
        "tailor_jobs",
        lambda *a, **k: TailorOutcome(versions={}, failures={job.id: failure}),
    )
    monkeypatch.setattr(tailoring, "enforce_active_budget", lambda: None)

    with pytest.raises(RuntimeError) as excinfo:
        tailoring.tailor(session, job_ids=[job.id], fail_on_partial=True)

    # The whole point: the cause is named, not just counted.
    assert "match_plan_enabled requires a match-plan agent" in str(excinfo.value)
    assert "ValueError" in str(excinfo.value)


def test_partial_failure_does_not_raise(monkeypatch, session):
    from resume_agent.services import tailoring
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job, JobStatus

    ok = save_job(
        session, Job(source="manual", jd_text="a", status=JobStatus.approved.value)
    )
    bad = save_job(
        session, Job(source="manual", jd_text="b", status=JobStatus.approved.value)
    )
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    monkeypatch.setattr(
        tailoring,
        "tailor_jobs",
        lambda *a, **k: TailorOutcome(versions={ok.id: []}, failures={bad.id: failure}),
    )
    monkeypatch.setattr(tailoring, "enforce_active_budget", lambda: None)

    outcome = tailoring.tailor(
        session, job_ids=[ok.id, bad.id], fail_on_partial=True
    )

    assert list(outcome.versions) == [ok.id]
    assert list(outcome.failures) == [bad.id]
```

> `tests/test_services_tailoring.py` monkeypatches `tailor_jobs` and
> `enforce_active_budget` because `tailoring.tailor` otherwise loads review
> config, facts, and the skill matrix from disk. This test is about the
> failure-reporting contract only.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring.py tests/test_tailor_service.py -v -k "failure or partial"`
Expected: FAIL — `ImportError: cannot import name 'TailorOutcome'`

- [ ] **Step 3: Add `TailorOutcome` and stop swallowing errors**

In `src/resume_agent/tailor/service.py`, add imports:

```python
from dataclasses import dataclass, field

from resume_agent.services.errors import StageFailure
```

Add the dataclass above `tailor_jobs`:

```python
@dataclass(frozen=True)
class TailorOutcome:
    """What one tailor run produced, per job, including what went wrong."""

    versions: dict[int, list[ResumeVersion]] = field(default_factory=dict)
    failures: dict[int, StageFailure] = field(default_factory=dict)
```

Replace the result-collection loop at the end of `tailor_jobs` (lines 156-162):

```python
        for job, res in zip(targets, rounds_results):
            job_id = job.id
            if job_id is None:
                raise ValueError("Cannot tailor a job that has not been persisted")
            if not res.ok or res.value is None:
                # Previously a bare `continue`: the captured exception was
                # discarded, so callers could only report a count. Log it and
                # hand it back so the cause reaches the user.
                error = res.error or RuntimeError("tailoring produced no rounds")
                logger.warning(
                    "tailor job=%s failed", job_id, exc_info=error
                )
                failures[job_id] = StageFailure.from_exception(error)
                continue
            results[job_id] = _persist_rounds(session, job, res.value, model=model)
```

Change `tailor_jobs`'s signature to accept the model id and return the outcome:

```python
def tailor_jobs(
    session: Session,
    targets: Sequence[Job],
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    reporter: ProgressReporter | None = None,
    match_plan_agent: Runner | None = None,
    skill_matrix: SkillMatrix | None = None,
    cluster_map: ClusterMap | None = None,
    model: str | None = None,
) -> TailorOutcome:
```

Declare `failures: dict[int, StageFailure] = {}` alongside `results`, and end with:

```python
    if reporter:
        reporter.done()
    return TailorOutcome(versions=results, failures=failures)
```

- [ ] **Step 4: Update `services/tailoring.py`**

Replace the tail of `tailor` (lines 71-92):

```python
    # Mirrors build_tailor_bundle's own tier lookup, so `model` records the
    # model that actually ran.
    model = model_for_tier(getattr(config, "tailor_tier", "premium"))
    outcome = tailor_jobs(
        session,
        targets,
        facts,
        config,
        bundle.tailor,
        bundle.reviewers,
        bundle.reviser,
        reporter=reporter,
        match_plan_agent=bundle.match_plan,
        skill_matrix=skill_matrix,
        cluster_map=cluster_map,
        model=model,
    )
    for job_id in outcome.versions:
        export_job_artifacts(session, job_id)
    if fail_on_partial and outcome.failures and not outcome.versions:
        job_id, failure = next(iter(outcome.failures.items()))
        raise RuntimeError(
            f"Tailoring failed for all {len(outcome.failures)} job(s). "
            f"First cause (job {job_id}): {failure.error_type}: {failure.message}"
        )
    return outcome
```

Change the return annotation to `-> TailorOutcome`, and add
`from resume_agent.tailor.service import TailorOutcome, tailor_jobs` plus
`from resume_agent.llm_runner import model_for_tier` to the imports.

> `ReviewConfig.tailor_tier` is `Literal["cheap","mid","premium"]` defaulting to
> `"premium"` (`tailor/review_config.py:32`), and `build_tailor_bundle` reads it
> with the same `getattr` default. Keep the two in step.

- [ ] **Step 5: Update the existing tailor router call site**

In `src/resume_agent/api/routers/runs.py`, in `do_tailor` (line 276), change:

```python
        outcome = tailor(
            session,
            job_ids=params.job_ids,
            approved=params.approved,
            review_path=DEFAULT_REVIEW_DEEP if params.deep else DEFAULT_REVIEW,
            reporter=reporter,
            fail_on_partial=True,
        )
        return {
            "jobs": [
                {
                    "jobId": jid,
                    "versionCount": len(v),
                    "factCheckPassed": v[-1].fact_check_passed if v else False,
                }
                for jid, v in outcome.versions.items()
            ],
            "failures": [
                {
                    "jobId": jid,
                    "errorType": failure.error_type,
                    "message": failure.message,
                }
                for jid, failure in outcome.failures.items()
            ],
        }
```

- [ ] **Step 6: Run the tailor suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_service.py tests/test_services_tailoring.py tests/test_cli_tailor.py tests/test_cli_tailor_deep.py tests/api -v`
Expected: PASS. Fix any other call site the failures reveal — `grep -rn "tailor_jobs\|services.tailoring import\|from resume_agent.services.tailoring" src/ tests/` finds them all.

- [ ] **Step 7: Lint and commit**

```bash
ruff check
git add src/resume_agent/tailor/service.py src/resume_agent/services/tailoring.py src/resume_agent/api/routers/runs.py tests/test_tailor_service.py tests/test_services_tailoring.py
git commit -m "fix(tailor): surface the real per-job failure instead of an opaque count"
```

---

## Task 6: Re-pull a job's description

**Files:**
- Create: `src/resume_agent/services/redo.py`
- Test: `tests/test_services_redo_pull.py`

**Interfaces:**
- Consumes: `job_from_url` from `resume_agent.discovery.url_ingest.service`; `compute_dedup_key`, `compute_content_fingerprint` from `resume_agent.tracking.dedup`; `company_rename_collides` from `resume_agent.tracking.repository`; `StageFailure` from `resume_agent.services.errors` (Task 3).
- Produces:
  - `RedoStage = Literal["pull", "extract", "tailor", "render"]`
  - `REDO_STAGES: tuple[RedoStage, ...] = ("pull", "extract", "tailor", "render")`
  - `StageOutcome(job_id: int, stage: RedoStage, status: Literal["ok","skipped","failed"], detail: str | None)`
  - `repull_job(session, job, *, agent, allow_browser) -> tuple[StageOutcome, StageFailure | None]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_services_redo_pull.py`:

```python
import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.services import redo
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def _tailored_job(session, **overrides) -> Job:
    values = {
        "source": "greenhouse",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "company": "Acme",
        "title": "Staff Engineer",
        "jd_text": "old text",
        "status": JobStatus.tailored.value,
    }
    values.update(overrides)
    return save_job(session, Job(**values))


def test_repull_replaces_frozen_jd_text_on_a_tailored_job(session, monkeypatch):
    """The motivating case: merge.decide() freezes jd_text past raw; redo does not."""
    job = _tailored_job(session)
    monkeypatch.setattr(
        redo,
        "job_from_url",
        lambda url, agent, allow_browser: RawJob(
            source="url", url=url, company="Acme", title="Staff Engineer",
            location="Remote", jd_text="fresh text",
        ),
    )

    outcome, failure = redo.repull_job(
        session, job, agent=object(), allow_browser=False
    )

    assert outcome.status == "ok"
    assert failure is None
    assert job.jd_text == "fresh text"
    assert job.location == "Remote"
    assert job.status == JobStatus.tailored.value  # never regressed
    assert job.source == "greenhouse"  # provenance preserved


def test_repull_skips_a_job_with_no_url(session):
    job = _tailored_job(session, url=None, source="manual")

    outcome, failure = redo.repull_job(
        session, job, agent=object(), allow_browser=False
    )

    assert outcome.status == "skipped"
    assert outcome.detail == "no source URL"
    assert failure is None
    assert job.jd_text == "old text"


def test_repull_failure_preserves_jd_text(session, monkeypatch):
    job = _tailored_job(session)

    def _boom(url, agent, allow_browser):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(redo, "job_from_url", _boom)

    outcome, failure = redo.repull_job(
        session, job, agent=object(), allow_browser=False
    )

    assert outcome.status == "failed"
    assert job.jd_text == "old text"
    assert failure is not None
    assert failure.error_type == "ConnectError"


def test_repull_reports_failure_when_no_description_extracted(session, monkeypatch):
    job = _tailored_job(session)
    monkeypatch.setattr(redo, "job_from_url", lambda url, agent, allow_browser: None)

    outcome, failure = redo.repull_job(
        session, job, agent=object(), allow_browser=False
    )

    assert outcome.status == "failed"
    assert outcome.detail == "no job description found"
    assert job.jd_text == "old text"


def test_repull_recomputes_dedup_key_when_title_changes(session, monkeypatch):
    job = _tailored_job(session)
    original_key = job.dedup_key
    monkeypatch.setattr(
        redo,
        "job_from_url",
        lambda url, agent, allow_browser: RawJob(
            source="url", url=url, company="Acme", title="Principal Engineer",
            location=None, jd_text="fresh text",
        ),
    )

    redo.repull_job(session, job, agent=object(), allow_browser=False)

    assert job.title == "Principal Engineer"
    assert job.dedup_key != original_key


def test_repull_keeps_identity_when_the_new_key_would_collide(session, monkeypatch):
    job = _tailored_job(session)
    original_key = job.dedup_key
    _tailored_job(session, company="Acme", title="Principal Engineer",
                  url="https://boards.greenhouse.io/acme/jobs/2")
    monkeypatch.setattr(
        redo,
        "job_from_url",
        lambda url, agent, allow_browser: RawJob(
            source="url", url=url, company="Acme", title="Principal Engineer",
            location=None, jd_text="fresh text",
        ),
    )

    outcome, _ = redo.repull_job(session, job, agent=object(), allow_browser=False)

    assert outcome.status == "ok"
    assert job.jd_text == "fresh text"   # text still taken
    assert job.title == "Staff Engineer"  # identity untouched
    assert job.dedup_key == original_key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_redo_pull.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.redo'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/services/redo.py`:

```python
"""Redo any pipeline stage on explicitly chosen jobs.

The automatic paths (pull/discover/refresh/reprocess) guard against clobbering
user work: merge.decide() freezes jd_text past raw, and reprocess() skips jobs
with progress. Those guards are right for a scheduled run and wrong for a user
who deliberately picked a job. Redo is the explicit escape hatch, and it never
regresses status, never rejects, and never deletes prior artifacts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.services.errors import StageFailure
from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
from resume_agent.tracking.repository import company_rename_collides, save_job
from resume_agent.tracking.tables import Job

logger = logging.getLogger(__name__)

RedoStage = Literal["pull", "extract", "tailor", "render"]

# Stages always run in pipeline order, whatever order the caller listed them.
REDO_STAGES: tuple[RedoStage, ...] = ("pull", "extract", "tailor", "render")


@dataclass(frozen=True)
class StageOutcome:
    """One job's result for one stage, as reported in the run payload.

    Distinct from StageFailure, which is the durable diagnostic written to
    ErrorRecord. `detail` carries the same one-line message.
    """

    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None


def repull_job(
    session: Session,
    job: Job,
    *,
    agent,
    allow_browser: bool,
) -> tuple[StageOutcome, StageFailure | None]:
    """Re-fetch a job's posting and replace its description in place.

    Deliberately bypasses find_existing/decide/_apply. That machinery answers
    "is this the same job, and does it outrank what I hold?" -- already settled
    for a row the user picked -- and it is what freezes jd_text at merge.py:179.
    """
    job_id = job.id
    if job_id is None:
        raise ValueError("cannot re-pull an unsaved job")
    if not job.url:
        return StageOutcome(job_id, "pull", "skipped", "no source URL"), None

    try:
        raw = job_from_url(job.url, agent=agent, allow_browser=allow_browser)
    except (httpx.HTTPError, PlaywrightError) as exc:
        logger.warning("repull job=%s failed", job_id, exc_info=exc)
        failure = StageFailure.from_exception(exc)
        detail = f"{failure.error_type}: {failure.message}"
        return StageOutcome(job_id, "pull", "failed", detail), failure

    if raw is None or not raw.jd_text.strip():
        detail = "no job description found"
        return (
            StageOutcome(job_id, "pull", "failed", detail),
            StageFailure(
                error_type="UrlFetchError", message=detail, traceback_tail=""
            ),
        )

    job.jd_text = raw.jd_text
    job.content_fingerprint = compute_content_fingerprint(raw.jd_text)
    if raw.location:
        job.location = raw.location

    company = raw.company or job.company
    title = raw.title or job.title
    if company != job.company or title != job.title:
        new_key = compute_dedup_key(company, title)
        if company_rename_collides(session, existing=job, dedup_key=new_key):
            # Another live row already holds that identity. Take the text and
            # leave company/title/dedup_key alone rather than stealing it.
            logger.info("repull job=%s kept identity (key collision)", job_id)
        else:
            job.company = company
            job.title = title
            job.dedup_key = new_key

    save_job(session, job)
    return StageOutcome(job_id, "pull", "ok", None), None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_redo_pull.py -v`
Expected: PASS — 6 passed

> If `RawJob` is not importable from `resume_agent.discovery.connectors.base`,
> find it with `grep -rn "class RawJob" src/` and fix the test import.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/redo.py tests/test_services_redo_pull.py
git commit -m "feat(redo): re-pull a job's description in place, bypassing the ingest freeze"
```

---

## Task 7: The redo orchestrator

**Files:**
- Modify: `src/resume_agent/services/redo.py`
- Test: `tests/test_services_redo.py`

**Interfaces:**
- Consumes: `repull_job`, `StageOutcome`, `REDO_STAGES` (Task 6); `StageScope` from `resume_agent.discovery.pipeline` (Task 2); `record_job_failure`, `resolve_job_failures` (Task 3); `TailorOutcome` (Task 5).
- Produces: `redo_jobs(session, *, job_ids, stages, deep=False, reporter=None, run_id=None) -> list[StageOutcome]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_services_redo.py`:

```python
import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.services import redo
from resume_agent.services.errors import StageFailure, list_error_records
from resume_agent.tailor.service import TailorOutcome
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    monkeypatch.setattr(redo, "enforce_active_budget", lambda: None)


def _rendered_job(session) -> Job:
    return save_job(
        session,
        Job(source="manual", jd_text="jd", company="Acme", title="Staff",
            status=JobStatus.rendered.value),
    )


def test_stages_run_in_pipeline_order_whatever_order_was_asked(session, monkeypatch):
    job = _rendered_job(session)
    seen: list[str] = []
    monkeypatch.setattr(
        redo, "_run_pull",
        lambda *a, **k: (seen.append("pull") or [])
    )
    monkeypatch.setattr(
        redo, "_run_extract",
        lambda *a, **k: (seen.append("extract") or [])
    )
    monkeypatch.setattr(
        redo, "_run_tailor",
        lambda *a, **k: (seen.append("tailor") or [])
    )

    redo.redo_jobs(
        session, job_ids=[job.id], stages=["tailor", "extract", "pull"]
    )

    assert seen == ["pull", "extract", "tailor"]


def test_tailor_failure_is_recorded_as_a_job_error(session, monkeypatch):
    job = _rendered_job(session)
    failure = StageFailure(
        error_type="ValueError", message="no match-plan agent", traceback_tail="tb"
    )
    monkeypatch.setattr(
        redo,
        "tailor",
        lambda *a, **k: TailorOutcome(versions={}, failures={job.id: failure}),
    )

    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])

    assert [o.status for o in outcomes] == ["failed"]
    records = list_error_records(session, "open")
    assert len(records) == 1
    assert records[0].kind == "job"
    assert records[0].source_label == f"job:{job.id}:tailor"


def test_tailor_success_resolves_an_earlier_failure(session, monkeypatch):
    job = _rendered_job(session)
    failure = StageFailure(error_type="ValueError", message="boom", traceback_tail="")
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={}, failures={job.id: failure}),
    )
    redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])
    assert len(list_error_records(session, "open")) == 1

    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )
    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])

    assert [o.status for o in outcomes] == ["ok"]
    assert list_error_records(session, "open") == []


def test_missing_job_is_skipped_not_fatal(session, monkeypatch):
    job = _rendered_job(session)
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )

    outcomes = redo.redo_jobs(session, job_ids=[job.id, 9999], stages=["tailor"])

    statuses = {o.job_id: o.status for o in outcomes}
    assert statuses[job.id] == "ok"
    assert statuses[9999] == "skipped"


def test_render_skips_a_job_with_no_versions(session):
    job = _rendered_job(session)

    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["render"])

    assert outcomes[0].status == "skipped"
    assert outcomes[0].detail == "no resume version"


def test_redo_never_regresses_a_rendered_job(session, monkeypatch):
    job = _rendered_job(session)
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )
    monkeypatch.setattr(redo, "_run_extract", lambda *a, **k: [])

    redo.redo_jobs(session, job_ids=[job.id], stages=["extract", "tailor"])

    session.refresh(job)
    assert job.status == JobStatus.rendered.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_redo.py -v`
Expected: FAIL — `AttributeError: module 'resume_agent.services.redo' has no attribute 'redo_jobs'`

- [ ] **Step 3: Write the orchestrator**

Append to `src/resume_agent/services/redo.py` (and add the imports listed at the top of the block):

```python
from collections.abc import Sequence

from resume_agent.config import get_settings
from resume_agent.discovery.pipeline import StageScope, run_extract, run_filter, run_score
from resume_agent.discovery.search_config import load_search_config
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.render.export import resume_download_name  # noqa: F401  (kept for parity)
from resume_agent.services.agents import build_discovery_bundle, build_url_extract_agent
from resume_agent.services.discovery import _skill_artifacts
from resume_agent.services.errors import record_job_failure, resolve_job_failures
from resume_agent.services.rendering import render_resume_version
from resume_agent.services.tailoring import tailor
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import FACTS_PATH, SEARCH_PATH
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    resume_versions_for_job,
)


def _record(session, job, stage, failure, run_id, model=None) -> None:
    """Persist a failure. Never let bookkeeping turn a partial run into a total one."""
    try:
        record_job_failure(
            session, job=job, stage=stage, failure=failure, run_id=run_id, model=model
        )
    except Exception:  # noqa: BLE001 - recording must never mask the real work
        logger.warning("could not record failure for job=%s stage=%s", job.id, stage,
                       exc_info=True)


def _settle(session, job, stage, outcome, failure, run_id) -> StageOutcome:
    if outcome.status == "failed" and failure is not None:
        _record(session, job, stage, failure, run_id)
    elif outcome.status == "ok":
        resolve_job_failures(session, outcome.job_id, stage)
    return outcome


def _run_pull(session, jobs, run_id) -> list[StageOutcome]:
    agent = build_url_extract_agent()
    allow_browser = get_settings().browser_enabled
    outcomes = []
    for job in jobs:
        outcome, failure = repull_job(
            session, job, agent=agent, allow_browser=allow_browser
        )
        outcomes.append(_settle(session, job, "pull", outcome, failure, run_id))
    return outcomes


def _run_extract(session, jobs, run_id) -> list[StageOutcome]:
    """Re-run extract -> filter -> score over these ids, forward-only.

    run_relevance is deliberately not run: it exists to reject off-target raw
    rows, so under never_regress it is a guaranteed no-op.
    """
    config = load_search_config(SEARCH_PATH)
    facts = load_facts(FACTS_PATH)
    matrix, cluster_map = _skill_artifacts(FACTS_PATH, facts)
    bundle = build_discovery_bundle()
    scope = StageScope(
        job_ids=frozenset(job.id for job in jobs if job.id is not None),
        any_status=True,
        never_regress=True,
    )
    run_extract(
        session, bundle.extract, scope=scope,
        industry_classifier=bundle.industry_classifier,
    )
    run_filter(session, config, scope)
    run_score(
        session, facts, bundle.fit, canonicalizer=bundle.canonicalizer,
        scope=scope, matrix=matrix, cluster_map=cluster_map,
    )
    outcomes = []
    for job in jobs:
        assert job.id is not None
        outcomes.append(
            _settle(session, job, "extract",
                    StageOutcome(job.id, "extract", "ok", None), None, run_id)
        )
    return outcomes


def _run_tailor(session, jobs, run_id, deep) -> list[StageOutcome]:
    from resume_agent.services.tailoring import DEFAULT_REVIEW, DEFAULT_REVIEW_DEEP

    ids = [job.id for job in jobs if job.id is not None]
    outcome = tailor(
        session,
        job_ids=ids,
        review_path=DEFAULT_REVIEW_DEEP if deep else DEFAULT_REVIEW,
    )
    results = []
    for job in jobs:
        assert job.id is not None
        failure = outcome.failures.get(job.id)
        if failure is not None:
            detail = f"{failure.error_type}: {failure.message}"
            results.append(
                _settle(session, job, "tailor",
                        StageOutcome(job.id, "tailor", "failed", detail),
                        failure, run_id)
            )
        else:
            results.append(
                _settle(session, job, "tailor",
                        StageOutcome(job.id, "tailor", "ok", None), None, run_id)
            )
    return results


def _render_target(session, job_id: int) -> int | None:
    """The Application's chosen version, else the highest-id version."""
    application = application_for_job(session, job_id)
    if application is not None and application.resume_version_id is not None:
        return application.resume_version_id
    versions = resume_versions_for_job(session, job_id)
    if not versions:
        return None
    return max(version.id or 0 for version in versions) or None


def _run_render(session, jobs, run_id) -> list[StageOutcome]:
    outcomes = []
    for job in jobs:
        assert job.id is not None
        version_id = _render_target(session, job.id)
        if version_id is None:
            outcomes.append(
                StageOutcome(job.id, "render", "skipped", "no resume version")
            )
            continue
        try:
            render_resume_version(session, version_id)
        except Exception as exc:  # noqa: BLE001 - isolate one job's render failure
            logger.warning("render job=%s failed", job.id, exc_info=exc)
            failure = StageFailure.from_exception(exc)
            outcomes.append(
                _settle(
                    session, job, "render",
                    StageOutcome(job.id, "render", "failed",
                                 f"{failure.error_type}: {failure.message}"),
                    failure, run_id,
                )
            )
            continue
        outcomes.append(
            _settle(session, job, "render",
                    StageOutcome(job.id, "render", "ok", None), None, run_id)
        )
    return outcomes


def redo_jobs(
    session: Session,
    *,
    job_ids: Sequence[int],
    stages: Sequence[RedoStage],
    deep: bool = False,
    reporter: ProgressReporter | None = None,
    run_id: str | None = None,
) -> list[StageOutcome]:
    """Re-run the chosen stages over the chosen jobs, stage-major.

    Inputs are validated at the API boundary (RedoParams): non-empty and
    deduped. This function trusts them.
    """
    enforce_active_budget()
    ordered = [stage for stage in REDO_STAGES if stage in set(stages)]
    found = {job_id: get_job(session, job_id) for job_id in job_ids}
    jobs = [job for job in found.values() if job is not None]

    outcomes: list[StageOutcome] = [
        StageOutcome(job_id, ordered[0], "skipped", "job not found")
        for job_id, job in found.items()
        if job is None
    ]
    if not jobs:
        return outcomes

    runners = {
        "pull": lambda: _run_pull(session, jobs, run_id),
        "extract": lambda: _run_extract(session, jobs, run_id),
        "tailor": lambda: _run_tailor(session, jobs, run_id, deep),
        "render": lambda: _run_render(session, jobs, run_id),
    }
    for index, stage in enumerate(ordered):
        if reporter:
            reporter.begin(len(jobs), f"Redo: {stage}",
                           phase_index=index + 1, phase_count=len(ordered))
        outcomes.extend(runners[stage]())
        if reporter:
            reporter.step(len(jobs))
    if reporter:
        reporter.done()
    return outcomes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_redo.py tests/test_services_redo_pull.py -v`
Expected: PASS

> The `_skill_artifacts` import is a private helper in `services/discovery.py`.
> If importing a private name across modules trips lint, rename it to
> `skill_artifacts` in `services/discovery.py` and update its two internal
> callers in the same commit.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/redo.py tests/test_services_redo.py
git commit -m "feat(redo): orchestrate pull/extract/tailor/render over explicit jobs"
```

---

## Task 8: `POST /api/redo`

**Files:**
- Modify: `src/resume_agent/api/schemas/runs.py`
- Modify: `src/resume_agent/api/routers/runs.py`
- Test: `tests/api/test_redo_endpoint.py`

**Interfaces:**
- Consumes: `redo_jobs`, `RedoStage` (Task 7); `launch`, `session_work` from `resume_agent.api.runs.launch`.
- Produces: `RedoParams`, `StageOutcomeOut`, `RedoResultOut`; `POST /api/redo` returning `202` + `RunOut`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_redo_endpoint.py`:

```python
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client(tmp_path) -> TestClient:
    # create_app takes db_url (api/app.py:78), not a path.
    return TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'test.db'}"))


def test_redo_rejects_empty_job_ids(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/redo", json={"jobIds": [], "stages": ["tailor"]}
        )
    assert response.status_code == 422


def test_redo_rejects_empty_stages(tmp_path):
    with _client(tmp_path) as client:
        response = client.post("/api/redo", json={"jobIds": [1], "stages": []})
    assert response.status_code == 422


def test_redo_rejects_an_unknown_stage(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/redo", json={"jobIds": [1], "stages": ["teleport"]}
        )
    assert response.status_code == 422


def test_redo_dedupes_repeated_ids_and_stages():
    from resume_agent.api.schemas.runs import RedoParams

    params = RedoParams(jobIds=[3, 3, 1], stages=["tailor", "tailor"])

    assert params.job_ids == [3, 1]     # order preserved, duplicates dropped
    assert params.stages == ["tailor"]


def test_redo_returns_202_with_a_run(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/redo", json={"jobIds": [1], "stages": ["tailor"]}
        )
    assert response.status_code == 202
    assert response.json()["kind"] == "redo"
```

> `tests/api/conftest.py` already isolates settings and the runs root for every
> API test via autouse fixtures, so no extra setup is needed here.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_redo_endpoint.py -v`
Expected: FAIL — 404 on `/api/redo`, and `ImportError` for `RedoParams`.

- [ ] **Step 3: Add the schemas**

In `src/resume_agent/api/schemas/runs.py`, add:

```python
from typing import Literal

from pydantic import Field, field_validator

from resume_agent.services.redo import RedoStage


def _dedupe(values: list) -> list:
    """Order-preserving dedupe."""
    return list(dict.fromkeys(values))


class RedoParams(CamelModel):
    """Which jobs to redo and which stages to run.

    Validated here and nowhere deeper: redo_jobs trusts its inputs. Deduping
    stages matters because ["tailor", "tailor"] would otherwise bill twice.
    """

    job_ids: list[int] = Field(min_length=1)
    stages: list[RedoStage] = Field(min_length=1)
    deep: bool = False

    @field_validator("job_ids", "stages")
    @classmethod
    def _drop_duplicates(cls, value: list) -> list:
        return _dedupe(value)


class StageOutcomeOut(CamelModel):
    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None


class RedoResultOut(CamelModel):
    outcomes: list[StageOutcomeOut] = Field(default_factory=list)
```

- [ ] **Step 4: Add the endpoint**

In `src/resume_agent/api/routers/runs.py`, add to the imports:

```python
from resume_agent.api.schemas.runs import RedoParams, RedoResultOut, StageOutcomeOut
from resume_agent.services.redo import redo_jobs
```

Add the endpoint after `launch_tailor`:

```python
@router.post("/redo", response_model=RunOut, status_code=202)
def launch_redo(
    params: RedoParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def do_redo(session, reporter):
        outcomes = redo_jobs(
            session,
            job_ids=params.job_ids,
            stages=params.stages,
            deep=params.deep,
            reporter=reporter,
            run_id=reporter.run_id,
        )
        return RedoResultOut(
            outcomes=[
                StageOutcomeOut(
                    job_id=outcome.job_id,
                    stage=outcome.stage,
                    status=outcome.status,
                    detail=outcome.detail,
                )
                for outcome in outcomes
            ]
        ).model_dump(by_alias=True)

    return launch(mgr, "redo", session_work(engine, do_redo))
```

- [ ] **Step 5: Run tests, then regenerate the contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_redo_endpoint.py -v`
Expected: PASS

Then: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS — the drift gate accepts the regenerated contract.

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/api/schemas/runs.py src/resume_agent/api/routers/runs.py tests/api/test_redo_endpoint.py contracts/
git commit -m "feat(api): add POST /api/redo with boundary-validated params"
```

---

## Task 9: Typed job failure details and paginated errors

**Files:**
- Modify: `src/resume_agent/api/schemas/errors.py`
- Modify: `src/resume_agent/api/routers/errors.py`
- Test: `tests/api/test_errors_endpoint.py` (create or append if it exists)

**Interfaces:**
- Consumes: `RedoStage` (Task 6); `page_from_slice` from `resume_agent.services.pagination`.
- Produces: `JobFailureDetails`; `ErrorRecordOut.job_details`; `ErrorRecordsOut.pagination`; `GET /api/errors?page=&pageSize=`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_errors_endpoint.py`:

```python
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import make_engine
from resume_agent.services.errors import StageFailure, record_error, record_job_failure


def _client(tmp_path) -> TestClient:
    # create_app takes db_url (api/app.py:78), not a path.
    return TestClient(create_app(db_url=f"sqlite:///{tmp_path / 'test.db'}"))


def test_job_record_exposes_typed_details(tmp_path):
    with _client(tmp_path) as client:
        from sqlmodel import Session

        from resume_agent.tracking.repository import save_job
        from resume_agent.tracking.tables import Job

        engine = client.app.state.engine
        with Session(engine) as session:
            job = save_job(
                session,
                Job(source="manual", jd_text="jd", company="Acme", title="Staff"),
            )
            record_job_failure(
                session,
                job=job,
                stage="tailor",
                failure=StageFailure(
                    error_type="ValueError", message="boom", traceback_tail="tb"
                ),
                model="openai:gpt-5",
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.status_code == 200
    record = response.json()["records"][0]
    details = record["jobDetails"]
    assert details["jobId"] == job.id
    assert details["company"] == "Acme"
    assert details["stage"] == "tailor"
    assert details["errorType"] == "ValueError"
    assert details["model"] == "openai:gpt-5"
    assert details["tracebackTail"] == "tb"


def test_source_record_has_no_job_details(tmp_path):
    with _client(tmp_path) as client:
        from sqlmodel import Session

        with Session(client.app.state.engine) as session:
            record_error(
                session, kind="source", source_label="workday:acme", message="HTTP 500"
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.json()["records"][0]["jobDetails"] is None


def test_unparseable_details_yield_none_not_500(tmp_path):
    with _client(tmp_path) as client:
        from sqlmodel import Session

        with Session(client.app.state.engine) as session:
            record_error(
                session,
                kind="job",
                source_label="job:1:tailor",
                message="legacy",
                details={"totally": "different shape"},
            )

        response = client.get("/api/errors", params={"status": "open"})

    assert response.status_code == 200
    assert response.json()["records"][0]["jobDetails"] is None


def test_errors_list_paginates(tmp_path):
    with _client(tmp_path) as client:
        from sqlmodel import Session

        with Session(client.app.state.engine) as session:
            for index in range(7):
                record_error(
                    session, kind="source", source_label=f"workday:acme-{index}",
                    message="HTTP 500",
                )

        response = client.get(
            "/api/errors", params={"status": "open", "page": 2, "pageSize": 3}
        )

    body = response.json()
    assert len(body["records"]) == 3
    assert body["pagination"]["page"] == 2
    assert body["pagination"]["pageSize"] == 3
    assert body["pagination"]["totalItems"] == 7
    assert body["pagination"]["totalPages"] == 3
```

> The app stores its engine on `app.state` (set by the lifespan in
> `api/app.py`). Confirm the attribute name there and use it consistently.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_errors_endpoint.py -v`
Expected: FAIL — `KeyError: 'jobDetails'`

- [ ] **Step 3: Add the schemas**

In `src/resume_agent/api/schemas/errors.py`:

```python
from typing import Literal

from resume_agent.services.redo import RedoStage


class JobFailureDetails(CamelModel):
    """The formatted diagnostic for one job's stage failure.

    Typed rather than a free-form map: an exposed dict's keys become a de facto
    contract with nothing holding them stable, and a schema flows into the
    generated TS client so the web side needs no hand-written shape.
    """

    job_id: int
    stage: RedoStage
    error_type: str
    message: str
    company: str | None = None
    title: str | None = None
    model: str | None = None
    traceback_tail: str = ""


class PageOut(CamelModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ErrorRecordOut(CamelModel):
    id: int
    kind: str
    source_label: str
    run_id: str | None = None
    message: str = ""
    status: str
    count: int = 1
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
    job_details: JobFailureDetails | None = None


class ErrorRecordsOut(CamelModel):
    records: list[ErrorRecordOut] = Field(default_factory=list)
    pagination: PageOut | None = None
```

> If a `PageOut`-equivalent already exists (check `api/schemas/` for whatever
> `/api/pipeline` returns), import and reuse it instead of declaring a second one.

- [ ] **Step 4: Project details and paginate in the router**

In `src/resume_agent/api/routers/errors.py`:

```python
from pydantic import ValidationError

from resume_agent.api.schemas.errors import JobFailureDetails, PageOut
from resume_agent.services.pagination import page_from_slice

MAX_PAGE_SIZE = 200


def _job_details(record: ErrorRecord) -> JobFailureDetails | None:
    """Project stored JSON into the typed schema.

    Persisted JSON written by an older build is untrusted input at a read
    boundary: a shape mismatch must degrade to None, never a 500.
    """
    if record.kind != "job" or not record.details_json:
        return None
    try:
        return JobFailureDetails.model_validate(record.details_json)
    except ValidationError:
        return None
```

Add `job_details=_job_details(record)` to the `ErrorRecordOut(...)` construction in `_row()`.

Replace `list_errors`:

```python
@router.get("/errors", response_model=ErrorRecordsOut)
def list_errors(
    status: ErrorStatus = Query("open"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE, alias="pageSize"),
    session: Session = Depends(get_session),
):
    records = list_error_records(session, status)
    window = paginate(records, page=page, page_size=page_size)
    return ErrorRecordsOut(
        records=[_row(record) for record in window.data],
        pagination=PageOut(
            page=window.page,
            page_size=window.page_size,
            total_items=window.total_items,
            total_pages=window.total_pages,
        ),
    )
```

Import `paginate` from `resume_agent.services.pagination`.

> `paginate` slices in Python because `list_error_records` already returns a
> list. Open error counts are bounded by `Clear all` and auto-resolve, so an
> in-memory slice is fine here; if that stops being true, push the limit into
> the query.

- [ ] **Step 5: Run tests, regenerate contract, verify**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_errors_endpoint.py tests/test_errors_service.py -v`
Expected: PASS

Then: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/api/schemas/errors.py src/resume_agent/api/routers/errors.py tests/api/test_errors_endpoint.py contracts/
git commit -m "feat(api): expose typed job failure details and paginate the errors list"
```

---

## Task 10: Redo dialog and run hook

**Files:**
- Create: `web/src/features/runs/use-redo-run.ts`
- Create: `web/src/features/runs/RedoDialog.tsx`
- Test: `web/src/features/runs/RedoDialog.test.tsx`

**Interfaces:**
- Consumes: `useLaunchRun` from `./use-launch-run`; generated types from `@/lib/api/schema`.
- Produces:
  - `useRedoRun(): { redo(jobIds: number[], stages: RedoStage[], deep: boolean): Promise<boolean> }`
  - `<RedoDialog open jobIds initialStages onOpenChange onLaunched? />`
  - `type RedoStage = "pull" | "extract" | "tailor" | "render"`

- [ ] **Step 1: Write the failing test**

Create `web/src/features/runs/RedoDialog.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RedoDialog } from "./RedoDialog";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function setup(props: Partial<React.ComponentProps<typeof RedoDialog>> = {}) {
  const onLaunch = vi.fn().mockResolvedValue(true);
  render(
    <RedoDialog
      open
      jobIds={[1, 2, 3]}
      initialStages={["tailor"]}
      onOpenChange={() => {}}
      onLaunch={onLaunch}
      {...props}
    />,
    { wrapper },
  );
  return { onLaunch };
}

describe("RedoDialog", () => {
  it("states the exact job count in the confirm button", () => {
    setup();
    expect(
      screen.getByRole("button", { name: /re-tailor 3 jobs/i }),
    ).toBeInTheDocument();
  });

  it("pre-ticks the stages it was opened with", () => {
    setup();
    expect(screen.getByRole("checkbox", { name: /re-tailor resume/i })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /re-pull job description/i }),
    ).not.toBeChecked();
  });

  it("pre-ticks re-extract when re-pull is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });

    await user.click(screen.getByRole("checkbox", { name: /re-pull job description/i }));

    expect(
      screen.getByRole("checkbox", { name: /re-extract criteria/i }),
    ).toBeChecked();
  });

  it("lets you untick the auto-ticked re-extract", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });

    await user.click(screen.getByRole("checkbox", { name: /re-pull job description/i }));
    await user.click(screen.getByRole("checkbox", { name: /re-extract criteria/i }));

    expect(
      screen.getByRole("checkbox", { name: /re-extract criteria/i }),
    ).not.toBeChecked();
  });

  it("launches with the ticked stages in pipeline order", async () => {
    const user = userEvent.setup();
    const { onLaunch } = setup({ initialStages: ["tailor"] });

    await user.click(screen.getByRole("checkbox", { name: /re-render pdf/i }));
    await user.click(screen.getByRole("button", { name: /re-tailor/i }));

    expect(onLaunch).toHaveBeenCalledWith([1, 2, 3], ["tailor", "render"], false);
  });

  it("disables launch when nothing is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: ["tailor"] });

    await user.click(screen.getByRole("checkbox", { name: /re-tailor resume/i }));

    expect(screen.getByRole("button", { name: /choose a stage/i })).toBeDisabled();
  });

  it("shows the deep-review switch only when re-tailor is ticked", async () => {
    const user = userEvent.setup();
    setup({ initialStages: [] });
    expect(screen.queryByRole("switch", { name: /deep review/i })).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: /re-tailor resume/i }));

    expect(screen.getByRole("switch", { name: /deep review/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/runs/RedoDialog.test.tsx`
Expected: FAIL — cannot resolve `./RedoDialog`

- [ ] **Step 3: Write the hook**

Create `web/src/features/runs/use-redo-run.ts`:

```ts
import { api, unwrap } from "@/lib/api/client";

import { useLaunchRun } from "./use-launch-run";

export type RedoStage = "pull" | "extract" | "tailor" | "render";

export function useRedoRun() {
  const { launch } = useLaunchRun();
  return {
    redo: (jobIds: number[], stages: RedoStage[], deep: boolean) =>
      launch("redo", () =>
        unwrap(api.POST("/api/redo", { body: { jobIds, stages, deep } })),
      ),
  };
}
```

- [ ] **Step 4: Write the dialog**

Create `web/src/features/runs/RedoDialog.tsx`:

```tsx
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";

import type { RedoStage } from "./use-redo-run";

// Pipeline order. The backend re-sorts too, but sending them ordered keeps the
// request readable and the button label honest.
const STAGES: { id: RedoStage; label: string; hint: string }[] = [
  {
    id: "pull",
    label: "Re-pull job description",
    hint: "Re-fetch the posting and replace its text.",
  },
  {
    id: "extract",
    label: "Re-extract criteria & fit score",
    hint: "Rebuild criteria and re-score against your profile.",
  },
  {
    id: "tailor",
    label: "Re-tailor resume",
    hint: "Write a new resume version. Existing versions are kept.",
  },
  { id: "render", label: "Re-render PDF", hint: "Re-render the selected version." },
];

const VERBS: Record<RedoStage, string> = {
  pull: "Re-pull",
  extract: "Re-extract",
  tailor: "Re-tailor",
  render: "Re-render",
};

export interface RedoDialogProps {
  open: boolean;
  jobIds: number[];
  initialStages: RedoStage[];
  onOpenChange: (open: boolean) => void;
  onLaunch: (
    jobIds: number[],
    stages: RedoStage[],
    deep: boolean,
  ) => Promise<boolean>;
}

export function RedoDialog(props: RedoDialogProps) {
  // Same closed->open remount guard as LaunchDialog: Base UI's Dialog stays
  // mounted through its exit animation, so remounting mid-close strands an
  // already-open popup that never hides.
  const [openState, setOpenState] = useState(() => ({
    isOpen: props.open,
    sequence: 0,
  }));
  if (props.open !== openState.isOpen) {
    setOpenState({
      isOpen: props.open,
      sequence: props.open ? openState.sequence + 1 : openState.sequence,
    });
  }
  const resetKey = [openState.sequence, props.jobIds.length].join(":");
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <RedoDialogBody key={resetKey} {...props} />
    </Dialog>
  );
}

function RedoDialogBody({
  jobIds,
  initialStages,
  onOpenChange,
  onLaunch,
}: RedoDialogProps) {
  const [selected, setSelected] = useState<Set<RedoStage>>(
    () => new Set(initialStages),
  );
  const [deep, setDeep] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);

  const ordered = STAGES.filter((stage) => selected.has(stage.id)).map((s) => s.id);
  const count = jobIds.length;
  const jobWord = `${count} job${count === 1 ? "" : "s"}`;
  const label = ordered.length
    ? `${ordered.map((stage) => VERBS[stage]).join(" + ")} ${jobWord}`
    : "Choose a stage";

  const toggle = (stage: RedoStage, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(stage);
        // Fresh text with stale criteria is a trap, so re-pull pre-ticks
        // re-extract. It stays untickable afterwards.
        if (stage === "pull") next.add("extract");
      } else {
        next.delete(stage);
      }
      return next;
    });

  const submit = async () => {
    setIsLaunching(true);
    try {
      if (await onLaunch(jobIds, ordered, deep)) onOpenChange(false);
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>Redo pipeline stages</DialogTitle>
        <DialogDescription>
          Re-run any stage on {jobWord}, whatever their status. Existing resume
          versions and PDFs are kept.
        </DialogDescription>
      </DialogHeader>

      <FieldSet>
        <FieldLegend variant="label">Stages</FieldLegend>
        <FieldGroup>
          {STAGES.map((stage) => {
            const inputId = `redo-stage-${stage.id}`;
            return (
              <Field key={stage.id} orientation="horizontal">
                <Checkbox
                  id={inputId}
                  checked={selected.has(stage.id)}
                  disabled={isLaunching}
                  onCheckedChange={(checked) => toggle(stage.id, Boolean(checked))}
                />
                <div>
                  <FieldLabel htmlFor={inputId}>{stage.label}</FieldLabel>
                  <FieldDescription>{stage.hint}</FieldDescription>
                </div>
              </Field>
            );
          })}
        </FieldGroup>
      </FieldSet>

      {selected.has("tailor") && (
        <Field orientation="horizontal">
          <Switch
            id="redo-deep-review"
            checked={deep}
            disabled={isLaunching}
            onCheckedChange={setDeep}
          />
          <div>
            <FieldLabel htmlFor="redo-deep-review">Deep review</FieldLabel>
            <FieldDescription>Full review panel; roughly 3–6× slower.</FieldDescription>
          </div>
        </Field>
      )}

      <DialogFooter>
        <Button
          variant="outline"
          disabled={isLaunching}
          onClick={() => onOpenChange(false)}
        >
          Cancel
        </Button>
        <Button disabled={!ordered.length || isLaunching} onClick={submit}>
          {isLaunching && <Spinner data-icon="inline-start" />}
          {isLaunching ? "Starting…" : label}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/runs/RedoDialog.test.tsx`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add web/src/features/runs/use-redo-run.ts web/src/features/runs/RedoDialog.tsx web/src/features/runs/RedoDialog.test.tsx
git commit -m "feat(web): add the redo stage-picker dialog and run hook"
```

---

## Task 11: `Redo…` on the pipeline board

**Files:**
- Modify: `web/src/features/pipeline/PipelineContainer.tsx`
- Test: `web/src/features/pipeline/PipelineContainer.test.tsx` (append)

**Interfaces:**
- Consumes: `RedoDialog`, `useRedoRun` (Task 10); existing `useSelection`, `BulkActionBar`.
- Produces: nothing new — a UI wiring task.

**Context:** `selection` (from `useSelection`) has `mode: "ids" | "allMatching"`, `ids: number[]`, `count`, `isAllMatching`. When `isAllMatching`, ids must be resolved from the query — mirror `useApprovedLaunchJobs`'s `fetchAllPages` over `/api/pipeline`, passing the active filter.

- [ ] **Step 1: Write the failing test**

Append to `web/src/features/pipeline/PipelineContainer.test.tsx`:

```tsx
it("opens redo for the current selection with re-tailor pre-ticked", async () => {
  const user = userEvent.setup();
  renderPipeline(
    statusAware([
      pipelineItem(9, "tailored", "Operator"),
      pipelineItem(10, "rendered", "Architect"),
    ]),
  );

  await user.click(
    await screen.findByRole("checkbox", { name: /Select tailored Co Operator/ }),
  );
  await user.click(screen.getByRole("button", { name: /^redo/i }));

  expect(
    await screen.findByRole("checkbox", { name: /re-tailor resume/i }),
  ).toBeChecked();
  expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
});

it("allows redo on a rendered job", async () => {
  const user = userEvent.setup();
  renderPipeline(statusAware([pipelineItem(10, "rendered", "Architect")]));

  await user.click(
    await screen.findByRole("checkbox", { name: /Select rendered Co Architect/ }),
  );
  await user.click(screen.getByRole("button", { name: /^redo/i }));

  expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
});
```

> Reuse the file's existing `renderPipeline`, `statusAware`, and `pipelineItem`
> helpers. Match the checkbox accessible-name format the existing tests assert
> (`/Select tailored Co Operator/`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/pipeline/PipelineContainer.test.tsx`
Expected: FAIL — no button matching `/^redo/i`

- [ ] **Step 3: Wire the dialog in**

In `web/src/features/pipeline/PipelineContainer.tsx`, add imports:

```tsx
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun } from "@/features/runs/use-redo-run";
import { useSelectedJobIds } from "@/features/board/use-selected-job-ids";
```

Add state next to `launchMode`:

```tsx
const [redoOpen, setRedoOpen] = useState(false);
const redoRun = useRedoRun();
const redoJobIds = useSelectedJobIds("pipeline", selection, filter, redoOpen);
```

Add the action inside `<BulkActionBar>`, after the Archive button:

```tsx
<Button
  size="sm"
  variant="outline"
  disabled={!selection.count}
  onClick={() => setRedoOpen(true)}
>
  Redo…
</Button>
```

Render the dialog next to `LaunchDialog`:

```tsx
<RedoDialog
  open={redoOpen}
  jobIds={redoJobIds}
  initialStages={["tailor"]}
  onOpenChange={setRedoOpen}
  onLaunch={(jobIds, stages, deep) => redoRun.redo(jobIds, stages, deep)}
/>
```

- [ ] **Step 4: Add the selection-resolving hook**

Create `web/src/features/board/use-selected-job-ids.ts`:

```ts
import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type PipelineItem = components["schemas"]["PipelineItem"];

/**
 * The selected job ids. "Select all matching" holds no ids, only a count, so
 * it is resolved by re-running the board query — the same approach
 * useApprovedLaunchJobs takes.
 */
export function useSelectedJobIds(
  board: "pipeline",
  selection: { mode: string; ids: number[] },
  filter: { status: Set<string> },
  enabled: boolean,
): number[] {
  const needsResolve = enabled && selection.mode === "allMatching";
  const query = useQuery({
    queryKey: ["selected-job-ids", board, [...filter.status].sort()],
    enabled: needsResolve,
    queryFn: () =>
      fetchAllPages<PipelineItem>((page) =>
        api.GET("/api/pipeline", {
          params: {
            query: {
              status: [...filter.status].join(",") || undefined,
              sortBy: "recency",
              page,
              pageSize: 200,
            },
          },
        }),
      ),
  });
  if (selection.mode !== "allMatching") return selection.ids;
  return (query.data ?? []).map((row) => row.jobId);
}
```

> Check `useBoardFilters`'s shape before finalising the `filter` parameter type;
> pass through whatever query params `useBoardQuery` builds so the resolved ids
> match what the user sees. If a shared filter→query-params helper already
> exists, use it rather than rebuilding the mapping here.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/pipeline`
Expected: PASS

- [ ] **Step 6: Type-check and commit**

```bash
cd web && npx tsc --noEmit
git add web/src/features/pipeline/PipelineContainer.tsx web/src/features/pipeline/PipelineContainer.test.tsx web/src/features/board/use-selected-job-ids.ts
git commit -m "feat(web): add Redo to the pipeline bulk bar for any-status selections"
```

---

## Task 12: `Redo…` on a single job

**Files:**
- Modify: `web/src/components/JobModal.tsx`
- Test: `web/src/components/JobModal.test.tsx` (append; create if absent)

**Interfaces:**
- Consumes: `RedoDialog`, `useRedoRun` (Task 10).

- [ ] **Step 1: Write the failing test**

Append to `web/src/components/JobModal.test.tsx`:

```tsx
it("opens redo for the single job it is showing", async () => {
  const user = userEvent.setup();
  renderJobModal({ jobId: 42 });

  await user.click(await screen.findByRole("button", { name: /^redo/i }));

  expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
});
```

> Reuse the file's existing render helper. If `JobModal.test.tsx` does not
> exist, create it modelled on `web/src/features/pipeline/PipelineContainer.test.tsx`
> — same QueryClient wrapper and MSW/fetch stubbing approach.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/JobModal.test.tsx`
Expected: FAIL — no button matching `/^redo/i`

- [ ] **Step 3: Wire it in**

In `web/src/components/JobModal.tsx`, add:

```tsx
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun } from "@/features/runs/use-redo-run";
```

```tsx
const [redoOpen, setRedoOpen] = useState(false);
const redoRun = useRedoRun();
```

Add a `Redo…` button to the modal's action row, and render:

```tsx
<RedoDialog
  open={redoOpen}
  jobIds={[jobId]}
  initialStages={["tailor"]}
  onOpenChange={setRedoOpen}
  onLaunch={(jobIds, stages, deep) => redoRun.redo(jobIds, stages, deep)}
/>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/components/JobModal.test.tsx`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

```bash
cd web && npx tsc --noEmit
git add web/src/components/JobModal.tsx web/src/components/JobModal.test.tsx
git commit -m "feat(web): add per-job Redo to the job modal"
```

---

## Task 13: Formatted failure triage in the dashboard

**Files:**
- Create: `web/src/features/dashboard/JobFailureRow.tsx`
- Modify: `web/src/features/dashboard/AttentionCard.tsx`
- Test: `web/src/features/dashboard/AttentionCard.test.tsx` (append)

**Interfaces:**
- Consumes: `ErrorRecord` (regenerated type carrying `jobDetails`) from `@/features/errors/use-errors`; `RedoDialog`, `useRedoRun` (Task 10).
- Produces: `<JobFailureRow record onRetry onDismiss onResolve isBusy />`.

- [ ] **Step 1: Write the failing test**

Append to `web/src/features/dashboard/AttentionCard.test.tsx`:

```tsx
const jobRecord = {
  id: 1,
  kind: "job",
  sourceLabel: "job:42:tailor",
  message: "ValueError: match_plan_enabled requires a match-plan agent",
  status: "open",
  count: 3,
  runId: null,
  firstSeenAt: new Date().toISOString(),
  lastSeenAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  jobDetails: {
    jobId: 42,
    stage: "tailor",
    errorType: "ValueError",
    message: "match_plan_enabled requires a match-plan agent",
    company: "Acme",
    title: "Staff Engineer",
    model: "openai:gpt-5",
    tracebackTail: "Traceback (most recent call last): ...",
  },
};

const sourceRecord = {
  ...jobRecord,
  id: 2,
  kind: "source",
  sourceLabel: "workday:acme",
  message: "HTTP 500",
  count: 1,
  jobDetails: null,
};

it("groups failures by kind", async () => {
  renderAttentionCard([jobRecord, sourceRecord]);

  expect(await screen.findByRole("heading", { name: /jobs/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /sources/i })).toBeInTheDocument();
});

it("formats a job failure instead of showing the raw label", async () => {
  renderAttentionCard([jobRecord]);

  expect(await screen.findByText(/Acme — Staff Engineer/)).toBeInTheDocument();
  expect(screen.getByText("tailor")).toBeInTheDocument();
  expect(screen.getByText(/openai:gpt-5/)).toBeInTheDocument();
  expect(screen.getByText(/×3/)).toBeInTheDocument();
  expect(screen.queryByText("job:42:tailor")).toBeNull();
});

it("hides the traceback until the expander is opened", async () => {
  const user = userEvent.setup();
  renderAttentionCard([jobRecord]);

  expect(screen.queryByText(/Traceback \(most recent call last\)/)).toBeNull();
  await user.click(await screen.findByRole("button", { name: /technical details/i }));

  expect(screen.getByText(/Traceback \(most recent call last\)/)).toBeInTheDocument();
});

it("opens redo for that job and stage when Retry is clicked", async () => {
  const user = userEvent.setup();
  renderAttentionCard([jobRecord]);

  await user.click(await screen.findByRole("button", { name: /retry/i }));

  expect(
    await screen.findByRole("checkbox", { name: /re-tailor resume/i }),
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: /re-pull job description/i }),
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: /re-tailor 1 job/i })).toBeEnabled();
});

it("shows only the first 8 rows until expanded", async () => {
  const user = userEvent.setup();
  const many = Array.from({ length: 12 }, (_, index) => ({
    ...jobRecord,
    id: index + 1,
    jobDetails: { ...jobRecord.jobDetails, jobId: index + 1 },
  }));
  renderAttentionCard(many);

  expect(await screen.findAllByRole("button", { name: /retry/i })).toHaveLength(8);
  await user.click(screen.getByRole("button", { name: /show all 12/i }));

  expect(screen.getAllByRole("button", { name: /retry/i })).toHaveLength(12);
});
```

> Add a `renderAttentionCard(records)` helper at the top of the file that
> renders `<AttentionCard />` inside the existing QueryClient wrapper with
> `GET /api/errors` stubbed to return `{ records, pagination: {...} }`. Follow
> whatever stubbing approach the file already uses for `useErrorRecords`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard/AttentionCard.test.tsx`
Expected: FAIL — no `jobs` heading; raw `job:42:tailor` still rendered.

- [ ] **Step 3: Write `JobFailureRow`**

Create `web/src/features/dashboard/JobFailureRow.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ErrorRecord } from "@/features/errors/use-errors";

import { timeAgo } from "./time-ago";

interface JobFailureRowProps {
  record: ErrorRecord;
  onRetry: () => void;
  onDismiss: () => void;
  onResolve: () => void;
  isBusy: boolean;
}

export function JobFailureRow({
  record,
  onRetry,
  onDismiss,
  onResolve,
  isBusy,
}: JobFailureRowProps) {
  const details = record.jobDetails;
  // A job record without details is a legacy or unparseable row; fall back to
  // the flat message rather than rendering an empty shell.
  const heading = details
    ? `${details.company ?? "Unknown company"} — ${details.title ?? "Untitled role"}`
    : record.sourceLabel;

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        {details ? (
          <a
            href={`/pipeline?job=${details.jobId}`}
            className="min-w-0 flex-1 truncate text-sm font-medium underline-offset-4 hover:underline"
          >
            {heading}
          </a>
        ) : (
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{heading}</span>
        )}
        {details && <Badge variant="secondary">{details.stage}</Badge>}
        {record.count > 1 && (
          <span className="text-xs text-muted-foreground">×{record.count}</span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{record.message}</p>
      <p className="text-xs text-muted-foreground">
        {details?.model ? `${details.model} · ` : ""}
        {timeAgo(Date.parse(record.lastSeenAt))}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {details?.tracebackTail ? (
          <details className="min-w-0 flex-1">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Technical details
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted p-2 text-[0.7rem]">
              {details.tracebackTail}
            </pre>
          </details>
        ) : (
          <span className="flex-1" />
        )}
        {details && (
          <Button size="sm" variant="outline" disabled={isBusy} onClick={onRetry}>
            Retry
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={isBusy} onClick={onDismiss}>
          Dismiss
        </Button>
        <Button size="sm" variant="outline" disabled={isBusy} onClick={onResolve}>
          Resolve
        </Button>
      </div>
    </li>
  );
}
```

> `<details>`/`<summary>` gives an accessible expander with no extra dependency
> and satisfies the `getByRole("button", { name: /technical details/i })` query.

- [ ] **Step 4: Rewrite `AttentionCard`**

Replace `web/src/features/dashboard/AttentionCard.tsx`:

```tsx
import { useState } from "react";
import { CircleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  useDismissAllErrors,
  useDismissError,
  useErrorRecords,
  useResolveError,
  type ErrorRecord,
} from "@/features/errors/use-errors";
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun, type RedoStage } from "@/features/runs/use-redo-run";

import { JobFailureRow } from "./JobFailureRow";

const VISIBLE_LIMIT = 8;
const GROUPS: { kind: string; heading: string }[] = [
  { kind: "job", heading: "Jobs" },
  { kind: "source", heading: "Sources" },
  { kind: "run", heading: "Runs" },
];

interface RetryTarget {
  jobId: number;
  stage: RedoStage;
}

export function AttentionCard() {
  const records = useErrorRecords("open");
  const dismiss = useDismissError();
  const resolve = useResolveError();
  const clearAll = useDismissAllErrors();
  const redoRun = useRedoRun();
  const [showAll, setShowAll] = useState(false);
  const [retry, setRetry] = useState<RetryTarget | null>(null);

  const rows = records.data?.records ?? [];
  const visible = showAll ? rows : rows.slice(0, VISIBLE_LIMIT);
  const isBusy = dismiss.isPending || resolve.isPending;

  const grouped = GROUPS.map((group) => ({
    ...group,
    items: visible.filter((row) => row.kind === group.kind),
  })).filter((group) => group.items.length > 0);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <CircleAlert className="text-destructive" aria-hidden="true" />
          Attention needed
          {rows.length ? <Badge variant="destructive">{rows.length}</Badge> : null}
        </CardTitle>
        {rows.length ? (
          <Button
            size="sm"
            variant="outline"
            disabled={clearAll.isPending}
            onClick={() => clearAll.mutate()}
          >
            {clearAll.isPending ? <Spinner data-icon="inline-start" /> : null}
            Clear all
          </Button>
        ) : null}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {records.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            Loading errors…
          </div>
        ) : null}

        {records.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not load errors</AlertTitle>
            <AlertDescription className="flex items-center justify-between gap-3">
              <span>Recent failures are temporarily unavailable.</span>
              <Button size="sm" variant="outline" onClick={() => void records.refetch()}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {!records.isPending && !records.isError && !rows.length ? (
          <p className="text-sm text-muted-foreground">No open errors.</p>
        ) : null}

        {grouped.map((group) => (
          <section key={group.kind} className="flex flex-col gap-2">
            <h3 className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              {group.heading}
            </h3>
            <ul className="flex flex-col gap-3">
              {group.items.map((row) =>
                row.kind === "job" ? (
                  <JobFailureRow
                    key={row.id}
                    record={row}
                    isBusy={isBusy}
                    onRetry={() => openRetry(row, setRetry)}
                    onDismiss={() => dismiss.mutate({ id: row.id })}
                    onResolve={() => resolve.mutate({ id: row.id })}
                  />
                ) : (
                  <PlainErrorRow
                    key={row.id}
                    record={row}
                    isBusy={isBusy}
                    onDismiss={() => dismiss.mutate({ id: row.id })}
                    onResolve={() => resolve.mutate({ id: row.id })}
                  />
                ),
              )}
            </ul>
          </section>
        ))}

        {!showAll && rows.length > VISIBLE_LIMIT ? (
          <Button size="sm" variant="ghost" onClick={() => setShowAll(true)}>
            Show all {rows.length}
          </Button>
        ) : null}
      </CardContent>

      <RedoDialog
        open={retry !== null}
        jobIds={retry ? [retry.jobId] : []}
        initialStages={retry ? [retry.stage] : []}
        onOpenChange={(open) => {
          if (!open) setRetry(null);
        }}
        onLaunch={(jobIds, stages, deep) => redoRun.redo(jobIds, stages, deep)}
      />
    </Card>
  );
}

function openRetry(
  row: ErrorRecord,
  setRetry: (target: RetryTarget | null) => void,
): void {
  if (!row.jobDetails) return;
  setRetry({
    jobId: row.jobDetails.jobId,
    stage: row.jobDetails.stage as RedoStage,
  });
}

function PlainErrorRow({
  record,
  isBusy,
  onDismiss,
  onResolve,
}: {
  record: ErrorRecord;
  isBusy: boolean;
  onDismiss: () => void;
  onResolve: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{record.sourceLabel}</span>
        <span className="text-xs text-muted-foreground">
          {record.message}
          {record.count > 1 ? ` · seen ${record.count}×` : ""}
        </span>
      </div>
      <Button size="sm" variant="ghost" disabled={isBusy} onClick={onDismiss}>
        Dismiss
      </Button>
      <Button size="sm" variant="outline" disabled={isBusy} onClick={onResolve}>
        Resolve
      </Button>
    </li>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/dashboard`
Expected: PASS

- [ ] **Step 6: Type-check and commit**

```bash
cd web && npx tsc --noEmit
git add web/src/features/dashboard/AttentionCard.tsx web/src/features/dashboard/JobFailureRow.tsx web/src/features/dashboard/AttentionCard.test.tsx
git commit -m "feat(web): format and group failure triage with a Retry into redo"
```

---

## Task 14: Full verification and documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the whole backend suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS — no regressions anywhere.

- [ ] **Step 2: Run the whole web suite and type-check**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 3: Lint**

Run: `ruff check`
Expected: no findings.

- [ ] **Step 4: Verify the contract is in sync**

Run: `bash scripts/gen_ts_client.sh && git diff --exit-code contracts/`
Expected: no diff — the generated contract already matches the code.

- [ ] **Step 5: Document the invariants in `CLAUDE.md`**

Add to the **Core invariants** section, after "Archive, delete, prune":

```markdown
### Redo — forward-only, never destructive

`services/redo.py` re-runs any stage (`pull`/`extract`/`tailor`/`render`) over
explicitly chosen jobs at any status. It exists because the automatic paths are
deliberately one-way: `merge.decide()` freezes `jd_text` once a job leaves
`raw`, and `reprocess()` skips anything `has_progress()` covers. Those guards
stay; redo is the explicit escape hatch, never a mode.

Three invariants, all enforced by `tracking/stages.py::advance`:

- **Never regresses.** Status is a high-water mark. A rendered job stays
  rendered through a re-pull + re-extract + re-tailor.
- **Never rejects.** `rejected` ranks below `raw`, so the filter and relevance
  gates cannot fire under `never_regress`. Fresh fit scores are still written.
- **Never deletes.** New `ResumeVersion` rows are appended under an incremented
  `attempt`; `tailor_model` records which model produced them.

`StageScope(job_ids, any_status, never_regress)` is how the funnel stages in
`discovery/pipeline.py` run over explicit ids. `StageScope()` reproduces the
automatic funnel exactly — that default is the regression guard.

Re-pull deliberately bypasses `find_existing`/`decide`/`_apply` and refreshes
the row in place; a `dedup_key` that would collide with a sibling keeps the old
identity and takes only the text.

Per-job stage failures are durable: `services/errors.py::record_job_failure`
writes an `ErrorRecord` with `kind="job"` keyed `job:{id}:{stage}` (so repeats
coalesce into `count`), and `resolve_job_failures` closes it when that stage
later succeeds. `gather_isolated` no longer discards the exception — the cause
reaches the run result, the log, and the dashboard.
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the redo invariants and job failure records"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Status ladder / `advance` | 1 |
| `StageScope` on funnel stages | 2 |
| Redo never regresses / never rejects | 1, 2, 4, 7 |
| `StageFailure`, `record_job_failure`, auto-resolve | 3 |
| `ResumeVersion.attempt` / `tailor_model` | 4 |
| `TailorOutcome`, failure surfacing, `fail_on_partial` | 5 |
| `repull_job` incl. dedup collision, browser degradation | 6 |
| `redo_jobs` stage-major, render target selection | 7 |
| `POST /api/redo`, boundary validation, typed result | 8 |
| Typed `jobDetails`, `/api/errors` pagination | 9 |
| `RedoDialog`, `use-redo-run` | 10 |
| Pipeline `Redo…` for any-status selections | 11 |
| Per-job `Redo…` | 12 |
| Grouped `AttentionCard`, formatted rows, Retry | 13 |
| Docs, full verification | 14 |

Every spec decision (1–15) maps to a task.

**Verified against the codebase.** Every symbol this plan names was checked:
`SearchConfig` has no `required_keywords` (the plan uses the real `yoe_max`
rejection path in `discovery/filter.py:32`), `create_app` takes `db_url` not a
path (`api/app.py:78`), `ReviewConfig.tailor_tier` exists and defaults to
`"premium"` (`tailor/review_config.py:32`), and `company_rename_collides`,
`compute_content_fingerprint`, `compute_dedup_key`, `resume_versions_for_job`,
and `application_for_job` all exist where the plan imports them.

**Two things left for the implementer to confirm in place**, each flagged inline
because they depend on code shape a reader must see rather than a name to look
up:
- Task 11 — the board filter → query-params mapping in `useBoardQuery`, so
  "select all matching" resolves the same rows the user sees.
- Task 13 — the existing stubbing approach in `AttentionCard.test.tsx`, which
  the new `renderAttentionCard` helper should follow.

**Type consistency check.** `StageFailure` (Task 3) is consumed unchanged by
Tasks 5, 6, 7. `StageOutcome` (Task 6) is consumed by Task 7 and mapped to
`StageOutcomeOut` in Task 8. `RedoStage` is defined once in `services/redo.py`
(Task 6) and imported by Tasks 8 and 9; the web mirror in `use-redo-run.ts`
(Task 10) is used by Tasks 11–13. `StageScope` (Task 2) is consumed by Task 7.
`TailorOutcome` (Task 5) is consumed by Task 7. Names match across all
references.
