# H-1B Company Cache, Quarterly Evidence, and Job-Detail Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the per-company H-1B cache the single display source for every job card, add a selectable per-quarter breakdown over the last four fiscal quarters, and split the job-detail tabs into `Tracking` (stage + application + delete) and `Sponsorship`.

**Architecture:** A company-level cache table (`h1b_company_evidence`) already exists and is already populated; the defect is that every read path goes through a _per-job frozen snapshot_ in `Job.analysis_meta_json`. This plan introduces one batched read seam (`h1b/cache.py::load_company_evidence`), points the job detail and all three board row projections at it, retires the snapshot, extends the evidence model with a per-period breakdown whose rollup is **derived server-side rather than trusted from the model**, widens discovery research to every surviving job's company under a per-run spend cap, and restructures the job-modal tabs.

**Tech Stack:** Python 3.13, FastAPI, SQLModel/SQLAlchemy, Pydantic v2, pytest · React 19, TypeScript, TanStack Query, Base UI, Tailwind, Vitest + Testing Library + msw

**Spec:** `docs/superpowers/specs/2026-08-03-h1b-company-cache-and-job-tabs-design.md`

---

## Global Constraints

- **Backend tests:** `.venv/Scripts/python.exe -m pytest` (offline — no API key, no network). All agent calls are faked.
- **Lint:** `ruff check` must pass before every commit.
- **Web tests:** run from the `web/` directory: `npx vitest run <path>`.
- **Contract regeneration:** after ANY change to `api/schemas/*`, run `bash scripts/gen_ts_client.sh` and commit `contracts/openapi.json` + `contracts/ts/api.ts` + the copied SPA schema `web/src/lib/api/schema.ts`. `tests/api/test_openapi_contract.py` is a drift gate and will fail if you skip this. If the Windows Bash wrapper fails before generation because of CRLF/`pipefail`, run the script's equivalent explicitly: `.venv/Scripts/python.exe scripts/export_openapi.py`, `npx --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts`, then `Copy-Item contracts/ts/api.ts web/src/lib/api/schema.ts -Force`.
- **Wire format is camelCase.** Python stays snake_case; `CamelModel` (`api/schemas/base.py`) sets `alias_generator=to_camel`. Never hand-write a camelCase Python field.
- **The caveat string is fixed.** `HISTORICAL_ONLY_CAVEAT` must appear verbatim in every `H1BSponsorshipEvidence`; the model validator rejects anything else. Copy it from `h1b/models.py`, never retype it.
- **Additive schema only.** `periods` and `denied_count` default to empty/`None` so every existing `evidence_json` payload still validates. There is **no database migration in this plan**.
- **Never auto-refresh.** No code path added here may trigger an LLM call as a side effect of _rendering_ or _reading_. Refresh happens only from the explicit manual check or a discovery run.
- **Baseline — the manual check is already a background run.** `POST /api/jobs/{job_id}/h1b-sponsorship` returns `202 RunOut` via the launch seam with `singleton_key=f"h1b-sponsorship:{job_id}"`; the panel derives checking/failed state from the run store via `latestArtifactRun(runs, "h1bSponsorship", "jobId", jobId)`, and evidence arrives only through the invalidated `["job"]` query. **Do not convert this back to a synchronous call.**
- **`normalize_company(value) -> str | None`** — it can return `None` _or_ an empty string. Always guard truthiness, never just `is not None`.

---

## Correctness Amendments (normative)

These rules resolve the plan/spec edge cases below. They override any earlier
illustrative snippet that conflicts with them.

1. **Four means four.** `periods` accepts at most four entries, not eight. The
   derived fields are the three counts only; a report-level `wage_summary` is
   not mathematically roll-upable. For legacy flat evidence, all three present
   counts must satisfy `certified_count + denied_count <= filing_count`.
2. **Only one cache read per rendered surface.** `services.board.list_board`
   reaches `project_shortlist_jobs`, `project_pipeline_jobs`, or
   `project_triage_jobs`, so every production projector must receive a map built
   from its materialized page. `job_detail_row` must not perform a second
   status-only read: the router performs the one full-evidence detail lookup.
3. **Freshness has two meanings.** `load_company_evidence` returns expired rows
   for display. Discovery must derive a separate `fresh_by_company` map
   (`expires_at > now`) for cap and scoring decisions; an expired row deferred
   by the cap is displayable but never scorer input.
4. **No-work is still useful work.** If all companies are fresh, skip the
   enricher call but build the silent-job scoring map from `fresh_by_company`.
   Never return `{}` before that mapping. Update `h1b_evidence_id` for every
   in-scope job with available evidence; return evidence only for `silent` jobs.
5. **The period UI is resilient to query refreshes.** Use `periods` (not
   `fiscalPeriods`) whenever periods exist, render stale status independently of
   the selector, omit the denied metric in the legacy flat fallback, and coerce
   a selected period that vanished after a refetch back to the rollup.
6. **Regeneration has three outputs.** `gen_ts_client.sh` also copies
   `contracts/ts/api.ts` to `web/src/lib/api/schema.ts`; commit and review that
   local generated copy with `contracts/openapi.json` and `contracts/ts/api.ts`.

---

## File Structure

**Created**

| Path                                        | Responsibility                                                                                                    |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `src/resume_agent/h1b/cache.py`             | The only batched read seam over `h1b_company_evidence`.                                                           |
| `tests/test_h1b_cache.py`                   | Batching, corruption tolerance, expiry passthrough.                                                               |
| `tests/test_h1b_enrichment_scope.py`        | Widened research set, narrow scoring map, per-run cap. `run_h1b_enrichment` currently has **zero** test coverage. |
| `web/src/features/job/TrackingTab.tsx`      | Composes stage + application + danger zone.                                                                       |
| `web/src/features/job/TrackingTab.test.tsx` | Tab composition and delete gating.                                                                                |

**Modified**

| Path                                           | Change                                                                                                         |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `src/resume_agent/h1b/models.py`               | `H1BPeriodStat`; `periods` + `denied_count` on evidence; derived rollup.                                       |
| `src/resume_agent/h1b/service.py`              | Quarter instructions; `schema_version = 2`; stop writing the snapshot.                                         |
| `src/resume_agent/api/schemas/jobs.py`         | `H1BPeriodStatOut`; `periods`/`deniedCount` on evidence out; `stale` on `H1BSponsorshipOut`.                   |
| `src/resume_agent/api/routers/jobs.py`         | `_job_detail_response` reads the cache; `_h1b_sponsorship_response` computes `stale`.                          |
| `src/resume_agent/tracking/queries.py`         | Three row projections take a batched evidence map; detail avoids a redundant status-only lookup.               |
| `src/resume_agent/services/board.py`           | Pass the DB session to the paginated shortlist projector so the production path can batch-load cache evidence. |
| `src/resume_agent/services/discovery.py`       | Widen research; keep scoring map narrow; apply cap; stop writing the snapshot.                                 |
| `src/resume_agent/config.py`                   | `h1b_enrich_max_companies_per_run`.                                                                            |
| `web/src/features/job/H1BSponsorshipPanel.tsx` | Period selector, stale label, shared-cache notice.                                                             |
| `web/src/features/job/StageManager.tsx`        | Delete moves out to the danger zone.                                                                           |
| `web/src/components/JobModal.tsx`              | Tab restructure.                                                                                               |
| `web/src/lib/api/schema.ts`                    | Generated SPA copy of the OpenAPI TypeScript contract.                                                         |
| `CLAUDE.md`                                    | Document the cache-is-truth invariant.                                                                         |

**Task dependency order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

---

### Task 1: Per-period evidence model with a derived rollup

**Files:**

- Modify: `src/resume_agent/h1b/models.py`
- Test: `tests/test_h1b_models.py` (create)

**Interfaces:**

- Consumes: nothing (first task).
- Produces: `H1BPeriodStat(period, filing_count, certified_count, denied_count, wage_summary)`; `H1BSponsorshipEvidence.periods: list[H1BPeriodStat]`; `H1BSponsorshipEvidence.denied_count: int | None`. Tasks 2–9 depend on these exact names.

**Why this matters:** the rollup is _derived, never trusted_. A model that returns `filing_count=999` alongside four quarters summing to 412 must not be able to put two contradicting numbers on screen. This is the same posture as `_project_domains` capping clustered domains rather than believing the model.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_h1b_models.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BPeriodStat,
    H1BSponsorshipEvidence,
)


def _evidence(**overrides) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    payload = {
        "status": "matched",
        "normalized_company": "acme",
        "retrieved_at": now,
        "expires_at": now + timedelta(days=30),
        "confidence": 0.8,
        "caveat": HISTORICAL_ONLY_CAVEAT,
    }
    payload.update(overrides)
    return H1BSponsorshipEvidence(**payload)


def test_rollup_overwrites_totals_that_disagree_with_their_parts():
    evidence = _evidence(
        filing_count=999,
        certified_count=999,
        denied_count=999,
        periods=[
            H1BPeriodStat(period="FY2026-Q1", filing_count=10, certified_count=9, denied_count=1),
            H1BPeriodStat(period="FY2025-Q4", filing_count=4, certified_count=3, denied_count=1),
        ],
    )
    assert evidence.filing_count == 14
    assert evidence.certified_count == 12
    assert evidence.denied_count == 2


def test_metric_no_period_reports_rolls_up_to_none_not_zero():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(period="FY2026-Q1", filing_count=10),
            H1BPeriodStat(period="FY2025-Q4", filing_count=4),
        ],
    )
    assert evidence.filing_count == 14
    assert evidence.certified_count is None
    assert evidence.denied_count is None


def test_partially_reported_metric_sums_only_present_values():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(period="FY2026-Q1", certified_count=9),
            H1BPeriodStat(period="FY2025-Q4"),
        ],
    )
    assert evidence.certified_count == 9


