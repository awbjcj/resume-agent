# Phase 1 — Loop Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the _best fact-lock-passing_ tailored round as the default resume, and never silently surface a gate-failing round — a purely read-side change that closes a latent fact-lock safety bug.

**Architecture:** A new pure selector `pick_best` ranks the already-persisted `ResumeVersion` rows; `best_resume_version` loads rows and applies it. The two read projections that surface "the resume" (`pipeline_rows`, `job_detail_row`) switch from `latest_resume_version` to the new selector and carry two new flags (`needs_attention`, `regressed`) out to the camelCase wire contract. The tailoring loop, the persistence path, and every row already written are untouched.

**Tech Stack:** Python 3, SQLModel/SQLAlchemy, Pydantic v2 (`CamelModel`), FastAPI + OpenAPI export, pytest, `uv`.

## Global Constraints

- **Observation-respecting:** zero behavior change to `src/resume_agent/tailor/`. All rounds still persist; the loop is untouched.
- **No schema migration:** `needs_attention` / `regressed` are computed read-side from existing columns (`ResumeVersion.fact_check_passed`, `review_score`, `round`, `id`). No new DB columns.
- Tests run **offline** with no API key/network (`.venv/Scripts/python.exe -m pytest`); the read side has no LLM calls.
- **Wire format is camelCase.** Pydantic schemas are the contract source of truth; DTO→schema is a `model_validate(row)` projection. After any schema change, regenerate `contracts/openapi.json` + `contracts/ts/api.ts` via `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the drift gate.
- The manual override `select_resume_version` (`services/board.py`) is unchanged — a user's explicit pick always wins.
- **Gating (do not start until both hold):** Phase 0 eval harness green in CI **and** a baseline `make eval` run recorded. This plan is verified against that baseline, not asserted.
- Branch: `feat/agent-quality-evals`. Commit after every task.

## Review corrections applied before implementation

- `review_score=None` ranks below score `0`; it is not coerced to zero for ranking.
- Regression compares the selected row with the actual latest row, not only their nullable ids.
- The eval harness must score the surfaced best clean round and report its round/attention state;
  judging `rounds[-1]` would not verify this phase.
- No paid baseline artifact exists locally. Explicit user authorization permits the capability
  implementation, but not an improvement/adoption claim.

---

### Task 1: `pick_best` selector + `best_resume_version`

**Files:**

- Modify: `src/resume_agent/tracking/repository.py` (add after `latest_rendered_resume_version`, ~line 175)
- Test: `tests/test_applications_repository.py` (append)

**Interfaces:**

- Consumes: `ResumeVersion` (`tracking/tables.py`); `resume_versions_for_job` (already in `repository.py`)
- Produces:
  - `BestResume` frozen dataclass: `version: ResumeVersion | None`, `no_clean_round: bool`, `regressed: bool`
  - `pick_best(versions: list[ResumeVersion]) -> BestResume` — pure; highest `review_score` among `fact_check_passed=True` rows, tie-broken by latest `round` then `id`; falls back to the latest row (by `round`, `id`) with `no_clean_round=True` when none pass the gate; `regressed=True` when the chosen gate-passing row is not the latest row overall
  - `best_resume_version(session: Session, job_id: int) -> BestResume` — loads rows via `resume_versions_for_job` and applies `pick_best`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_applications_repository.py  (append; reuse the existing _session helper)
from resume_agent.tracking.repository import best_resume_version, pick_best, save_resume_version
from resume_agent.tracking.tables import ResumeVersion


def _rv(round_num: int, score: int | None, passed: bool, version_id: int) -> ResumeVersion:
    return ResumeVersion(
        id=version_id, job_id=7, round=round_num,
        review_score=score, fact_check_passed=passed,
    )


def test_pick_best_prefers_highest_scoring_gate_passing_round():
    rows = [_rv(1, 90, True, 1), _rv(2, 82, True, 2)]
    best = pick_best(rows)
    assert best.version is not None and best.version.id == 1
    assert best.no_clean_round is False
    assert best.regressed is True  # best (round 1) is not the latest (round 2)


def test_pick_best_no_regression_when_best_is_latest():
    rows = [_rv(1, 80, True, 1), _rv(2, 90, True, 2)]
    best = pick_best(rows)
    assert best.version.id == 2 and best.regressed is False and best.no_clean_round is False


def test_pick_best_falls_back_to_latest_when_no_gate_passes():
    rows = [_rv(1, 70, False, 1), _rv(2, 60, False, 2)]
    best = pick_best(rows)
    assert best.version.id == 2  # latest round
    assert best.no_clean_round is True
    assert best.regressed is False  # no clean round to regress from


def test_pick_best_tie_breaks_on_latest_round_then_id():
    rows = [_rv(1, 88, True, 1), _rv(2, 88, True, 2)]
    assert pick_best(rows).version.id == 2


def test_pick_best_empty():
    best = pick_best([])
    assert best.version is None and best.no_clean_round is False and best.regressed is False


def test_best_resume_version_reads_rows():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, review_score=90, fact_check_passed=True))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, review_score=80, fact_check_passed=False))
        best = best_resume_version(s, 7)
        assert best.version is not None and best.version.round == 1
        assert best.no_clean_round is False and best.regressed is True
        assert best_resume_version(s, 999).version is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_applications_repository.py -v -k pick_best`