def test_duplicate_period_labels_reject():
    with pytest.raises(ValidationError):
        _evidence(
            periods=[
                H1BPeriodStat(period="FY2026-Q1", filing_count=1),
                H1BPeriodStat(period="FY2026-Q1", filing_count=2),
            ],
        )


def test_more_than_four_periods_reject():
    with pytest.raises(ValidationError):
        _evidence(
            periods=[H1BPeriodStat(period=f"FY-Q{i}", filing_count=1) for i in range(5)],
        )


def test_legacy_payload_without_periods_still_validates():
    evidence = _evidence(filing_count=12, certified_count=8)
    assert evidence.periods == []
    assert evidence.denied_count is None
    assert evidence.filing_count == 12


def test_period_rejects_outcomes_exceeding_filings():
    with pytest.raises(ValidationError):
        H1BPeriodStat(
            period="FY2026-Q1", filing_count=5, certified_count=4, denied_count=3
        )


def test_denied_count_cannot_exceed_filing_count_without_periods():
    with pytest.raises(ValidationError):
        _evidence(filing_count=2, denied_count=3)


def test_legacy_total_rejects_combined_outcomes_over_filings():
    with pytest.raises(ValidationError):
        _evidence(filing_count=2, certified_count=1, denied_count=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'H1BPeriodStat'`

- [ ] **Step 3: Add `H1BPeriodStat` above `H1BSponsorshipEvidence`**

In `src/resume_agent/h1b/models.py`, after the `H1BCompanyResolution` class:

```python
class H1BPeriodStat(BaseModel):
    """One fiscal quarter of historical filing figures for a company."""

    period: str = Field(min_length=1, max_length=32)
    filing_count: int | None = Field(default=None, ge=0)
    certified_count: int | None = Field(default=None, ge=0)
    denied_count: int | None = Field(default=None, ge=0)
    wage_summary: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_outcome_counts(self) -> H1BPeriodStat:
        if (
            self.filing_count is not None
            and self.certified_count is not None
            and self.denied_count is not None
            and self.certified_count + self.denied_count > self.filing_count
        ):
            raise ValueError(
                "certified_count + denied_count cannot exceed filing_count"
            )
        return self


def _rollup(periods: list[H1BPeriodStat], attribute: str) -> int | None:
    """Sum one metric across periods, yielding None when no period reports it."""
    present = [
        value
        for value in (getattr(period, attribute) for period in periods)
        if value is not None
    ]
    return sum(present) if present else None
```

- [ ] **Step 4: Add the two fields to `H1BSponsorshipEvidence`**

Add immediately after the existing `certified_count` line:

```python
    denied_count: int | None = Field(default=None, ge=0)
    periods: list[H1BPeriodStat] = Field(default_factory=list, max_length=4)
```

- [ ] **Step 5: Derive the rollup inside the existing contract validator**

Replace the body of `validate_historical_contract` with:

```python
    @model_validator(mode="after")
    def validate_historical_contract(self) -> H1BSponsorshipEvidence:
        if self.periods:
            labels = [period.period for period in self.periods]
            if len(set(labels)) != len(labels):
                raise ValueError("H1B evidence periods must have unique labels")
            # The rollup is derived, never trusted: a model cannot put a total on
            # screen that disagrees with the parts shown beneath it.
            self.filing_count = _rollup(self.periods, "filing_count")
            self.certified_count = _rollup(self.periods, "certified_count")
            self.denied_count = _rollup(self.periods, "denied_count")
        if self.expires_at <= self.retrieved_at:
            raise ValueError("H1B evidence must expire after retrieval")
        if self.caveat != HISTORICAL_ONLY_CAVEAT:
            raise ValueError("H1B evidence must use the application caveat")
        if self.certified_count is not None and self.filing_count is not None:
            if self.certified_count > self.filing_count:
                raise ValueError("certified_count cannot exceed filing_count")
        if self.denied_count is not None and self.filing_count is not None:
            if self.denied_count > self.filing_count:
                raise ValueError("denied_count cannot exceed filing_count")
        if (
            self.filing_count is not None
            and self.certified_count is not None
            and self.denied_count is not None
            and self.certified_count + self.denied_count > self.filing_count
        ):
            raise ValueError("certified_count + denied_count cannot exceed filing_count")
        return self
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_models.py -q`
Expected: PASS (9 passed)

- [ ] **Step 7: Verify nothing else regressed, then lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_service.py tests/test_h1b_mcp.py tests/test_h1b_config.py -q && ruff check`
Expected: PASS, no lint findings

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/h1b/models.py tests/test_h1b_models.py
git commit -m "feat: add per-quarter H-1B evidence with a derived rollup"
```

---

### Task 2: Batched company-cache read seam

**Files:**

- Create: `src/resume_agent/h1b/cache.py`
- Test: `tests/test_h1b_cache.py` (create)

**Interfaces:**

- Consumes: `H1BSponsorshipEvidence` (Task 1).
- Produces: `load_company_evidence(session: Session, companies: Sequence[str | None]) -> dict[str, H1BSponsorshipEvidence]`. Tasks 4, 5, and 8 all call this exact signature.

**Why this matters:** the board list renders hundreds of rows. A per-row cache lookup would reintroduce exactly the N+1 the board page was built to avoid. One query per request, map passed down — the same shape as `derive_filter_values`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_h1b_cache.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import event
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.h1b.cache import load_company_evidence
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.tracking.tables import H1BCompanyEvidence


def _evidence(company: str, *, expires_in_days: int = 30) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        display_company=company.title(),
        filing_count=3,
        retrieved_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


def _seed(session: Session, company: str, **kwargs) -> None:
    evidence = _evidence(company, **kwargs)
    session.add(
        H1BCompanyEvidence(
            normalized_company=company,
            display_company=evidence.display_company,
            status=evidence.status,
            evidence_json=evidence.model_dump(mode="json"),
            expires_at=evidence.expires_at,
            retrieved_at=evidence.retrieved_at,
        )
    )
    session.commit()


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_loads_many_companies_in_one_query():
    engine = _engine()
    with Session(engine) as session:
        for name in ("acme", "globex", "initech"):
            _seed(session, name)

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            loaded = load_company_evidence(
                session, ["Acme, Inc.", "Globex LLC", "Initech"]
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert set(loaded) == {"acme", "globex", "initech"}
    assert len(statements) == 1


def test_expired_rows_are_returned_not_filtered():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "acme", expires_in_days=-5)
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc."])
    assert loaded["acme"].status == "matched"


def test_schema_version_one_row_deserializes_with_empty_periods():
    engine = _engine()
    with Session(engine) as session:
        # `_seed` uses H1BCompanyEvidence.schema_version's persisted default: 1.
        _seed(session, "acme")
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc."])
    assert loaded["acme"].periods == []


def test_corrupt_row_is_skipped_not_raised():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "acme")
        session.add(
            H1BCompanyEvidence(
                normalized_company="globex",
                status="matched",
                evidence_json={"nonsense": True},
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.commit()
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc.", "Globex LLC"])
    assert set(loaded) == {"acme"}


def test_blank_companies_return_empty_without_querying():
    engine = _engine()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            assert load_company_evidence(session, [None, "", "   "]) == {}
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.h1b.cache'`

- [ ] **Step 3: Create the module**

Create `src/resume_agent/h1b/cache.py`:

```python
"""Batched read access to the durable per-company H-1B evidence cache."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from sqlmodel import Session, select

from resume_agent.h1b.models import H1BSponsorshipEvidence
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tracking.tables import H1BCompanyEvidence

logger = logging.getLogger(__name__)


def load_company_evidence(
    session: Session, companies: Sequence[str | None]
) -> dict[str, H1BSponsorshipEvidence]:
    """Load cached evidence for these company labels, keyed by normalized name.

    One query for the whole batch -- callers derive the map once per request and
    pass it down, never per row.

    Expired rows are returned like any other: expiry is a display concern (the
    caller labels them stale), not a filter. A row whose ``evidence_json`` no
    longer validates is skipped rather than raised, so a single corrupt cache
    row can never fail a whole board page.
    """
    keys = {
        key
        for key in (normalize_company(company) for company in companies if company)
        if key
    }
    if not keys:
        return {}
    column = cast(Any, H1BCompanyEvidence.normalized_company)
    rows = session.exec(
        select(H1BCompanyEvidence).where(column.in_(sorted(keys)))
    ).all()
    loaded: dict[str, H1BSponsorshipEvidence] = {}
    for row in rows:
        try:
            loaded[row.normalized_company] = H1BSponsorshipEvidence.model_validate(
                row.evidence_json
            )
        except ValueError:
            logger.warning(
                "Skipping corrupt H-1B cache row for normalized company %s",
                row.normalized_company,
            )
    return loaded
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_cache.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/h1b/cache.py tests/test_h1b_cache.py
git commit -m "feat: add batched H-1B company cache read seam"
```

---

### Task 3: Project periods, denied count, and staleness onto the wire

**Files:**

- Modify: `src/resume_agent/api/schemas/jobs.py:169-193`
- Modify: `src/resume_agent/api/routers/jobs.py:114-131`
- Test: `tests/api/test_job_h1b_detail.py` (create)

**Interfaces:**

- Consumes: `H1BSponsorshipEvidence.periods`, `.denied_count` (Task 1).
- Produces: `H1BPeriodStatOut`; `H1BSponsorshipEvidenceOut.periods`, `.denied_count`; `H1BSponsorshipOut.stale: bool`; `_h1b_sponsorship_response(evidence, *, now=None)`. Task 9 consumes the camelCase wire names `periods`, `deniedCount`, `stale`.

**Why this matters:** without this the browser cannot see the breakdown at all — the model would hold the data and the API would silently drop it.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_job_h1b_detail.py`:

```python
from datetime import datetime, timedelta, timezone

from resume_agent.api.routers.jobs import _h1b_sponsorship_response
from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BPeriodStat,
    H1BSponsorshipEvidence,
)