Expected: FAIL — `ImportError: cannot import name 'pick_best' from 'resume_agent.tracking.repository'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_agent/tracking/repository.py
# add near the top with the other imports:
from dataclasses import dataclass

# add immediately after latest_rendered_resume_version():


@dataclass(frozen=True)
class BestResume:
    """Read-side selection of the surfaced resume round (no schema change).

    ``version`` is the chosen row; ``no_clean_round`` is True when no round
    passed the fact-lock gate and a gate-failing latest round was surfaced as a
    fallback; ``regressed`` is True when the best gate-passing round is not the
    latest round (a later revision scored lower or broke the gate).
    """

    version: ResumeVersion | None
    no_clean_round: bool
    regressed: bool


def _latest_key(version: ResumeVersion) -> tuple[int, int]:
    return (version.round, version.id or 0)


def pick_best(versions: list[ResumeVersion]) -> BestResume:
    """Pick the best gate-passing round; never silently surface a gate-failing one."""
    if not versions:
        return BestResume(version=None, no_clean_round=False, regressed=False)
    latest = max(versions, key=_latest_key)
    gate_passing = [v for v in versions if v.fact_check_passed]
    if not gate_passing:
        return BestResume(version=latest, no_clean_round=True, regressed=False)
    best = max(
        gate_passing,
        key=lambda v: (-1 if v.review_score is None else v.review_score, v.round, v.id or 0),
    )
    return BestResume(
        version=best,
        no_clean_round=False,
        regressed=best is not latest,
    )


def best_resume_version(session: Session, job_id: int) -> BestResume:
    """Surface the best fact-lock-passing round for a job (falls back + flags)."""
    return pick_best(resume_versions_for_job(session, job_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_applications_repository.py -v -k "pick_best or best_resume_version"`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py tests/test_applications_repository.py
git commit -m "Adds best_resume_version read-side selector"
```

---

### Task 2: Surface best-round + flags on the pipeline board

**Files:**

- Modify: `src/resume_agent/tracking/queries.py` (`PipelineRow` dataclass ~line 113; `pipeline_rows` ~line 282; imports ~line 13)
- Test: `tests/test_tracking_queries.py` (append)

**Interfaces:**

- Consumes: `best_resume_version`, `BestResume` (Task 1)
- Produces: `PipelineRow` gains `needs_attention: bool = False` and `regressed: bool = False`; `pipeline_rows` sources `critique_json` from `best_resume_version(...).version` instead of `latest_resume_version`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_queries.py  (append)
from resume_agent.tracking.queries import pipeline_rows
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def test_pipeline_row_surfaces_best_gate_passing_round(session):
    job = save_job(session, Job(source="url", status=JobStatus.tailored.value))
    jid = job.id
    # round 2 regressed and broke the gate; round 1 is the clean best.
    save_resume_version(session, ResumeVersion(
        job_id=jid, round=1, review_score=90, fact_check_passed=True,
        critique_json=[{"reviewer": "ats-keyword", "score": 90, "passed": True}]))
    save_resume_version(session, ResumeVersion(
        job_id=jid, round=2, review_score=70, fact_check_passed=False,
        critique_json=[{"reviewer": "fact-check", "score": 0, "passed": False}]))
    row = next(r for r in pipeline_rows(session) if r.job_id == jid)
    assert row.critique_json == [{"reviewer": "ats-keyword", "score": 90, "passed": True}]
    assert row.regressed is True
    assert row.needs_attention is False


def test_pipeline_row_flags_no_clean_round(session):
    job = save_job(session, Job(source="url", status=JobStatus.tailored.value))
    save_resume_version(session, ResumeVersion(
        job_id=job.id, round=1, review_score=50, fact_check_passed=False, critique_json=[]))
    row = next(r for r in pipeline_rows(session) if r.job_id == job.id)
    assert row.needs_attention is True
```

(If `tests/test_tracking_queries.py` has no `session` fixture, add one mirroring `_session()` from `tests/test_applications_repository.py`: an in-memory `create_engine("sqlite://")` with `SQLModel.metadata.create_all`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v -k "best_gate_passing or no_clean_round"`
Expected: FAIL — `AttributeError: 'PipelineRow' object has no attribute 'regressed'`

- [ ] **Step 3: Write the implementation**

In `src/resume_agent/tracking/queries.py`, extend the import block (lines 13–20) to add `best_resume_version`:

```python
from resume_agent.tracking.repository import (
    application_for_job,
    best_resume_version,
    cover_letters_for_job,
    has_progress,
    latest_rendered_resume_version,
    latest_resume_version,
    resume_versions_for_job,
)
```

Add the two fields to `PipelineRow` (after `has_progress`, line 128):

```python
@dataclass
class PipelineRow:
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
    has_progress: bool = False
    needs_attention: bool = False
    regressed: bool = False
```

In `pipeline_rows` (lines 293–319), replace the `latest_resume_version` selection and thread the flags. `latest_rendered_resume_version` stays the PDF source (an older rendered PDF must not be hidden by a newer unrendered best round — see §7 of the spec, render default unchanged this phase):

```python
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        best = best_resume_version(session, job_id)
        version = best.version
        rendered = latest_rendered_resume_version(session, job_id)
        application = application_for_job(session, job_id)
        rows.append(
            PipelineRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                status=job.status,
                fit_score=job.fit_score,
                jd_text=clean_job_description_text(job.jd_text),
                critique_json=(version.critique_json or []) if version else None,
                pdf_path=rendered.pdf_path if rendered else None,
                application_status=application.status if application else None,
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                has_progress=has_progress(session, job_id),
                needs_attention=best.no_clean_round,
                regressed=best.regressed,
            )
        )
    return rows