def _evidence(*, expires_in_days: int = 30, periods=None) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company="acme",
        display_company="Acme",
        retrieved_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        confidence=0.9,
        caveat=HISTORICAL_ONLY_CAVEAT,
        periods=periods or [],
    )


def test_periods_and_denied_count_reach_the_wire():
    evidence = _evidence(
        periods=[
            H1BPeriodStat(
                period="FY2026-Q1", filing_count=10, certified_count=9, denied_count=1
            )
        ]
    )
    out = _h1b_sponsorship_response(evidence)
    assert out.evidence is not None
    payload = out.model_dump(by_alias=True)
    assert payload["evidence"]["periods"][0]["period"] == "FY2026-Q1"
    assert payload["evidence"]["periods"][0]["deniedCount"] == 1
    assert payload["evidence"]["deniedCount"] == 1


def test_fresh_evidence_is_not_stale():
    assert _h1b_sponsorship_response(_evidence()).stale is False


def test_expired_evidence_is_stale():
    assert _h1b_sponsorship_response(_evidence(expires_in_days=-1)).stale is True


def test_stale_flips_exactly_at_expiry():
    evidence = _evidence(expires_in_days=1)
    assert _h1b_sponsorship_response(
        evidence, now=evidence.expires_at - timedelta(microseconds=1)
    ).stale is False
    assert _h1b_sponsorship_response(evidence, now=evidence.expires_at).stale is True


def test_missing_evidence_is_not_stale():
    out = _h1b_sponsorship_response(None)
    assert out.capability == "unavailable"
    assert out.stale is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_h1b_detail.py -q`
Expected: FAIL — `AttributeError: 'H1BSponsorshipOut' object has no attribute 'stale'`

- [ ] **Step 3: Add the out-schemas**

In `src/resume_agent/api/schemas/jobs.py`, insert before `H1BSponsorshipEvidenceOut`:

```python
class H1BPeriodStatOut(CamelModel):
    period: str
    filing_count: int | None = None
    certified_count: int | None = None
    denied_count: int | None = None
    wage_summary: dict[str, float] | None = None
```

Then add these two lines to `H1BSponsorshipEvidenceOut`, immediately after `certified_count`:

```python
    denied_count: int | None = None
    periods: list[H1BPeriodStatOut] = Field(default_factory=list)
```

And add this line to `H1BSponsorshipOut`, after `capability`:

```python
    stale: bool = False
```

- [ ] **Step 4: Compute `stale` in the response builder**

In `src/resume_agent/api/routers/jobs.py`, replace `_h1b_sponsorship_response` with:

```python
def _h1b_sponsorship_response(
    evidence: H1BSponsorshipEvidence | None,
    *,
    now: datetime | None = None,
) -> H1BSponsorshipOut:
    if evidence is None:
        return H1BSponsorshipOut(
            capability="unavailable",
            message=H1B_NO_EVIDENCE_MESSAGE,
        )
    # Expired evidence still renders -- historical filings do not rot. The server
    # owns "now" for every other TTL decision, so it owns this label too.
    stale = evidence.expires_at <= (now or datetime.now(timezone.utc))
    if evidence.status == "unavailable":
        return H1BSponsorshipOut(
            capability="unavailable",
            evidence=H1BSponsorshipEvidenceOut.from_evidence(evidence),
            message=evidence.unavailable_reason,
            stale=stale,
        )
    return H1BSponsorshipOut(
        capability="available",
        evidence=H1BSponsorshipEvidenceOut.from_evidence(evidence),
        stale=stale,
    )
```

Add to the imports at the top of the file if not already present:

```python
from datetime import datetime, timezone
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_h1b_detail.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Regenerate the TypeScript contract**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check
git add src/resume_agent/api/schemas/jobs.py src/resume_agent/api/routers/jobs.py \
        tests/api/test_job_h1b_detail.py contracts/openapi.json contracts/ts/api.ts \
        web/src/lib/api/schema.ts
git commit -m "feat: expose H-1B periods, denied count, and staleness on the API"
```

---

### Task 4: Job detail reads the company cache

**Files:**

- Modify: `src/resume_agent/api/routers/jobs.py:94-106`
- Test: `tests/api/test_job_h1b_detail.py` (extend)

**Interfaces:**

- Consumes: `load_company_evidence` (Task 2), `_h1b_sponsorship_response` (Task 3).
- Produces: no new symbols. Behaviour: `GET /api/jobs/{id}` reports evidence for any job whose _company_ is cached, regardless of whether that job was ever researched.

**Why this matters:** this is the defect the user reported. Job B at Stripe currently reads "not checked" while a fresh answer for Stripe sits one query away.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_job_h1b_detail.py`. This reuses the app-construction
pattern from `tests/api/test_job_mutations.py` — `create_app` takes `db_url`,
never an engine, and H-1B must be enabled through a temp `env_path` file:

```python
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import H1BCompanyEvidence, Job


def _h1b_app(tmp_path):
    env = tmp_path / "h1b.env"
    env.write_text(
        "H1B_MCP_ENABLED=true\nH1B_MCP_TRANSPORT=stdio\nH1B_MCP_COMMAND=server\n",
        encoding="utf-8",
    )
    return create_app(db_url="sqlite://", env_path=env, runs_root=tmp_path)


def test_job_detail_reads_evidence_cached_by_a_sibling_job(tmp_path):
    """A job never researched itself still shows its company's cached answer."""
    app = _h1b_app(tmp_path)
    evidence = _evidence(
        periods=[H1BPeriodStat(period="FY2026-Q1", filing_count=7, certified_count=6)]
    )

    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            # Two jobs at the same company; neither carries a per-job snapshot.
            first = Job(source="manual", company="Acme, Inc.", title="A", jd_text="x")
            second = Job(source="manual", company="Acme LLC", title="B", jd_text="y")
            session.add(first)
            session.add(second)
            session.add(
                H1BCompanyEvidence(
                    normalized_company="acme",
                    display_company="Acme",
                    status="matched",
                    evidence_json=evidence.model_dump(mode="json"),
                    expires_at=evidence.expires_at,
                    retrieved_at=evidence.retrieved_at,
                )
            )
            session.commit()
            job_ids = [first.id, second.id]

        for job_id in job_ids:
            body = client.get(f"/api/jobs/{job_id}").json()
            assert body["h1BSponsorship"]["capability"] == "available"
            assert body["h1BSponsorship"]["evidence"]["filingCount"] == 7
            assert body["h1BSponsorship"]["evidence"]["periods"][0]["period"] == "FY2026-Q1"
```

> Both jobs must resolve to the **same** normalized company: `normalize_company`
> maps `"Acme, Inc."` and `"Acme LLC"` alike to `"acme"`. That equivalence is the
> whole point of the test — do not "fix" the fixture by giving them identical
> labels.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_h1b_detail.py -q`
Expected: FAIL — `capability` is `"unavailable"` because no per-job snapshot exists

- [ ] **Step 3: Point the detail response at the cache**

In `src/resume_agent/api/routers/jobs.py::_job_detail_response`, replace the `else:` branch:

```python
    else:
        job = get_job(session, job_id)
        evidence = None
        if job is not None:
            key = normalize_company(job.company)
            if key:
                evidence = load_company_evidence(session, [job.company]).get(key)
        detail.h1b_sponsorship = _h1b_sponsorship_response(evidence)
```

Add the import:

```python
from resume_agent.h1b.cache import load_company_evidence
```

- [ ] **Step 4: Remove the now-orphaned snapshot import**

`read_job_analysis_meta` and `H1BSponsorshipEvidence` may now be unused in this module. Run `ruff check` — it will name any import your change orphaned. Remove **only** those, and only if nothing else in the file uses them.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_h1b_detail.py tests/api/test_job_mutations.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/api/routers/jobs.py tests/api/test_job_h1b_detail.py
git commit -m "fix: read H-1B evidence from the company cache on job detail"
```

---

### Task 5: Board row projections read the cache, batched

**Files:**

- Modify: `src/resume_agent/tracking/queries.py:152-163, 191-227, 230-255, 258-275, 278-290, 318-393, 415-465`
- Modify: `src/resume_agent/services/board.py:107-114`
- Test: `tests/test_board_h1b_status.py` (create)

**Interfaces:**

- Consumes: `load_company_evidence` (Task 2).
- Produces: `_h1b_sponsorship_status(job, evidence_by_company)`; `_shortlist_row(job, tokens, aliases, evidence_by_company)`; `_triage_row(job, progressed, evidence_by_company)`. The public row APIs keep their existing signatures. The internal paginated shortlist projector changes to `project_shortlist_jobs(session, jobs, ...)`, because `services.board.list_board` is the real production caller and must load one map for its page.

**Why this matters:** three call sites read the snapshot. If the detail card and the list badge disagree, that is a bug users will report. The map must be built **once per call**, not per row.

- [ ] **Step 1: Write the failing test**

Create `tests/test_board_h1b_status.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import event
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.services.board import list_board
from resume_agent.tracking.tables import H1BCompanyEvidence, Job, JobStatus


def _seed_evidence(session: Session, company: str) -> None:
    now = datetime.now(timezone.utc)
    evidence = H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        retrieved_at=now,
        expires_at=now + timedelta(days=30),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )
    session.add(
        H1BCompanyEvidence(
            normalized_company=company,
            status="matched",
            evidence_json=evidence.model_dump(mode="json"),
            expires_at=evidence.expires_at,
            retrieved_at=evidence.retrieved_at,
        )
    )


def test_production_shortlist_page_resolves_h1b_status_in_one_query():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for index in range(6):
            session.add(
                Job(
                    source="manual",
                    company="Acme, Inc." if index % 2 == 0 else "Globex LLC",
                    title=f"Role {index}",
                    jd_text="x",
                    status=JobStatus.shortlisted.value,
                )
            )
        _seed_evidence(session, "acme")
        _seed_evidence(session, "globex")
        session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            rows = list_board(
                session, "shortlist", with_facets=False
            ).page.data
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(rows) == 6
    assert all(row.h1b_sponsorship_status == "matched" for row in rows)
    assert len(statements) == 1, "board rows must not issue one H-1B query per row"
```