```

`latest_resume_version` stays imported — it is still referenced by `job_detail_row` until Task 3 lands; leave the import in place.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v -k "best_gate_passing or no_clean_round"`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/queries.py tests/test_tracking_queries.py
git commit -m "Surfaces best gate-passing round on the pipeline board"
```

---

### Task 3: Carry best-round + flags into the job detail projection

**Files:**

- Modify: `src/resume_agent/tracking/queries.py` (`JobDetailRow` dataclass ~line 62; `job_detail_row` ~line 229)
- Test: `tests/test_tracking_queries.py` (append)

**Interfaces:**

- Consumes: `best_resume_version` (Task 1)
- Produces: `JobDetailRow` gains `best_resume_version_id: int | None = None`, `needs_attention: bool = False`, `regressed: bool = False`. `resume_versions` (all rows) is unchanged — the detail modal still shows every round; these fields tell the client which round is the default and whether the job needs attention.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_queries.py  (append)
from resume_agent.tracking.queries import job_detail_row


def test_job_detail_marks_best_version_and_attention(session):
    job = save_job(session, Job(source="url", status=JobStatus.tailored.value))
    v1 = save_resume_version(session, ResumeVersion(
        job_id=job.id, round=1, review_score=92, fact_check_passed=True, content_json={}))
    save_resume_version(session, ResumeVersion(
        job_id=job.id, round=2, review_score=70, fact_check_passed=False, content_json={}))
    row = job_detail_row(session, job.id)
    assert row is not None
    assert row.best_resume_version_id == v1.id
    assert row.regressed is True
    assert row.needs_attention is False
    assert len(row.resume_versions) == 2  # all rounds still returned


def test_job_detail_no_versions_has_no_best(session):
    job = save_job(session, Job(source="url", status=JobStatus.shortlisted.value))
    row = job_detail_row(session, job.id)
    assert row is not None
    assert row.best_resume_version_id is None
    assert row.needs_attention is False and row.regressed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v -k "best_version_and_attention or no_versions_has_no_best"`
Expected: FAIL — `AttributeError: 'JobDetailRow' object has no attribute 'best_resume_version_id'`

- [ ] **Step 3: Write the implementation**

Add three fields to `JobDetailRow` (after the `location_city` default, line 96), keeping them defaulted so field order with the existing non-default fields stays valid:

```python
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    best_resume_version_id: int | None = None
    needs_attention: bool = False
    regressed: bool = False
```

In `job_detail_row` (lines 243–279), compute the selection and pass the fields into the `JobDetailRow(...)` constructor (add these three keyword arguments alongside the existing ones):

```python
    facets = _shortlist_row(job, tokens, aliases)
    jid = _require_job_id(job)
    best = best_resume_version(session, jid)
    return JobDetailRow(
        id=jid,
        # ... all existing fields unchanged ...
        location_city=loc.get("city"),
        best_resume_version_id=best.version.id if best.version else None,
        needs_attention=best.no_clean_round,
        regressed=best.regressed,
    )
```

Note: `loc` is already computed inside `_shortlist_row`; in `job_detail_row` the location fields come from `facets`. Keep the existing assignments (`location_country=facets.location_country`, etc.) and only add the three new keyword arguments at the end of the constructor call.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v`
Expected: PASS (all queries tests, including the two new)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/queries.py tests/test_tracking_queries.py
git commit -m "Marks best resume version and attention on job detail"
```

---

### Task 4: Extend the wire contract + regenerate the typed client

**Files:**

- Modify: `src/resume_agent/api/schemas/jobs.py` (`PipelineItem` ~line 40; `JobDetail` ~line 107)
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`
- Test: `tests/api/test_openapi_contract.py` (drift gate — already exists)

**Interfaces:**

- Consumes: the `PipelineRow` / `JobDetailRow` fields added in Tasks 2–3
- Produces: camelCase wire fields `needsAttention`, `regressed` on the pipeline item; `bestResumeVersionId`, `needsAttention`, `regressed` on the job detail. Projection stays `model_validate(row)` (snake_case attr → camelCase alias via `CamelModel`).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_jobs_schema_flags.py  (new)
from resume_agent.api.schemas.jobs import JobDetail, PipelineItem


def test_pipeline_item_exposes_attention_flags_camelcase():
    item = PipelineItem.model_validate({
        "job_id": 1, "company": "Acme", "title": "Eng", "status": "tailored",
        "fit_score": 80, "jd_text": "x", "critique_json": [], "pdf_path": None,
        "application_status": None, "salary_min": None, "salary_max": None,
        "remote_policy": None, "seniority": None, "has_progress": True,
        "needs_attention": True, "regressed": False,
    })
    dumped = item.model_dump(by_alias=True)
    assert dumped["needsAttention"] is True
    assert dumped["regressed"] is False


def test_job_detail_exposes_best_version_camelcase():
    detail = JobDetail.model_validate({
        "id": 1, "source": "url", "url": None, "company": None, "title": None,
        "location": None, "jd_text": "x", "status": "tailored", "fit_score": None,
        "fit_rationale": None, "criteria_json": None, "posted_at": None,
        "archived_at": None, "created_at": "2026-06-30T00:00:00Z", "has_progress": True,
        "application": None, "resume_versions": [], "skills": [],
        "best_resume_version_id": 5, "needs_attention": False, "regressed": True,
    })
    dumped = detail.model_dump(by_alias=True)
    assert dumped["bestResumeVersionId"] == 5
    assert dumped["regressed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_jobs_schema_flags.py -v`