Add equivalent focused cases for the `pipeline` and `triage` values of
`list_board` (using jobs in each board's selectable statuses). The cache-query
assertion applies to each case. Calling `shortlist_rows()` alone is insufficient:
the API board route calls `services.board.list_board()` and previously bypassed
the plan's proposed shortlist map.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_h1b_status.py -q`
Expected: FAIL — every `h1b_sponsorship_status` is `None` (no per-job snapshots exist)

- [ ] **Step 3: Rewrite the status helper to read the map**

In `src/resume_agent/tracking/queries.py`, replace `_h1b_sponsorship_status` entirely:

```python
def _h1b_sponsorship_status(
    job: Job, evidence_by_company: Mapping[str, H1BSponsorshipEvidence]
) -> str | None:
    """Return the company's cached H-1B status, or None when uncached."""
    key = normalize_company(job.company)
    if not key:
        return None
    evidence = evidence_by_company.get(key)
    return evidence.status if evidence is not None else None
```

Add imports at the top of the file:

```python
from collections.abc import Mapping

from resume_agent.h1b.cache import load_company_evidence
from resume_agent.taxonomy.industries import normalize_company
```

(`H1BSponsorshipEvidence` is already imported at line 11. If `normalize_company` is already imported, do not duplicate it.)

- [ ] **Step 4: Thread one map through the actual page projectors**

Change `_shortlist_row` and `_triage_row` to accept
`Mapping[str, H1BSponsorshipEvidence]`, and pass that map to
`_h1b_sponsorship_status`. Add one small private helper so the three projectors
cannot drift into subtly different cache behavior:

```python
def _company_evidence(
    session: Session, jobs: Sequence[Job]
) -> Mapping[str, H1BSponsorshipEvidence]:
    return load_company_evidence(session, [job.company for job in jobs])
```

Use it exactly once in each materialized-page projector:

```python
def project_shortlist_jobs(
    session: Session,
    jobs: Sequence[Job],
    *,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> list[ShortlistRow]:
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    evidence_by_company = _company_evidence(session, jobs)
    return [
        _shortlist_row(job, tokens, aliases, evidence_by_company) for job in jobs
    ]
```

Do the same before the row loops in `project_pipeline_jobs` and
`project_triage_jobs`. `archived_rows` already uses `project_triage_jobs`, so it
inherits the same batched behavior without a fourth implementation.

- [ ] **Step 5: Update every caller, without adding a duplicate detail read**

- `shortlist_rows` calls `project_shortlist_jobs(session, jobs, ...)`.
- `services/board.py::list_board` calls
  `project_shortlist_jobs(session, jobs, facts=facts)`. This is the missing
  production path; without it the paginated shortlist API either fails the new
  signature or keeps reading no cache evidence.
- `job_facets` builds `_company_evidence(session, [job])` once before calling
  `_shortlist_row`.
- `job_detail_row` passes an empty map to `_shortlist_row`. Its inherited
  `h1b_sponsorship_status` is not part of `JobDetail`; the router's Task 4
  full-evidence lookup is authoritative and must remain the only cache query for
  a job-detail request.
- `pipeline_rows`, `triage_rows`, and `archived_rows` keep their public
  signatures and delegate to their updated projectors.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_h1b_status.py -q`
Expected: PASS (3 passed — shortlist, pipeline, and triage production pages)

- [ ] **Step 7: Run the surrounding suites**

Run: `.venv/Scripts/python.exe -m pytest tests/tracking/test_board_query.py tests/api -q`
Expected: PASS. The board query test lives under `tests/tracking/`; do not hide a
bad path behind a broad `-k` fallback.

- [ ] **Step 8: Lint and commit**

```bash
ruff check
git add src/resume_agent/tracking/queries.py src/resume_agent/services/board.py \
        tests/test_board_h1b_status.py
git commit -m "fix: resolve board H-1B status from the batched company cache"
```

---

### Task 6: Retire the per-job evidence snapshot

**Files:**

- Modify: `src/resume_agent/h1b/service.py:431-442`
- Modify: `src/resume_agent/services/discovery.py:143-151`
- Test: `tests/test_h1b_service.py` (extend)
- Test: `tests/test_h1b_enrichment_scope.py` (assert the discovery path too; created in Task 8)

**Interfaces:**

- Consumes: nothing new.
- Produces: no new symbols. Behaviour: `JobAnalysisMeta.h1b_evidence_snapshot` is never written; `h1b_evidence_id` still is.

**Why this matters:** with Tasks 4 and 5 done, the snapshot has no readers. Continuing to write it duplicates the cache into every job row and lets the two drift. The **field stays on the model** so existing rows still deserialize — do not delete it from `JobAnalysisMeta`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_h1b_service.py`:

```python
def test_manual_check_records_the_cache_pointer_but_no_snapshot():
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    @asynccontextmanager
    async def fake_tools(_settings, **_kwargs):
        yield object()

    with Session(engine) as session:
        job = Job(source="manual", company="Acme, Inc.", title="Engineer", jd_text="x")
        session.add(job)
        session.commit()
        session.refresh(job)

        import resume_agent.h1b.service as service

        original = service.h1b_tools
        service.h1b_tools = fake_tools
        try:
            asyncio.run(
                check_job_sponsorship(
                    session,
                    job,
                    settings=settings,
                    agent_factory=Factory(FakeRunner()),
                )
            )
        finally:
            service.h1b_tools = original

        meta = job.analysis_meta_json or {}
        assert meta.get("h1b_evidence_id") is not None
        assert meta.get("h1b_evidence_snapshot") is None
```

> **Note for the implementer:** `FakeRunner` returns evidence for company `"acme"`, which is what `normalize_company("Acme, Inc.")` produces — that match is required or `_agent_output` raises.

The manual-path test is not sufficient by itself: Task 8 must also assert that
the widened discovery path leaves `h1b_evidence_snapshot` absent for both a
`silent` and a non-`silent` job while retaining the appropriate provenance
pointer. This prevents the later loop rewrite from quietly reintroducing the
retired payload.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_service.py -q -k snapshot`
Expected: FAIL — `h1b_evidence_snapshot` is a dict, not `None`

- [ ] **Step 3: Stop writing the snapshot in the manual path**

In `src/resume_agent/h1b/service.py::check_job_sponsorship`, delete this line
and update its docstring from “attach its snapshot” to “record cache
provenance”:

```python
    meta.h1b_evidence_snapshot = evidence.model_dump(mode="json")
```

Leave `meta.h1b_evidence_id = row.id if row is not None else None` in place.

- [ ] **Step 4: Stop writing the snapshot in the discovery path**

In `src/resume_agent/services/discovery.py::run_h1b_enrichment`, delete the identical line:

```python
        meta.h1b_evidence_snapshot = evidence.model_dump(mode="json")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_service.py tests/api -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/h1b/service.py src/resume_agent/services/discovery.py tests/test_h1b_service.py
git commit -m "refactor: stop writing the per-job H-1B evidence snapshot"
```

---

### Task 7: Research the last four quarters

**Files:**

- Modify: `src/resume_agent/h1b/service.py:103-140` (agent instructions), `:374-388` (persistence)
- Test: `tests/test_h1b_service.py` (extend)

**Interfaces:**

- Consumes: `H1BPeriodStat` (Task 1).
- Produces: cache rows written with `schema_version = 2`.

**Why this matters:** the MCP command is unset in this workspace, so the provider's exact tool signatures are unverified. The instruction asks for quarters; if the provider cannot slice by quarter the agent returns `periods: []`, the evidence is still **valid**, and the UI falls back to the flat view. This must never become an error path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_h1b_service.py`:

```python
def test_sponsorship_agent_is_instructed_to_collect_four_quarters():
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )
    from resume_agent.h1b.service import DefaultSponsorshipAgentFactory

    runner = DefaultSponsorshipAgentFactory(settings).build(tools=None)
    # AgentRunner intentionally narrows the public runner API; tests in this
    # repository inspect its wrapped agent for prompt-contract assertions.
    instructions = " ".join(runner._agent.instructions)
    assert "get_available_data" in instructions
    assert "four most recent" in instructions
    assert "periods" in instructions
    assert runner.run_meta is not None
    assert runner.run_meta.prompt_policy_version == "h1b-sponsorship-research-v2"


def test_persisted_rows_are_written_at_schema_version_two():
    from resume_agent.tracking.tables import H1BCompanyEvidence
    from sqlmodel import select as model_select

    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    @asynccontextmanager
    async def fake_tools(_settings, **_kwargs):
        yield object()

    import resume_agent.h1b.service as service

    original = service.h1b_tools
    service.h1b_tools = fake_tools
    try:
        asyncio.run(
            enrich_companies(
                engine,
                ["Acme, Inc."],
                settings=settings,
                agent_factory=Factory(FakeRunner()),
            )
        )
    finally:
        service.h1b_tools = original

    with Session(engine) as session:
        row = session.exec(
            model_select(H1BCompanyEvidence).where(
                H1BCompanyEvidence.normalized_company == "acme"
            )
        ).first()
    assert row is not None
    assert row.schema_version == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_service.py -q -k "four_quarters or schema_version"`
Expected: FAIL — instruction text absent; `schema_version` is `1`

- [ ] **Step 3: Add the quarter instructions**

In `DefaultSponsorshipAgentFactory.build`, add these three strings to the `with_guidance(...)` list, after the existing "Return one validated evidence object…" line:

```python
                    "When get_available_data is exposed, use it to identify the four most recent fiscal quarters.",
                    "Fill periods with one entry per quarter, newest first, using that quarter's own filing_count, certified_count, denied_count, and wage_summary.",
                    "If the source cannot break figures down by quarter, return periods as an empty list rather than guessing or repeating the total.",
```

The tool surface is intentionally unverified. “When ... is exposed” preserves
the `periods: []` degradation path instead of turning a missing optional tool
into an agent failure.

- [ ] **Step 3b: Version the changed prompt policy**

In the returned `AgentRunMeta`, change
`prompt_policy_version="h1b-sponsorship-research-v1"` to
`"h1b-sponsorship-research-v2"`. Prompt-policy metadata must change with a
behavioural prompt contract, not merely with its output schema.

- [ ] **Step 4: Write the schema version on persist**

In `enrich_companies`, inside the persistence loop, add alongside the other `row.*` assignments:

```python
            row.schema_version = 2
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_service.py -q`
Expected: PASS

- [ ] **Step 6: Check the prompt-contract gate**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_prompt_contracts.py -q`
Expected: PASS. If it fails because the prompt registry snapshots agent instructions, update the expected snapshot to include the three new lines — do not weaken the assertion.

- [ ] **Step 7: Lint and commit**

```bash
ruff check
git add src/resume_agent/h1b/service.py tests/test_h1b_service.py
git commit -m "feat: research the four most recent H-1B fiscal quarters"
```

---

### Task 8: Widen discovery research under a per-run cap

**Files:**

- Modify: `src/resume_agent/config.py:78`
- Modify: `src/resume_agent/services/discovery.py:94-158`
- Test: `tests/test_h1b_enrichment_scope.py` (create)

**Interfaces:**

- Consumes: `load_company_evidence` (Task 2).
- Produces: `Settings.h1b_enrich_max_companies_per_run: int`. **`run_h1b_enrichment` keeps its exact current signature and return type** — `dict[int, H1BSponsorshipEvidence]`. `discovery/pipeline.py` needs no change.

**Why this matters:** two separable behaviours are being kept separate on purpose. Research widens so every card gets an answer; the **returned map stays narrow** so a job whose JD explicitly refuses sponsorship does not get its fit score lifted by the employer's filing history. Conflating them would silently change scoring.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_h1b_enrichment_scope.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BEnrichmentReport,
    H1BSponsorshipEvidence,
)
from resume_agent.services.discovery import run_h1b_enrichment
from resume_agent.tracking.tables import Job, JobStatus


def _evidence(company: str) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        retrieved_at=now,
        expires_at=now + timedelta(days=30),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


class RecordingEnricher:
    """Captures which company labels were handed to the researcher."""

    def __init__(self):
        self.seen: list[str] = []

    async def enrich(self, engine, companies: list[str]) -> H1BEnrichmentReport:
        self.seen.extend(companies)
        from resume_agent.taxonomy.industries import normalize_company

        return H1BEnrichmentReport(
            by_company={
                normalize_company(c): _evidence(normalize_company(c) or "")
                for c in companies
            }
        )


def _add(session: Session, company: str, signal: str) -> Job:
    job = Job(
        source="manual",
        company=company,
        title=f"Role at {company}",
        jd_text="x",
        status=JobStatus.filtered.value,
        criteria_json={"sponsorship_signal": signal},
    )
    session.add(job)
    return job


def test_research_widens_beyond_silent_jobs():
    engine = make_engine("sqlite://")
    init_db(engine)
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()
    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "explicit_no")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)
    assert {c.lower() for c in enricher.seen} == {"acme, inc.", "globex llc"}


def test_returned_scoring_map_stays_silent_only():
    engine = make_engine("sqlite://")
    init_db(engine)
    config = SearchConfig(sponsorship_required=True)
    with Session(engine) as session:
        silent = _add(session, "Acme, Inc.", "silent")
        loud = _add(session, "Globex LLC", "explicit_no")
        session.commit()
        session.refresh(silent)
        session.refresh(loud)
        silent_id, loud_id = silent.id, loud.id
        result = run_h1b_enrichment(session, config, enricher=RecordingEnricher())
    assert silent_id in result
    assert loud_id not in result


def test_nothing_is_researched_when_sponsorship_is_not_required():
    engine = make_engine("sqlite://")
    init_db(engine)
    enricher = RecordingEnricher()
    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        session.commit()
        run_h1b_enrichment(
            session, SearchConfig(sponsorship_required=False), enricher=enricher
        )
    assert enricher.seen == []


def test_fresh_cache_hits_still_reach_the_scorer():
    """A company already cached is not re-researched but must still score."""
    engine = make_engine("sqlite://")
    init_db(engine)
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    now = datetime.now(timezone.utc)
    acme_evidence = _evidence("acme")
    globex_evidence = _evidence("globex")
    with Session(engine) as session:
        from resume_agent.tracking.tables import H1BCompanyEvidence

        silent = _add(session, "Acme, Inc.", "silent")
        explicit_no = _add(session, "Globex LLC", "explicit_no")
        for company, evidence in (
            ("acme", acme_evidence),
            ("globex", globex_evidence),
        ):
            session.add(
                H1BCompanyEvidence(
                    normalized_company=company,
                    status="matched",
                    evidence_json=evidence.model_dump(mode="json"),
                    expires_at=now + timedelta(days=30),
                    retrieved_at=now,
                )
            )
        session.commit()
        session.refresh(silent)
        session.refresh(explicit_no)
        silent_id, explicit_no_id = silent.id, explicit_no.id
        result = run_h1b_enrichment(session, config, enricher=enricher)
        for job in (silent, explicit_no):
            meta = job.analysis_meta_json or {}
            assert meta.get("h1b_evidence_id") is not None
            assert meta.get("h1b_evidence_snapshot") is None

    assert enricher.seen == [], "a fresh cache hit must not be re-researched"
    assert silent_id in result, "a fresh cache hit must still reach the fit scorer"
    assert explicit_no_id not in result, "an explicit-no JD must not reach the scorer"


def test_per_run_cap_takes_the_companies_with_the_most_jobs(monkeypatch):
    engine = make_engine("sqlite://")
    init_db(engine)
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    monkeypatch.setattr(
        "resume_agent.services.discovery.get_settings",
        lambda: Settings(  # type: ignore[call-arg]
            _env_file=None, h1b_enrich_max_companies_per_run=1
        ),
    )

    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "silent")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)

    assert len(enricher.seen) == 1
    assert "acme" in enricher.seen[0].lower()
```

Add these cap-edge regressions in the same file:

- With equally frequent normalizable companies and a cap of one, assert the
  alphabetically earlier normalized key is selected. This pins the documented
  tie-break rather than only the “most jobs” half of the sort.
- Seed an **expired** cache row for a silent job and a higher-leverage uncached
  company, then cap the run at one. Assert the stale job remains out of the
  returned scorer map when its refresh is deferred; it may still render as stale
  through the display read seam.
- Set `h1b_enrich_max_companies_per_run=0` and assert every uncached company is
  handed to the enricher. This pins the repository convention that zero means
  unlimited.

> **Note for the implementer:** `SearchConfig` lives in `src/resume_agent/discovery/search_config.py`. If it requires more constructor arguments than `sponsorship_required`, supply the minimum the dataclass demands.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_enrichment_scope.py -q`
Expected: FAIL — only the `silent` company is researched

- [ ] **Step 3: Add the setting**

In `src/resume_agent/config.py`, after `h1b_cache_ttl_days`:

```python
    h1b_enrich_max_companies_per_run: int = Field(default=50, ge=0)
```

- [ ] **Step 4: Build the widened research set; keep score eligibility at return time**

Replace the eligibility block at the top of `run_h1b_enrichment` (the `eligible` / `companies` loop) with:

```python
    if not config.sponsorship_required:
        if reporter:
            reporter.begin(0, "Checking historical sponsorship", phase_index=3, phase_count=4)
            reporter.step(0)
        return {}

    # Research every surviving job's company so each card gets an answer.
    research_jobs: list[Job] = []
    job_counts: dict[str, int] = {}
    companies: dict[str, str] = {}
    for job in jobs:
        normalized = normalize_company(job.company)
        if not normalized:
            continue
        research_jobs.append(job)
        job_counts[normalized] = job_counts.get(normalized, 0) + 1
        companies.setdefault(normalized, job.company or normalized)

    if reporter:
        reporter.begin(
            len(research_jobs),
            "Checking historical sponsorship",
            phase_index=3,
            phase_count=4,
        )
    if not research_jobs or enricher is None:
        if reporter:
            reporter.step(len(research_jobs))
        return {}
```

- [ ] **Step 5: Separate displayable cache rows from fresh scoring rows, then apply the cap**

Immediately before the `enricher.enrich(...)` call, load the durable rows once
but split the maps by freshness. Do **not** return early when `uncached` is empty:
that branch is how a fully fresh cache reaches the scorer.

```python
    now = datetime.now(timezone.utc)
    cached_for_display = load_company_evidence(session, list(companies.values()))
    fresh_by_company = {
        key: evidence
        for key, evidence in cached_for_display.items()
        if evidence.expires_at > now
    }
    # Expired rows still render on cards, but refreshing them costs a call and
    # they must never silently become scorer input if the cap defers them.
    uncached = sorted(
        (key for key in companies if key not in fresh_by_company),
        key=lambda key: (-job_counts[key], key),
    )
    cap = get_settings().h1b_enrich_max_companies_per_run
    selected = uncached if cap == 0 else uncached[:cap]

    report = H1BEnrichmentReport(by_company={})
    if selected:
        outcome = enricher.enrich(
            session.get_bind(), [companies[key] for key in selected]
        )
        if inspect.isawaitable(outcome):
            outcome = asyncio.run(outcome)
        report = H1BEnrichmentReport.model_validate(outcome)
```

Add these imports to `services/discovery.py` if absent:

```python
from datetime import datetime, timezone

from resume_agent.h1b.cache import load_company_evidence
```

- [ ] **Step 6: Update provenance broadly but keep the returned scorer map narrow**

Fresh rows were not sent to the enricher, so merge only **fresh** cache hits
with the newly researched report. Query cache row IDs in one batch; do not put a
per-job lookup inside this loop.

```python
    available: dict[str, H1BSponsorshipEvidence] = {
        **fresh_by_company,
        **report.by_company,
    }
    cache_rows = session.exec(
        model_select(H1BCompanyEvidence).where(
            H1BCompanyEvidence.normalized_company.in_(list(available))
        )
    ).all()
    evidence_ids = {row.normalized_company: row.id for row in cache_rows}

    evidence_by_job: dict[int, H1BSponsorshipEvidence] = {}
    for job in research_jobs:
        normalized = normalize_company(job.company)
        evidence = available.get(normalized) if normalized else None
        if evidence is None:
            continue
        meta = read_job_analysis_meta(job.analysis_meta_json) or JobAnalysisMeta()
        meta.h1b_evidence_id = evidence_ids.get(normalized)
        # `h1b_evidence_snapshot` is retired: do not write it here.
        job.analysis_meta_json = meta.model_dump(mode="json")
        session.add(job)
        if (
            job.id is not None
            and (job.criteria_json or {}).get("sponsorship_signal") == "silent"
        ):
            evidence_by_job[job.id] = evidence
```

This deliberately leaves capped-out, expired rows out of `available`: they can
render as stale, but cannot raise a fit score until a later run refreshes them.
Change the final `reporter.step(len(eligible))` to
`reporter.step(len(research_jobs))`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_h1b_enrichment_scope.py -q`
Expected: PASS (8 passed, including fresh-only, stale-deferred, tie-break, and
zero-is-unlimited cases)

- [ ] **Step 8: Verify the pipeline still wires up unchanged**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_discovery.py tests/test_discovery_ingest.py -q`
Expected: PASS — `discovery/pipeline.py` was not modified

- [ ] **Step 9: Lint and commit**

```bash
ruff check
git add src/resume_agent/config.py src/resume_agent/services/discovery.py tests/test_h1b_enrichment_scope.py
git commit -m "feat: widen H-1B research to every surviving company under a run cap"
```

---

### Task 9: Period selector and stale label in the sponsorship panel

**Files:**

- Modify: `web/src/features/job/H1BSponsorshipPanel.tsx`
- Test: `web/src/features/job/H1BSponsorshipPanel.test.tsx`

**Interfaces:**

- Consumes: wire fields `periods`, `deniedCount`, `stale` (Task 3).
- Produces: no exported symbols beyond the existing `H1BSponsorshipPanel`.

**Why this matters:** two traps. **(a)** Changing the period must not change the status banner — status is a property of the company research, not of a quarter; a quarter with zero filings shows `0`, which is a fact, not a `no_match`. **(b)** A bare `<SelectValue />` in this codebase renders the raw value (`"FY2026-Q1"`) until the dropdown has been opened once. Base UI's `Select.Value` accepts a **function child** that receives the current value — use it.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/job/H1BSponsorshipPanel.test.tsx`. Keep the existing
`matchedEvidence` as the legacy flat fixture, then add a quarterly fixture with
the new fields:

```tsx
const quarterlyEvidence = {
  ...matchedEvidence,
  filingCount: 14,
  certifiedCount: 12,
  deniedCount: 2,
  periods: [
    {
      period: "FY2026-Q1",
      filingCount: 10,
      certifiedCount: 9,
      deniedCount: 1,
      wageSummary: { median: 160000 },
    },
    {
      period: "FY2025-Q4",
      filingCount: 4,
      certifiedCount: 3,
      deniedCount: 1,
      wageSummary: { median: 140000 },
    },
  ],
};
```

Then add these cases inside the existing `describe`:

```tsx
it("defaults to the rolling total and labels it with the period count", () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: quarterlyEvidence,
      }}
    />,
    { wrapper },
  );

  // The selector shows its LABEL, not the raw value, before it is ever opened.
  expect(screen.getByText("Last 2 quarters (total)")).toBeInTheDocument();
  expect(screen.getByText("14")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
});

it("switches figures to one quarter without changing the status banner", async () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: quarterlyEvidence,
      }}
    />,
    { wrapper },
  );

  fireEvent.click(screen.getByRole("combobox", { name: /period/i }));
  fireEvent.click(await screen.findByRole("option", { name: /FY2026 Q1/i }));

  await waitFor(() => expect(screen.getByText("10")).toBeInTheDocument());
  expect(screen.queryByText("14")).not.toBeInTheDocument();
  // Status is a property of the company research, never of one quarter.
  expect(screen.getByText("Historical filings found")).toBeInTheDocument();
});

it("falls back to the rollup when a refetch replaces the selected period", async () => {
  const { rerender } = render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: quarterlyEvidence,
      }}
    />,
    { wrapper },
  );
  fireEvent.click(screen.getByRole("combobox", { name: /period/i }));
  fireEvent.click(await screen.findByRole("option", { name: /FY2026 Q1/i }));

  rerender(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: {
          ...quarterlyEvidence,
          filingCount: 4,
          certifiedCount: 3,
          deniedCount: 1,
          periods: [quarterlyEvidence.periods[1]!],
        },
      }}
    />,
  );

  expect(screen.getByText("Last 1 quarter (total)")).toBeInTheDocument();
  expect(screen.getByText("4")).toBeInTheDocument();
});

it("hides the selector when the provider had no quarterly breakdown", () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: matchedEvidence,
      }}
    />,
    { wrapper },
  );

  expect(
    screen.queryByRole("combobox", { name: /period/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Denied filings")).not.toBeInTheDocument();
  expect(screen.getByText("Historical filings found")).toBeInTheDocument();
});

it("marks stale evidence without hiding its figures", () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: true,
        evidence: quarterlyEvidence,
      }}
    />,
    { wrapper },
  );

  expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
  expect(screen.getByText("14")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /refresh/i })).toBeEnabled();
});

it("shows stale warning for a legacy flat row too", () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: true,
        evidence: matchedEvidence,
      }}
    />,
    { wrapper },
  );

  expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
  expect(
    screen.queryByRole("combobox", { name: /period/i }),
  ).not.toBeInTheDocument();
});

it("warns that refreshing updates every job at the company", () => {
  render(
    <H1BSponsorshipPanel
      jobId={42}
      company="Acme"
      initialResult={{
        capability: "available",
        stale: false,
        evidence: quarterlyEvidence,
      }}
    />,
    { wrapper },
  );

  expect(
    screen.getByText(/updates every job at this company/i),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `web/`): `npx vitest run src/features/job/H1BSponsorshipPanel.test.tsx`
Expected: FAIL — no combobox, no stale text

- [ ] **Step 3: Add the period state and metric resolution**

In `H1BSponsorshipPanel.tsx`, add imports:

```tsx
import { useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
```

Add above the component:

```tsx
type PeriodStat = NonNullable<Evidence["periods"]>[number];

const ROLLUP = "__rollup__";

/** "FY2026-Q1" reads as "FY2026 Q1" -- provider labels are opaque, so only
 *  separators are prettified, never reordered or reparsed. */
function periodLabel(period: string): string {
  return period.replace(/[-_]+/g, " ");
}
```

- [ ] **Step 4: Replace `EvidenceDetails` metric selection**

Change `EvidenceDetails` to accept the selected metrics rather than reading the evidence flat:

```tsx
function EvidenceDetails({
  evidence,
  metrics,
}: {
  evidence: Evidence;
  metrics: Pick<
    PeriodStat,
    "filingCount" | "certifiedCount" | "deniedCount" | "wageSummary"
  >;
}) {
  const wageSummary = Object.entries(metrics.wageSummary ?? {});
  const filingPeriods = evidence.periods?.length
    ? evidence.periods.map((entry) => periodLabel(entry.period))
    : evidence.fiscalPeriods;
  const details: Array<readonly [string, string]> = [
    ["Company", evidence.displayCompany ?? evidence.normalizedCompany],
    [
      "Filing periods",
      filingPeriods.length ? filingPeriods.join(", ") : "Not reported",
    ],
    [
      "Filings",
      metrics.filingCount == null
        ? "Not reported"
        : String(metrics.filingCount),
    ],
    [
      "Certified filings",
      metrics.certifiedCount == null
        ? "Not reported"
        : String(metrics.certifiedCount),
    ],
    ...(evidence.periods?.length
      ? [
          [
            "Denied filings",
            metrics.deniedCount == null
              ? "Not reported"
              : String(metrics.deniedCount),
          ] as const,
        ]
      : []),
    ["Confidence", `${Math.round(evidence.confidence * 100)}%`],
    ["Retrieved", formatDate(evidence.retrievedAt)],
    ["Expires", formatDate(evidence.expiresAt)],
    ["Data version", evidence.dataVersion ?? "Not reported"],
  ];
  // ...rest of the existing body unchanged, using `wageSummary` as before
}
```

`wageSummary` is deliberately the active period's value when a period is
selected and the provider's top-level report aggregate for the rollup. Do not
pretend it can be derived by summing quarterly medians or percentiles.

- [ ] **Step 5: Render the selector and stale notice in the component body**

Inside `H1BSponsorshipPanel`, after the existing `status` line:

```tsx
const periods = evidence?.periods ?? [];
const [selectedPeriod, setSelectedPeriod] = useState<string>(ROLLUP);
const effectivePeriod =
  selectedPeriod === ROLLUP ||
  periods.some((entry) => entry.period === selectedPeriod)
    ? selectedPeriod
    : ROLLUP;
const activePeriod =
  effectivePeriod === ROLLUP
    ? undefined
    : periods.find((entry) => entry.period === effectivePeriod);
const metrics = activePeriod ?? {
  filingCount: evidence?.filingCount ?? null,
  certifiedCount: evidence?.certifiedCount ?? null,
  deniedCount: evidence?.deniedCount ?? null,
  wageSummary: evidence?.wageSummary ?? null,
};
const rollupLabel = `Last ${periods.length} quarter${periods.length === 1 ? "" : "s"} (total)`;
```

Change the button label so a stale row reads `Refresh`:

```tsx
const buttonLabel = checking
  ? "Checking…"
  : result?.capability === "disabled"
    ? "H-1B disabled"
    : result?.stale
      ? "Refresh"
      : status === "unavailable"
        ? "Try again"
        : status
          ? "Refresh check"
          : "Check H-1B";
```

Add the shared-cache notice under the panel heading paragraph:

```tsx
{
  company?.trim() && (
    <p className="mt-1 text-xs text-muted-foreground">
      Refreshing updates every job at this company.
    </p>
  );
}
```

Rename the section ID and its `aria-labelledby` reference from
`h1b-management-title` to `h1b-sponsorship-title`; the panel no longer belongs
to Management after Task 11.

And render the selector plus stale line immediately before `<EvidenceDetails …>`:

```tsx
{
  evidence && result?.stale && (
    <p className="mt-4 text-xs text-amber-700 dark:text-amber-400">
      ⚠ Checked {formatDate(evidence.retrievedAt)} — may be out of date
    </p>
  );
}

{
  evidence && status !== "unavailable" && periods.length > 0 && (
    <div className="mt-5 flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="h1b-period">Period</Label>
        <Select
          value={effectivePeriod}
          onValueChange={(value) => setSelectedPeriod(value ?? ROLLUP)}
        >
          <SelectTrigger id="h1b-period" className="w-64">
            {/* A bare <SelectValue /> renders the raw value until the
                    dropdown has been opened once -- resolve the label here. */}
            <SelectValue>
              {(value: string) =>
                effectivePeriod === ROLLUP
                  ? rollupLabel
                  : periodLabel(String(value))
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ROLLUP}>{rollupLabel}</SelectItem>
            {periods.map((entry) => (
              <SelectItem key={entry.period} value={entry.period}>
                {periodLabel(entry.period)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

{
  evidence && status !== "unavailable" && (
    <EvidenceDetails evidence={evidence} metrics={metrics} />
  );
}
```

Delete the old unconditional `{evidence && status !== "unavailable" && <EvidenceDetails evidence={evidence} />}` line it replaces.

- [ ] **Step 6: Run the tests to verify they pass**

Run (from `web/`): `npx vitest run src/features/job/H1BSponsorshipPanel.test.tsx`
Expected: PASS

> If the option query fails, inspect the rendered roles with `screen.debug()` — Base UI's Select renders `role="option"` inside a portal, and the trigger may expose `role="combobox"` only when it has an accessible name. Bind the `<Label htmlFor="h1b-period">` correctly rather than loosening the query.

- [ ] **Step 7: Typecheck and commit**

```bash
cd web && npx tsc --noEmit && cd ..
git add web/src/features/job/H1BSponsorshipPanel.tsx web/src/features/job/H1BSponsorshipPanel.test.tsx
git commit -m "feat: add H-1B period selector and stale labelling to the panel"
```

---

### Task 10: `TrackingTab` and the fenced danger zone

**Files:**

- Create: `web/src/features/job/TrackingTab.tsx`
- Create: `web/src/features/job/TrackingTab.test.tsx`
- Modify: `web/src/features/job/StageManager.tsx`

**Interfaces:**

- Consumes: `StageManager`, `ApplicationEditor`, `useDeleteJob`, `ConfirmDialog`.
- Produces: `TrackingTab({ job, onDeleted }: { job: JobDetail; onDeleted: () => void })`. Task 11 renders it.

**Why this matters:** the merge requested is a _tab_ merge, not a component merge — `ApplicationEditor` and `StageManager` keep their own mutation hooks and lifecycles. Only `Delete` relocates, so a destructive action stops sitting next to the routine `Set stage` button.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/job/TrackingTab.test.tsx`:

```tsx
import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("@/features/triage/use-triage-mutations", () => ({
  useDeleteJob: () => ({ mutate: mocks.mutate }),
}));

import { TrackingTab } from "./TrackingTab";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );
}

const baseJob = {
  id: 42,
  status: "shortlisted",
  hasProgress: false,
  application: null,
} as never;

describe("TrackingTab", () => {
  beforeEach(() => mocks.mutate.mockReset());

  it("renders stage, application, and a fenced danger zone", () => {
    render(<TrackingTab job={baseJob} onDeleted={vi.fn()} />, { wrapper });

    expect(screen.getByLabelText("Stage")).toBeInTheDocument();
    expect(screen.getByLabelText("Application status")).toBeInTheDocument();
    expect(screen.getByText("Danger zone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete/i })).toBeEnabled();
  });

  it("disables delete when the job has progress", () => {
    render(
      <TrackingTab
        job={{ ...baseJob, hasProgress: true } as never}
        onDeleted={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
    expect(screen.getByText(/has progress/i)).toBeInTheDocument();
  });

  it("no longer exposes delete from the stage section", () => {
    render(<TrackingTab job={baseJob} onDeleted={vi.fn()} />, { wrapper });
    expect(screen.getAllByRole("button", { name: /delete/i })).toHaveLength(1);
  });

  it("closes only after the delete mutation succeeds", async () => {
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<TrackingTab job={baseJob} onDeleted={onDeleted} />, { wrapper });

    await user.click(screen.getByRole("button", { name: /delete job/i }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(onDeleted).not.toHaveBeenCalled();
    const [, options] = mocks.mutate.mock.calls[0] ?? [];
    options?.onSuccess?.();
    expect(onDeleted).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npx vitest run src/features/job/TrackingTab.test.tsx`
Expected: FAIL — cannot resolve `./TrackingTab`

- [ ] **Step 3: Strip delete out of `StageManager`**

In `web/src/features/job/StageManager.tsx`, remove the `ConfirmDialog` block, the `useDeleteJob` import and call, the `onDeleted` prop, and the `job.hasProgress` paragraph. Keep the stage `<Select>`, the `Set stage` button, and the filtered/rejected explanatory paragraph. The resulting signature is:

```tsx
export function StageManager({ job }: { job: JobDetail }) {
```

Leave the `<div className="flex gap-2">` wrapper containing only the `Set stage` button.

- [ ] **Step 4: Create `TrackingTab`**

Create `web/src/features/job/TrackingTab.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ApplicationEditor } from "./ApplicationEditor";
import { StageManager } from "./StageManager";
import type { ReactNode } from "react";
import { useDeleteJob } from "@/features/triage/use-triage-mutations";
import type { JobDetail } from "./use-job-detail";

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
      {children}
    </h3>
  );
}

/**
 * Where the job stands, in causal order: pipeline stage, then what you did
 * about it, then the destructive action fenced off at the bottom.
 */
export function TrackingTab({
  job,
  onDeleted,
}: {
  job: JobDetail;
  onDeleted: () => void;
}) {
  const del = useDeleteJob();

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <SectionHeading>Pipeline stage</SectionHeading>
        <StageManager job={job} />
      </section>

      <hr className="border-border" />

      <section className="space-y-3">
        <SectionHeading>Application</SectionHeading>
        <ApplicationEditor jobId={job.id} application={job.application} />
      </section>

      <hr className="border-border" />

      <section className="space-y-3">
        <SectionHeading>Danger zone</SectionHeading>
        <div className="flex flex-wrap items-center gap-3">
          <ConfirmDialog
            trigger={
              <Button variant="destructive" disabled={job.hasProgress}>
                Delete job
              </Button>
            }
            title="Delete this job?"
            description="This cannot be undone."
            confirmLabel="Confirm delete"
            onConfirm={() => del.mutate(job.id, { onSuccess: onDeleted })}
          />
          {job.hasProgress && (
            <p className="text-xs text-muted-foreground">
              Has progress — delete disabled.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
```

Do not call `onDeleted()` optimistically. `useDeleteJob` surfaces a failed
server-side progress guard with a toast; closing the modal before `onSuccess`
would make a failed deletion look successful. The focused mutation mock above
captures the `onSuccess` option and proves `onDeleted` is called only through
that callback.

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `web/`): `npx vitest run src/features/job/TrackingTab.test.tsx`
Expected: PASS (4 passed, including close-only-on-success)

- [ ] **Step 6: Typecheck and commit**

```bash
cd web && npx tsc --noEmit && cd ..
git add web/src/features/job/TrackingTab.tsx web/src/features/job/TrackingTab.test.tsx web/src/features/job/StageManager.tsx
git commit -m "feat: add TrackingTab merging stage, application, and delete"
```

---

### Task 11: Restructure the job-modal tabs

**Files:**

- Modify: `web/src/components/JobModal.tsx:200-312`
- Test: `web/src/components/JobModal.test.tsx`

**Interfaces:**

- Consumes: `TrackingTab` (Task 10), `H1BSponsorshipPanel` (Task 9).
- Produces: tab values `jd | versions | coverLetters | tracking | interview | sponsorship`.

**Why this matters:** the tab count stays at six, so the tab bar does not wrap on narrow viewports.

- [ ] **Step 1: Write the failing test**

Replace the existing `"places H-1B research inside the Management tab"` test
and add the following tab-set assertion in `web/src/components/JobModal.test.tsx`.
Do not leave the old Management assertion behind:

This reuses the file's existing `wrap` helper and `jobPayload` factory — do not
introduce a second harness:

```tsx
it("exposes tracking and sponsorship tabs and no legacy application or management tab", async () => {
  server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
  wrap(<JobModal jobId={42} onClose={() => {}} />);

  expect(
    await screen.findByRole("tab", { name: "Tracking" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Sponsorship" })).toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "Application" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "Management" }),
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("tab")).toHaveLength(6);
});
```

The replacement H-1B test must click `Sponsorship` and assert the Historical
H-1B sponsorship heading is visible there. The tab-count test alone would not
prove the panel moved out of the old body.

> `jobPayload()` omits `h1BSponsorship` entirely, so the Sponsorship tab renders
> its "not checked" state — which is exactly the case worth pinning here.

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npx vitest run src/components/JobModal.test.tsx`
Expected: FAIL — no `Tracking` tab

- [ ] **Step 3: Replace the three affected triggers with the new set**

In `JobModal.tsx`, replace these three lines:

```tsx
                    <TabsTrigger value="application" className={tabTriggerClass}>Application</TabsTrigger>
                    <TabsTrigger value="interview" className={tabTriggerClass}>Interview</TabsTrigger>
                    <TabsTrigger value="manage" className={tabTriggerClass}>Management</TabsTrigger>
```

with:

```tsx
                    <TabsTrigger value="tracking" className={tabTriggerClass}>Tracking</TabsTrigger>
                    <TabsTrigger value="interview" className={tabTriggerClass}>Interview</TabsTrigger>
                    <TabsTrigger value="sponsorship" className={tabTriggerClass}>Sponsorship</TabsTrigger>
```

- [ ] **Step 4: Replace the two tab bodies**

Replace the `application` and `manage` `<TabsContent>` blocks with:

```tsx
<TabsContent value="tracking" className="mt-0">
  <TrackingTab job={job} onDeleted={onClose} />
</TabsContent>
```

and, after the `interview` block:

```tsx
<TabsContent value="sponsorship" className="mt-0">
  <H1BSponsorshipPanel
    jobId={jobId}
    company={job.company}
    initialResult={job.h1BSponsorship}
  />
</TabsContent>
```

- [ ] **Step 5: Fix the imports**

Replace the `ApplicationEditor` and `StageManager` imports with:

```tsx
import { TrackingTab } from "@/features/job/TrackingTab";
```

Keep the `H1BSponsorshipPanel` import. Run `npx eslint src/components/JobModal.tsx` to catch any import your change orphaned.

- [ ] **Step 6: Run the tests to verify they pass**

Run (from `web/`): `npx vitest run src/components/JobModal.test.tsx`
Expected: PASS

- [ ] **Step 7: Run the whole web suite**

Run (from `web/`): `npx vitest run`
Expected: PASS. Any test asserting on the `Application` or `Management` tab names must be updated to the new names — update the assertion, never delete the test.

- [ ] **Step 8: Typecheck and commit**

```bash
cd web && npx tsc --noEmit && cd ..
git add web/src/components/JobModal.tsx web/src/components/JobModal.test.tsx
git commit -m "feat: split job modal into Tracking and Sponsorship tabs"
```

---

### Task 12: Full verification and documentation

**Files:**

- Modify: `CLAUDE.md`

**Interfaces:**

- Consumes: everything.
- Produces: the durable statement of the cache-is-truth invariant.

- [ ] **Step 1: Run the complete backend suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS. Do not proceed until it is green — record the actual pass/fail counts.

- [ ] **Step 2: Run the complete web suite and typecheck**

Run (from `web/`): `npx vitest run && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 3: Lint**

Run: `ruff check`
Expected: no findings

- [ ] **Step 4: Confirm the contract is not drifted**

Run: `bash scripts/gen_ts_client.sh && git diff --stat -- contracts/ web/src/lib/api/schema.ts`
Expected: **no diff** — Task 3 already committed all three generated files. A
non-empty diff means a schema change landed after Task 3; commit the regenerated
contract **and** the copied SPA schema. Use the Windows fallback from Global
Constraints if Bash fails before generation.

- [ ] **Step 5: Document the invariant**

In `CLAUDE.md`, under **Known design notes**, add:

```markdown
- **H-1B evidence is per company, and the cache is the only display source.**
  `h1b_company_evidence` (keyed by `normalize_company`, TTL
  `Settings.h1b_cache_ttl_days`) is read through the single batched seam
  `h1b/cache.py::load_company_evidence` — one query per request, the map passed
  down to row projections rather than looked up per row. The job detail and all
  three board projections read it; `JobAnalysisMeta.h1b_evidence_snapshot` is no
  longer written or read (the field remains only so old rows deserialize, and
  `h1b_evidence_id` remains as a provenance pointer). **Expired rows still
  render**, labelled stale via `H1BSponsorshipOut.stale` — historical filings do
  not rot, and nothing auto-refreshes: an LLM call happens only on an explicit
  manual check or a discovery run. Evidence carries a per-quarter `periods`
  breakdown whose top-level **count** rollup is **derived by the model validator,
  never trusted from the agent**, so count totals can never contradict the parts
  shown beneath them; report-level wage summaries remain provider aggregates.
  `periods: []` is valid and degrades to the flat pre-quarter view.
  Discovery researches every surviving job's company (gated on
  `config.sponsorship_required`, bounded by
  `Settings.h1b_enrich_max_companies_per_run`), but `run_h1b_enrichment` still
  returns **only** `silent` jobs to the fit scorer — a JD that explicitly refuses
  sponsorship must not have its score lifted by filing history. Fresh cache hits
  reach that map without an agent call; expired entries deferred by the cap are
  display-only until refreshed. `h1b_evidence_id` is updated for every covered
  in-scope job as provenance, while no job writes a snapshot.
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the H-1B company-cache invariant"
```

---

## Self-Review

**Spec coverage**

| Spec section                                                                                        | Task                                   |
| --------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `H1BPeriodStat`, `periods`, `denied_count`, derived rollup, bounds, uniqueness                      | 1                                      |
| Additive schema evolution, no migration                                                             | 1 (defaults), 7 (`schema_version = 2`) |
| `load_company_evidence` batched seam, corruption tolerance, expiry passthrough                      | 2                                      |
| `H1BPeriodStatOut`, wire projection, `stale`                                                        | 3                                      |
| Job detail reads the cache                                                                          | 4                                      |
| Board row projections read the cache; N+1 pin                                                       | 5                                      |
| Retire the per-job snapshot; keep `h1b_evidence_id`                                                 | 6                                      |
| Agent instructed to collect four quarters; graceful `periods: []`                                   | 7                                      |
| Widen research, keep scoring narrow, per-run cap, new setting                                       | 8                                      |
| Fresh cache hits reach the scorer without being re-researched                                       | 8                                      |
| Period selector, status banner invariance, stale label, `SelectValue` resolver, shared-cache notice | 9                                      |
| `TrackingTab`, delete relocation                                                                    | 10                                     |
| Six-tab restructure                                                                                 | 11                                     |
| Contract regen gate, CLAUDE.md                                                                      | 3, 12                                 

## Self-Review

**Spec coverage**

| Spec section | Task |
| --- | --- |
| `H1BPeriodStat`, `periods`, `denied_count`, derived rollup, bounds, uniqueness | 1 |
| Additive schema evolution, no migration | 1 (defaults), 7 (`schema_version = 2`) |
| `load_company_evidence` batched seam, corruption tolerance, expiry passthrough | 2 |
| `H1BPeriodStatOut`, wire projection, `stale` | 3 |
| Job detail reads the cache | 4 |
| Board row projections read the cache; N+1 pin | 5 |
| Retire the per-job snapshot; keep `h1b_evidence_id` | 6 |
| Agent instructed to collect four quarters; graceful `periods: []` | 7 |
| Widen research, keep scoring narrow, per-run cap, new setting | 8 |
| Fresh cache hits reach the scorer without being re-researched | 8 |
| Period selector, status banner invariance, stale label, `SelectValue` resolver, shared-cache notice | 9 |
| `TrackingTab`, delete relocation | 10 |
| Six-tab restructure | 11 |
| Contract regen gate, CLAUDE.md | 3, 12 |

**Known gaps, deliberately left**

- **The provider's tool signatures are unverified.** `H1B_MCP_COMMAND` is empty in this workspace, so Task 7's instruction text is written against the documented tool names (`get_available_data`, `get_company_stats`) without a live call to confirm they accept or expose a quarter dimension. The degradation path (`periods: []` → flat view) is what makes this safe; if you gain access to a live MCP server, verify the quarter slice before trusting the selector in production.
- **`h1b_enrich_max_companies_per_run = 50` is unvalidated.** It is a judgment call about spend, not a measured figure.
- **Two files carry a `# type: ignore[call-arg]` on `Settings(_env_file=None, …)`** in new tests. This matches the existing convention in `tests/test_h1b_service.py`; do not "fix" it.

**Type consistency check**

`load_company_evidence(session, companies) -> dict[str, H1BSponsorshipEvidence]` is used identically in Tasks 4, 5, and 8. `_h1b_sponsorship_status(job, evidence_by_company)` has one definition (Task 5) and three call sites, all updated in the same task. `H1BPeriodStat` field names (`period`, `filing_count`, `certified_count`, `denied_count`, `wage_summary`) match `H1BPeriodStatOut` and the camelCase wire names asserted in Task 9. `TrackingTab({ job, onDeleted })` as produced in Task 10 matches its call in Task 11. `StageManager({ job })` loses `onDeleted` in Task 10 and has exactly one caller, updated in the same task.