Expected: FAIL — `ValidationError`/missing fields (`needs_attention` not a field on `PipelineItem`)

- [ ] **Step 3: Add the schema fields**

In `src/resume_agent/api/schemas/jobs.py`, append to `PipelineItem` (after `has_progress`, line 54):

```python
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
    needs_attention: bool = False
    regressed: bool = False
```

Append to `JobDetail` (after `location_city`, line 140):

```python
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    best_resume_version_id: int | None = None
    needs_attention: bool = False
    regressed: bool = False
```

- [ ] **Step 4: Run the new schema test**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_jobs_schema_flags.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Regenerate the OpenAPI + TS contract and run the drift gate**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: drift gate PASS (regenerated `contracts/openapi.json` now matches the live schema; `contracts/ts/api.ts` gains the camelCase fields).

- [ ] **Step 6: Full offline suite + lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api/schemas/jobs.py contracts/openapi.json contracts/ts/api.ts tests/api/test_jobs_schema_flags.py
git commit -m "Exposes best-version and attention flags on the jobs API contract"
```

---

## Self-Review

**Spec coverage (`2026-06-30-phase1-loop-reliability-design.md`):**

- §3.1 `best_resume_version` (best gate-passing, tie-break latest round/id, fallback + "no clean round") — Task 1. ✓
- §3.1 "becomes the default surfaced by the projection (`queries.py:297`)" — Task 2 (`pipeline_rows`, the actual `latest_resume_version` caller) + Task 3 (`job_detail_row`). ✓
- §3.2 regression marker, detect + report only, read-side, no migration — `regressed` flag (Tasks 1–4); the loop is not changed. ✓
- §3.3 dropped items (early-exit / skip-passed) — correctly **not** implemented here. ✓
- §4 metric: "surfaced == best gate-passing; no `fact_check_passed=False` surfaced by default" — enforced by `pick_best` and tested in Tasks 1–3; the Phase 0 report's existing `regressed`/`convergence` reports the rate. ✓
- §7 open items: render default (`latest_rendered_resume_version`) **stays latest-rendered** (Task 2 comment); every surfacing site enumerated (grep confirmed only `pipeline_rows` + `job_detail_row` consume `latest_resume_version`). ✓

**Placeholder scan:** none — every code step shows the full edit.

**Type consistency:** `BestResume(version, no_clean_round, regressed)` flows Task 1 → `pipeline_rows` (`needs_attention=no_clean_round`, `regressed`) → `PipelineRow`/`PipelineItem`; `job_detail_row` maps to `best_resume_version_id`/`needs_attention`/`regressed` on `JobDetailRow`/`JobDetail`. camelCase aliases (`needsAttention`, `bestResumeVersionId`) are produced by `CamelModel`. ✓

## Notes for the implementer

- This phase has **no** LLM calls and touches **no** file under `src/resume_agent/tailor/`. If a step seems to need a loop change, stop — that is out of scope.
- Verify against the recorded Phase 0 baseline: after this lands, no eval case should surface a `fact_check_passed=False` resume as its default, and the report's regression rate is unchanged (Phase 1 _reports_, it does not _reduce_).
