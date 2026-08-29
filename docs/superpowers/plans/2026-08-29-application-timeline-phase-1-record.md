# Application Timeline — Phase 1: The Record — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-status, single-date `Application` snapshot with an `ApplicationEvent` log that records every dated stage of a job application, and amend the two invariants that stand in its way.

**Architecture:** A new `application_events` table hangs off `applications`, one row per timeline entry, with closed enum vocabularies for kind/modality/platform/result. Events auto-advance `Application.status` under a new progression-versus-terminal rule (replacing a flat high-water mark that cannot express `interview → rejected`). `has_progress` is refined so an empty `ready` application no longer trips the delete gate. The web Tracking tab is restructured so status is a *header* over the timeline rather than a peer widget.

**Tech Stack:** Python 3.13, SQLModel/SQLAlchemy over SQLite, FastAPI, pytest. React 19 + TypeScript, Base UI + Tailwind 4, TanStack Query, vitest + Testing Library.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-29-application-timeline-design.md`. Read it before Task 1.
- **Tests run offline.** No API key, no network. `.venv/Scripts/python.exe -m pytest`
- **Lint:** `ruff check` must pass. Web: `npm --prefix web run lint`.
- **No LLM anywhere in this phase.** Deterministic CRUD, date arithmetic, aggregation only.
- **No new Python or npm dependencies.**
- **All datetimes stored UTC.** Use `resume_agent.tracking.tables.utcnow` — never `datetime.now()`.
- **API wire format is camelCase.** All request/response models subclass `CamelModel` (`api/schemas/base.py`); Python fields stay snake_case and the alias generator maps them.
- **Errors use `ApiException(status_code, code, message)`** from `api/errors.py`. Validation failures are `422` / `"VALIDATION_ERROR"`, missing rows `404` / `"NOT_FOUND"`.
- **SQLite runs without `PRAGMA foreign_keys`.** Declared FKs do not cascade or restrict. Any cleanup must be explicit in code.
- **After any API schema change**, regenerate the contract: `make openapi && make client` (or `bash scripts/gen_ts_client.sh`). Commit `contracts/openapi.json`, `contracts/ts/api.ts`, and `web/src/lib/api/schema.ts` together with the change.

## Correctness amendment (reviewed 2026-08-29)

- Persist `sequence_override` separately from effective `sequence`; NULL means
  automatic. Expose nullable `sequenceOverride` in event responses so edit forms
  do not resubmit automatic values as manual choices, and accept PATCH null to
  clear an override. Add the idempotent nullable-column ALTER migration before
  the submitted-event backfill. Because legacy provenance is unrecoverable,
  freeze existing effective values as overrides so later mutations cannot
  silently destroy an old manual order; users can clear them explicitly.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/tracking/event_vocab.py` | **Create.** The four enums + the kind→status mapping. Pure data, no I/O, no SQLModel import. Isolated so tests and the web contract can read the vocabulary without touching the DB layer. |
| `src/resume_agent/tracking/tables.py` | **Modify.** Add the `ApplicationEvent` table. |
| `src/resume_agent/db.py` | **Modify.** Import `ApplicationEvent` into the metadata block; register the backfill migration. |
| `src/resume_agent/tracking/migrate.py` | **Modify.** Add `ensure_application_event_sequence_override_column` and `ensure_application_submitted_events`. |
| `src/resume_agent/tracking/repository.py` | **Modify.** Event CRUD; refine `has_progress` and `progressed_job_ids`. |
| `src/resume_agent/tracking/status_rules.py` | **Create.** Progression-versus-terminal transition logic. Pure function over strings — no session, no ORM — so the rule is testable in isolation and readable by anyone auditing the invariant. |
| `src/resume_agent/services/application_events.py` | **Create.** Service layer: validation, sequence assignment, status advancement, transactional create/update/delete. |
| `src/resume_agent/api/schemas/application_events.py` | **Create.** `ApplicationEventOut`, `ApplicationEventCreate`, `ApplicationEventUpdate`. |
| `src/resume_agent/api/routers/application_events.py` | **Create.** Four routes nested under `/jobs/{job_id}/events`. |
| `src/resume_agent/api/app.py` | **Modify.** Register the router. |
| `docs/adr/0012-application-status-progression-and-terminal.md` | **Create.** |
| `docs/adr/0013-has-progress-requires-real-investment.md` | **Create.** |
| `web/src/features/job/use-application-events.ts` | **Create.** Query + mutation hooks. |
| `web/src/features/job/EventRow.tsx` | **Create.** One event, display + inline edit. |
| `web/src/features/job/EventFormDialog.tsx` | **Create.** Add/edit form. |
| `web/src/features/job/ApplicationTimeline.tsx` | **Create.** Ordered list + add button. |
| `web/src/features/job/ApplicationEditor.tsx` | **Modify.** Becomes the status header + notes textarea; hosts the timeline. |

Split rationale: `event_vocab.py` and `status_rules.py` are separated from `repository.py` because they are the two pieces an auditor of the amended invariants must read, and burying them in a 500-line repository module makes that audit harder. The web files split by responsibility (one event / the form / the list) rather than dumping ~400 lines into `ApplicationEditor.tsx`.

---

### Task 1: Event vocabulary

**Files:**
- Create: `src/resume_agent/tracking/event_vocab.py`
- Test: `tests/test_event_vocab.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EventKind`, `Modality`, `Platform`, `EventResult` (all `str, Enum`); `KIND_IMPLIES_STATUS: dict[str, str]`; `REPEATABLE_KINDS: frozenset[str]`; `FUNNEL_KINDS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_vocab.py
from resume_agent.tracking.event_vocab import (
    FUNNEL_KINDS,
    KIND_IMPLIES_STATUS,
    REPEATABLE_KINDS,
    EventKind,
    EventResult,
    Modality,
    Platform,
)
from resume_agent.tracking.tables import ApplicationStatus


def test_every_kind_except_custom_has_a_status_implication():
    missing = {k.value for k in EventKind} - set(KIND_IMPLIES_STATUS)
    assert missing == {EventKind.custom.value}


def test_status_implications_are_all_real_application_statuses():
    valid = {s.value for s in ApplicationStatus}
    assert set(KIND_IMPLIES_STATUS.values()) <= valid


def test_interview_kinds_all_imply_interview():
    for kind in (
        EventKind.recruiter_screen,
        EventKind.online_assessment,
        EventKind.questionnaire,
        EventKind.technical_phone_screen,
        EventKind.technical_round,
        EventKind.system_design,
        EventKind.behavioral,
        EventKind.hiring_manager,
        EventKind.onsite_loop,
        EventKind.team_match,
    ):
        assert KIND_IMPLIES_STATUS[kind.value] == ApplicationStatus.interview.value


def test_offer_kinds_imply_offer_and_exits_are_terminal():
    assert KIND_IMPLIES_STATUS[EventKind.offer_received.value] == "offer"
    assert KIND_IMPLIES_STATUS[EventKind.offer_deadline.value] == "offer"
    assert KIND_IMPLIES_STATUS[EventKind.rejected.value] == "rejected"
    assert KIND_IMPLIES_STATUS[EventKind.withdrawn.value] == "closed"


def test_repeatable_kinds_are_technical_round_and_offer_received():
    assert REPEATABLE_KINDS == frozenset(
        {EventKind.technical_round.value, EventKind.offer_received.value}
    )


def test_custom_is_excluded_from_the_funnel():
    assert EventKind.custom.value not in FUNNEL_KINDS
    assert FUNNEL_KINDS[0] == EventKind.application_submitted.value


def test_online_assessment_and_questionnaire_are_distinct():
    assert EventKind.online_assessment.value != EventKind.questionnaire.value


def test_async_modality_uses_a_non_keyword_member_name():
    assert Modality.async_.value == "async"


def test_platform_and_result_vocabularies():
    assert "tencent_meeting" in {p.value for p in Platform}
    assert "no_response" in {r.value for r in EventResult}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_vocab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking.event_vocab'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/tracking/event_vocab.py
"""Closed vocabularies for application timeline events.

Kept free of SQLModel and of any session import: these are the values an
auditor of the amended status invariant reads, and the values the funnel
analytics group by. Pure data, importable from anywhere.
"""

from __future__ import annotations

from enum import Enum


class EventKind(str, Enum):
    application_submitted = "application_submitted"
    recruiter_screen = "recruiter_screen"
    online_assessment = "online_assessment"
    questionnaire = "questionnaire"
    technical_phone_screen = "technical_phone_screen"
    technical_round = "technical_round"
    system_design = "system_design"
    behavioral = "behavioral"
    hiring_manager = "hiring_manager"
    onsite_loop = "onsite_loop"
    team_match = "team_match"
    offer_received = "offer_received"
    offer_deadline = "offer_deadline"
    rejected = "rejected"
    withdrawn = "withdrawn"
    custom = "custom"


class Modality(str, Enum):
    onsite = "onsite"
    virtual = "virtual"
    phone = "phone"
    async_ = "async"  # `async` is a Python keyword; the wire value is "async"


class Platform(str, Enum):
    zoom = "zoom"
    teams = "teams"
    google_meet = "google_meet"
    webex = "webex"
    tencent_meeting = "tencent_meeting"
    feishu = "feishu"
    phone = "phone"
    hackerrank = "hackerrank"
    codesignal = "codesignal"
    coderpad = "coderpad"
    karat = "karat"
    other = "other"


class EventResult(str, Enum):
    pending = "pending"
    advanced = "advanced"
    rejected = "rejected"
    no_response = "no_response"  # ghosting is not rejection
    cancelled = "cancelled"
    withdrew = "withdrew"


_INTERVIEW_KINDS = (
    EventKind.recruiter_screen,
    EventKind.online_assessment,
    EventKind.questionnaire,
    EventKind.technical_phone_screen,
    EventKind.technical_round,
    EventKind.system_design,
    EventKind.behavioral,
    EventKind.hiring_manager,
    EventKind.onsite_loop,
    EventKind.team_match,
)

KIND_IMPLIES_STATUS: dict[str, str] = {
    EventKind.application_submitted.value: "submitted",
    **{kind.value: "interview" for kind in _INTERVIEW_KINDS},
    EventKind.offer_received.value: "offer",
    EventKind.offer_deadline.value: "offer",
    EventKind.rejected.value: "rejected",
    EventKind.withdrawn.value: "closed",
}
"""What logging an event implies about Application.status.

`custom` is deliberately absent: a user-labelled event says nothing about the
funnel, so it never moves status.
"""

REPEATABLE_KINDS: frozenset[str] = frozenset(
    {EventKind.technical_round.value, EventKind.offer_received.value}
)
"""Kinds that legitimately occur more than once and carry a `sequence`.

`offer_received` repeats because a negotiated revision is a new event, which
is what gives negotiation history for free.
"""

FUNNEL_KINDS: tuple[str, ...] = (
    EventKind.application_submitted.value,
    EventKind.recruiter_screen.value,
    EventKind.online_assessment.value,
    EventKind.questionnaire.value,
    EventKind.technical_phone_screen.value,
    EventKind.technical_round.value,
    EventKind.system_design.value,
    EventKind.behavioral.value,
    EventKind.hiring_manager.value,
    EventKind.onsite_loop.value,
    EventKind.team_match.value,
    EventKind.offer_received.value,
)
"""Funnel order for the Sankey and cycle-time charts (Phase 3).

`custom` is excluded so user-labelled events cannot distort the numbers;
`offer_deadline`, `rejected`, and `withdrawn` are excluded because they are
not stages a candidate passes through.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_vocab.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking/event_vocab.py tests/test_event_vocab.py
git add src/resume_agent/tracking/event_vocab.py tests/test_event_vocab.py
git commit -m "feat(tracking): add application event vocabularies"
```

---

### Task 2: The `ApplicationEvent` table

**Files:**
- Modify: `src/resume_agent/tracking/tables.py` (append after `Application`, ~line 128)
- Modify: `src/resume_agent/db.py:10-30` (metadata import block)
- Test: `tests/test_application_event_table.py`

**Interfaces:**
- Consumes: Task 1's enums (for default values only).
- Produces: `resume_agent.tracking.tables.ApplicationEvent` with the exact field names listed in the implementation below. Every later task uses these names.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_application_event_table.py
from datetime import datetime, timezone

from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_create_all_makes_the_table_without_a_migration():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="test", company="Acme", title="SWE")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id, status="submitted")
        session.add(app)
        session.commit()
        session.refresh(app)
        event = ApplicationEvent(
            application_id=app.id,
            kind="technical_round",
            sequence=1,
            occurred_at=datetime(2026, 3, 3, 19, 0, tzinfo=timezone.utc),
            timezone="America/New_York",
            duration_minutes=60,
            modality="virtual",
            platform="zoom",
        )
        session.add(event)
        session.commit()
        stored = session.exec(select(ApplicationEvent)).one()
        assert stored.kind == "technical_round"
        assert stored.result == "pending"
        assert stored.all_day is False
        assert stored.source == "manual"
        assert stored.schema_version == 1


def test_comp_fields_default_to_none():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="test")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id)
        session.add(app)
        session.commit()
        session.refresh(app)
        event = ApplicationEvent(application_id=app.id, kind="recruiter_screen")
        session.add(event)
        session.commit()
        stored = session.exec(select(ApplicationEvent)).one()
        assert stored.comp_base is None
        assert stored.comp_currency is None
        assert stored.reflection is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_table.py -v`
Expected: FAIL — `ImportError: cannot import name 'ApplicationEvent'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/tracking/tables.py`, directly after the `Application` class:

```python
class ApplicationEvent(SQLModel, table=True):
    """One dated entry on an application's timeline.

    An event log rather than wide columns on Application: the round count is
    unbounded (loops run to five, companies insert team-match calls), so
    columns would cap the model and make every new stage a migration. The
    spreadsheet the user reads is a pivot over these rows.
    """

    __tablename__ = cast(Any, "application_events")

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)

    kind: str = Field(index=True)
    custom_label: str | None = None
    sequence: int = 1

    # UTC. `all_day` distinguishes "applied on the 3rd" from "Zoom at 14:00";
    # `timezone` is an IANA name, not an offset, because DST can shift between
    # logging an event and its occurrence.
    occurred_at: datetime | None = Field(default=None, index=True)
    all_day: bool = False
    timezone: str | None = None
    duration_minutes: int | None = None

    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None

    result: str = Field(default="pending", index=True)
    notes: str | None = None
    reflection: str | None = None

    # offer_received only; total compensation is derived, never stored.
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None

    source: str = Field(default="manual")  # manual | migration | gmail
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

Then in `src/resume_agent/db.py`, add `ApplicationEvent` to the existing table-import block near line 10 so its metadata registers before `create_all`. Find the line importing `Application` from `resume_agent.tracking.tables` and add `ApplicationEvent` to it.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_table.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Verify nothing else broke**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q -x`
Expected: PASS — no collection errors, no regressions.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_agent/tracking/tables.py src/resume_agent/db.py
git add src/resume_agent/tracking/tables.py src/resume_agent/db.py tests/test_application_event_table.py
git commit -m "feat(tracking): add ApplicationEvent table"
```

---

### Task 3: Status transition rules (progression versus terminal)

**Files:**
- Create: `src/resume_agent/tracking/status_rules.py`
- Create: `docs/adr/0012-application-status-progression-and-terminal.md`
- Test: `tests/test_status_rules.py`

**Interfaces:**
- Consumes: Task 1's `KIND_IMPLIES_STATUS`.
- Produces: `advance_application_status(current: str, implied: str) -> str`; `PROGRESSION: tuple[str, ...]`; `TERMINAL: frozenset[str]`.

**Why this is its own file:** it amends an invariant documented in `tracking/CLAUDE.md`. Anyone auditing that invariant should be able to read the whole rule in one screen, without a session or an ORM in scope.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_status_rules.py
import pytest

from resume_agent.tracking.status_rules import (
    PROGRESSION,
    TERMINAL,
    advance_application_status,
)


@pytest.mark.parametrize(
    "current,implied,expected",
    [
        ("ready", "submitted", "submitted"),
        ("submitted", "interview", "interview"),
        ("interview", "offer", "offer"),
        # Forward-only: a late-logged earlier stage never demotes.
        ("offer", "interview", "offer"),
        ("interview", "submitted", "interview"),
        ("submitted", "submitted", "submitted"),
    ],
)
def test_progression_advances_forward_only(current, implied, expected):
    assert advance_application_status(current, implied) == expected


@pytest.mark.parametrize("current", ["ready", "submitted", "interview", "offer"])
def test_terminal_is_reachable_from_every_progression_state(current):
    assert advance_application_status(current, "rejected") == "rejected"
    assert advance_application_status(current, "closed") == "closed"


def test_offer_to_rejected_works_because_offers_get_rescinded():
    assert advance_application_status("offer", "rejected") == "rejected"


def test_terminal_states_are_sticky_against_progression():
    assert advance_application_status("rejected", "interview") == "rejected"
    assert advance_application_status("closed", "offer") == "closed"


def test_terminal_can_be_replaced_by_the_other_terminal():
    assert advance_application_status("rejected", "closed") == "closed"


def test_vocabulary_shape():
    assert PROGRESSION == ("ready", "submitted", "interview", "offer")
    assert TERMINAL == frozenset({"rejected", "closed"})


def test_unknown_implied_status_is_a_no_op():
    assert advance_application_status("submitted", "nonsense") == "submitted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_status_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking.status_rules'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/tracking/status_rules.py
"""How an event moves Application.status. See ADR-0012.

A flat high-water mark cannot express the most common transition in a job
hunt: `interview -> rejected`. `rejected` is not *behind* `interview`, it is
an *exit*. So the rule has two halves — an ordered progression that only
advances, and a terminal set reachable from anywhere. This mirrors
`gmail/propose.py`'s existing `_TERMINAL` rather than inventing a second rule.
"""

from __future__ import annotations

PROGRESSION: tuple[str, ...] = ("ready", "submitted", "interview", "offer")
TERMINAL: frozenset[str] = frozenset({"rejected", "closed"})


def advance_application_status(current: str, implied: str) -> str:
    """Return the status after an event implying `implied` is logged.

    Never raises: an unrecognised `implied` is a no-op, because a vocabulary
    gap must not block recording what happened.
    """
    if implied in TERMINAL:
        return implied
    if current in TERMINAL:
        return current  # an exit is not undone by logging an earlier stage
    if implied not in PROGRESSION or current not in PROGRESSION:
        return current
    return implied if PROGRESSION.index(implied) > PROGRESSION.index(current) else current
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_status_rules.py -v`
Expected: PASS (16 tests including parametrized cases)

- [ ] **Step 5: Write the ADR**

Create `docs/adr/0012-application-status-progression-and-terminal.md`:

```markdown
# 12. Application status is a progression plus a terminal set, not a high-water mark

Date: 2026-08-29

## Status

Accepted

## Context

`tracking/CLAUDE.md` documents status as a forward-only high-water mark, by
analogy with `JobStatus` and `tracking/stages.py::advance`. That analogy does
not hold for `ApplicationStatus`.

`ApplicationStatus` has no defined ordering, and `rejected` is not behind
`interview` — it is an exit from the funnel. A flat high-water mark blocks
`interview -> rejected`, the single most common transition in a job hunt, and
`offer -> rejected`, which is what a rescinded offer is.

The codebase already encodes the distinction: `gmail/propose.py:13` defines
`_TERMINAL = {rejected, closed}` and handles it separately from progression.

## Decision

Status has two halves, in `tracking/status_rules.py`:

- **Progression** `ready < submitted < interview < offer` advances forward
  only. A late-logged earlier stage never demotes.
- **Terminal** `{rejected, closed}` is reachable from any progression state,
  including `offer`. A terminal state is not undone by logging an earlier
  stage; it is replaceable only by the other terminal state.

`ApplicationEvent` creation applies `KIND_IMPLIES_STATUS` through this rule.
Manual edits and Gmail proposals continue to write status directly.

## Consequences

- Two clarifications this rule deliberately makes:
  - `EventResult.rejected` on a round does **not** move status. A weak round
    is not a dead application; only a `rejected` *event* is terminal.
  - Deleting an event never moves status back. Progression is forward-only,
    so a mis-logged event is undone with the manual override, not by deletion.
- `tracking/CLAUDE.md`'s "status is a high-water mark" wording applies to
  `JobStatus` only and is amended for `ApplicationStatus`.
- Do not add ordering comparisons against `ApplicationStatus` members; the
  ordering lives in `PROGRESSION` and nowhere else.
```

- [ ] **Step 6: Amend the tracking CLAUDE.md**

In `src/resume_agent/tracking/CLAUDE.md`, under "Redo — forward-only, never destructive", add a note distinguishing `JobStatus` (high-water mark) from `ApplicationStatus` (progression + terminal, ADR-0012). Do not delete the existing `JobStatus` wording — it remains correct for jobs.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/resume_agent/tracking/status_rules.py tests/test_status_rules.py
git add src/resume_agent/tracking/status_rules.py tests/test_status_rules.py docs/adr/0012-application-status-progression-and-terminal.md src/resume_agent/tracking/CLAUDE.md
git commit -m "feat(tracking): progression-vs-terminal application status (ADR-0012)"
```

---

### Task 4: Refine `has_progress` so an empty application is not investment

**Files:**
- Modify: `src/resume_agent/tracking/repository.py:470-500` (`has_progress`, `progressed_job_ids`)
- Create: `docs/adr/0013-has-progress-requires-real-investment.md`
- Test: `tests/test_has_progress_investment.py`

**Interfaces:**
- Consumes: Task 2's `ApplicationEvent`.
- Produces: unchanged signatures — `has_progress(session, job_id) -> bool`, `progressed_job_ids(session, job_ids=None) -> set[int]`. Behaviour changes only.

**Danger:** this **loosens a destructive-action gate**. Both directions must be pinned, and `progressed_job_ids` must agree with `has_progress` on identical fixtures — it exists to batch exactly this predicate and would otherwise silently diverge.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_has_progress_investment.py
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.repository import has_progress, progressed_job_ids
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _setup(**app_kwargs):
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test", company="Acme", title="SWE", status="raw")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, **app_kwargs)
    session.add(app)
    session.commit()
    session.refresh(app)
    return session, job, app


def test_empty_ready_application_is_not_progress():
    session, job, _ = _setup(status="ready")
    assert has_progress(session, job.id) is False
    assert progressed_job_ids(session) == set()


def test_application_with_one_event_is_progress():
    session, job, app = _setup(status="ready")
    session.add(ApplicationEvent(application_id=app.id, kind="recruiter_screen"))
    session.commit()
    assert has_progress(session, job.id) is True
    assert progressed_job_ids(session) == {job.id}


def test_non_ready_status_is_progress():
    session, job, _ = _setup(status="submitted")
    assert has_progress(session, job.id) is True
    assert progressed_job_ids(session) == {job.id}


def test_notes_are_progress():
    session, job, _ = _setup(status="ready", notes="applied via referral")
    assert has_progress(session, job.id) is True


def test_blank_notes_are_not_progress():
    session, job, _ = _setup(status="ready", notes="   ")
    assert has_progress(session, job.id) is False


def test_selected_artifact_pointer_is_progress():
    session, job, _ = _setup(status="ready", resume_version_id=1)
    assert has_progress(session, job.id) is True


def test_job_status_check_is_unchanged():
    session, job, _ = _setup(status="ready")
    job.status = "rendered"
    session.add(job)
    session.commit()
    assert has_progress(session, job.id) is True


def test_batched_and_single_predicates_agree_across_a_mixed_set():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    ids = []
    for status, add_event in (("ready", False), ("ready", True), ("submitted", False)):
        job = Job(source="test", status="raw")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id, status=status)
        session.add(app)
        session.commit()
        session.refresh(app)
        if add_event:
            session.add(ApplicationEvent(application_id=app.id, kind="behavioral"))
            session.commit()
        ids.append(job.id)
    batched = progressed_job_ids(session, ids)
    singles = {i for i in ids if has_progress(session, i)}
    assert batched == singles
    assert batched == {ids[1], ids[2]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_has_progress_investment.py -v`
Expected: FAIL — `test_empty_ready_application_is_not_progress` and `test_blank_notes_are_not_progress` fail, because any `Application` row currently counts.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/tracking/repository.py`, add a shared predicate above `has_progress` and use it in both functions:

```python
def _application_is_investment(session: Session, application: Application) -> bool:
    """True when an Application row represents work the user would mourn.

    An empty `ready` row is created by merely opening the Tracking tab
    (`services/board.py::upsert_application` writes unconditionally), so
    counting bare existence permanently blocked `delete_job` for jobs with
    zero user investment. See ADR-0013.
    """
    if application.status != ApplicationStatus.ready.value:
        return True
    if (application.notes or "").strip():
        return True
    if application.resume_version_id is not None or application.cover_letter_id is not None:
        return True
    return (
        session.exec(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == application.id
            )
        ).first()
        is not None
    )
```

Rewrite `has_progress` so the `Application` branch consults it while
`ResumeVersion` and `CoverLetter` keep their existence check:

```python
def has_progress(session: Session, job_id: int) -> bool:
    """True if a job has user investment that must never be destroyed."""
    job = session.get(Job, job_id)
    if job is None:
        return False
    if job.status in _PROGRESS_STATUSES:
        return True
    for application in session.exec(
        select(Application).where(Application.job_id == job_id)
    ).all():
        if _application_is_investment(session, application):
            return True
    for model in (ResumeVersion, CoverLetter):
        if session.exec(select(model).where(model.job_id == job_id)).first() is not None:
            return True
    return False
```

Then update `progressed_job_ids` so its `Application` pass applies the same
predicate rather than bare existence. Keep `ResumeVersion` and `CoverLetter`
batched exactly as they are today — only the `Application` branch changes.
Import `ApplicationEvent` at the top of the module.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_has_progress_investment.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Verify the existing invariant tests still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q -k "progress or delete or prune"`
Expected: PASS. In particular `test_deleting_every_version_does_not_make_a_progressed_job_deletable` must still pass — `job.status` is still a high-water mark and that check is untouched. If it fails, stop: the change has gone further than intended.

- [ ] **Step 6: Write the ADR**

Create `docs/adr/0013-has-progress-requires-real-investment.md`:

```markdown
# 13. has_progress requires real investment, not a bare Application row

Date: 2026-08-29

## Status

Accepted

## Context

`has_progress` returned True if any `Application` row existed for a job.
`services/board.py::upsert_application` creates that row unconditionally, so
saving status `ready` with no notes — a no-op by any reasonable reading —
permanently tripped the `delete_job` gate.

The application timeline makes this fire constantly rather than occasionally:
recording a single date would lock a job forever, including one logged against
the wrong company.

## Decision

An `Application` counts as progress only when it carries investment:

    status != "ready"
      OR notes is non-blank
      OR any ApplicationEvent exists
      OR resume_version_id / cover_letter_id is set

`ResumeVersion` and `CoverLetter` existence checks are unchanged, as is
`job.status in {approved, tailored, rendered}`. `progressed_job_ids` applies
the identical predicate; it exists to batch this check and must never diverge.

## Consequences

- This **loosens a destructive gate**. Tests pin both directions: an empty
  `ready` row deletes; a row with one event refuses.
- Jobs already stuck in existing databases become deletable. This is the
  intended repair, not a side effect.
- The gate's meaning is now "investment", matching its docstring, rather than
  "a row exists".
- Any future child table of `Application` must be added to
  `_application_is_investment` *and* to `progressed_job_ids` together.
```

- [ ] **Step 7: Amend the CLAUDE.md invariants**

Update the "Archive, delete, prune" bullet in the root `CLAUDE.md` and the corresponding section in `src/resume_agent/tracking/CLAUDE.md` to state that an `Application` counts only with real investment, citing ADR-0013.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src/resume_agent/tracking/repository.py tests/test_has_progress_investment.py
git add src/resume_agent/tracking/repository.py tests/test_has_progress_investment.py docs/adr/0013-has-progress-requires-real-investment.md CLAUDE.md src/resume_agent/tracking/CLAUDE.md
git commit -m "fix(tracking): has_progress requires real investment (ADR-0013)"
```

---

### Task 5: Event repository CRUD

**Files:**
- Modify: `src/resume_agent/tracking/repository.py` (append near the other application helpers)
- Test: `tests/test_application_event_repository.py`

**Interfaces:**
- Consumes: Task 2's `ApplicationEvent`.
- Produces:
  - `events_for_application(session, application_id) -> list[ApplicationEvent]` — ordered by `occurred_at` ascending, nulls last, tie-broken by `created_at`.
  - `get_application_event(session, event_id) -> ApplicationEvent | None`
  - `save_application_event(session, event) -> ApplicationEvent`
  - `delete_application_event(session, event_id) -> bool`
  - `next_sequence(session, application_id, kind) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_application_event_repository.py
from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.repository import (
    delete_application_event,
    events_for_application,
    get_application_event,
    next_sequence,
    save_application_event,
)
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _app():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id)
    session.add(app)
    session.commit()
    session.refresh(app)
    return session, app


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def test_events_are_ordered_by_date_ascending():
    session, app = _app()
    for day, kind in ((9, "online_assessment"), (3, "recruiter_screen")):
        save_application_event(
            session, ApplicationEvent(application_id=app.id, kind=kind, occurred_at=_at(day))
        )
    kinds = [e.kind for e in events_for_application(session, app.id)]
    assert kinds == ["recruiter_screen", "online_assessment"]


def test_undated_events_sort_last():
    session, app = _app()
    save_application_event(
        session, ApplicationEvent(application_id=app.id, kind="custom", custom_label="note")
    )
    save_application_event(
        session,
        ApplicationEvent(application_id=app.id, kind="recruiter_screen", occurred_at=_at(3)),
    )
    kinds = [e.kind for e in events_for_application(session, app.id)]
    assert kinds == ["recruiter_screen", "custom"]


def test_next_sequence_counts_only_the_same_kind():
    session, app = _app()
    save_application_event(
        session,
        ApplicationEvent(application_id=app.id, kind="technical_round", occurred_at=_at(3)),
    )
    save_application_event(
        session, ApplicationEvent(application_id=app.id, kind="behavioral", occurred_at=_at(4))
    )
    assert next_sequence(session, app.id, "technical_round") == 2
    assert next_sequence(session, app.id, "behavioral") == 2
    assert next_sequence(session, app.id, "system_design") == 1


def test_delete_returns_false_for_unknown_id():
    session, app = _app()
    assert delete_application_event(session, 999) is False


def test_delete_removes_the_row():
    session, app = _app()
    event = save_application_event(
        session, ApplicationEvent(application_id=app.id, kind="behavioral", occurred_at=_at(3))
    )
    assert delete_application_event(session, event.id) is True
    assert get_application_event(session, event.id) is None
    assert events_for_application(session, app.id) == []


def test_events_are_scoped_to_one_application():
    session, app = _app()
    other = Application(job_id=app.job_id)
    session.add(other)
    session.commit()
    session.refresh(other)
    save_application_event(
        session, ApplicationEvent(application_id=other.id, kind="behavioral", occurred_at=_at(3))
    )
    assert events_for_application(session, app.id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_repository.py -v`
Expected: FAIL — `ImportError: cannot import name 'events_for_application'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/tracking/repository.py`:

```python
def events_for_application(session: Session, application_id: int) -> list[ApplicationEvent]:
    """Timeline order: by date ascending, undated last, then by creation."""
    occurred = cast(Any, ApplicationEvent.occurred_at)
    return list(
        session.exec(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(
                occurred.is_(None),  # False (0) sorts before True (1)
                occurred.asc(),
                cast(Any, ApplicationEvent.created_at).asc(),
            )
        ).all()
    )


def get_application_event(session: Session, event_id: int) -> ApplicationEvent | None:
    return session.get(ApplicationEvent, event_id)


def save_application_event(
    session: Session, event: ApplicationEvent
) -> ApplicationEvent:
    event.updated_at = utcnow()
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def delete_application_event(session: Session, event_id: int) -> bool:
    event = session.get(ApplicationEvent, event_id)
    if event is None:
        return False
    session.delete(event)
    session.commit()
    return True


def next_sequence(session: Session, application_id: int, kind: str) -> int:
    existing = session.exec(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.kind == kind,
        )
    ).all()
    return len(existing) + 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_repository.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking/repository.py tests/test_application_event_repository.py
git add src/resume_agent/tracking/repository.py tests/test_application_event_repository.py
git commit -m "feat(tracking): application event repository CRUD"
```

---

### Task 6: Event service — validation, sequencing, status advancement

**Files:**
- Create: `src/resume_agent/services/application_events.py`
- Test: `tests/test_application_events_service.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 3, 5.
- Produces:
  - `class EventValidationError(Exception)` with a `.message: str`
  - `create_event(session, job_id, payload: dict) -> ApplicationEvent`
  - `update_event(session, job_id, event_id, payload: dict) -> ApplicationEvent | None`
  - `delete_event(session, job_id, event_id) -> bool`
  - `list_events(session, job_id) -> list[ApplicationEvent]`

`create_event` creates the `Application` row if absent (mirroring `select_resume_version`'s `or Application(job_id=job_id)` idiom), assigns `sequence` when the payload omits it, and advances status.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_application_events_service.py
from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.application_events import (
    EventValidationError,
    create_event,
    delete_event,
    list_events,
    update_event,
)
from resume_agent.tracking.queries import application_for_job
from resume_agent.tracking.tables import Job


def _job():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    return session, job


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def test_create_makes_the_application_row_when_absent():
    session, job = _job()
    create_event(session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)})
    assert application_for_job(session, job.id) is not None


def test_create_advances_status_through_the_progression():
    session, job = _job()
    create_event(session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)})
    assert application_for_job(session, job.id).status == "submitted"
    create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(9)})
    assert application_for_job(session, job.id).status == "interview"


def test_a_late_logged_earlier_stage_never_demotes():
    session, job = _job()
    create_event(session, job.id, {"kind": "offer_received", "occurred_at": _at(20)})
    create_event(session, job.id, {"kind": "recruiter_screen", "occurred_at": _at(3)})
    assert application_for_job(session, job.id).status == "offer"


def test_rejected_event_is_terminal_even_from_offer():
    session, job = _job()
    create_event(session, job.id, {"kind": "offer_received", "occurred_at": _at(20)})
    create_event(session, job.id, {"kind": "rejected", "occurred_at": _at(22)})
    assert application_for_job(session, job.id).status == "rejected"


def test_result_rejected_on_a_round_does_not_kill_the_application():
    session, job = _job()
    create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "result": "rejected"},
    )
    assert application_for_job(session, job.id).status == "interview"


def test_custom_events_never_move_status():
    session, job = _job()
    create_event(session, job.id, {"kind": "custom", "custom_label": "sent thank-you"})
    assert application_for_job(session, job.id).status == "ready"


def test_sequence_auto_increments_per_kind():
    session, job = _job()
    first = create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(9)})
    second = create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(11)})
    assert (first.sequence, second.sequence) == (1, 2)


def test_explicit_sequence_overrides_auto_assignment():
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9), "sequence": 3}
    )
    assert event.sequence == 3


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"kind": "not_a_kind", "occurred_at": _at(3)}, "kind"),
        ({"kind": "technical_round"}, "occurred_at"),
        ({"kind": "custom"}, "custom_label"),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "platform": "other"},
            "platform_other",
        ),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "modality": "teleport"},
            "modality",
        ),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "result": "vibes"},
            "result",
        ),
    ],
)
def test_validation_rejects_bad_payloads(payload, fragment):
    session, job = _job()
    with pytest.raises(EventValidationError) as excinfo:
        create_event(session, job.id, payload)
    assert fragment in str(excinfo.value)


def test_custom_events_may_omit_a_date():
    session, job = _job()
    event = create_event(session, job.id, {"kind": "custom", "custom_label": "referral ping"})
    assert event.occurred_at is None


def test_update_changes_fields_and_can_advance_status():
    session, job = _job()
    event = create_event(session, job.id, {"kind": "recruiter_screen", "occurred_at": _at(3)})
    updated = update_event(
        session, job.id, event.id, {"kind": "offer_received", "occurred_at": _at(20)}
    )
    assert updated.kind == "offer_received"
    assert application_for_job(session, job.id).status == "offer"


def test_update_returns_none_for_an_event_on_another_job():
    session, job = _job()
    other = Job(source="test")
    session.add(other)
    session.commit()
    session.refresh(other)
    event = create_event(session, other.id, {"kind": "behavioral", "occurred_at": _at(3)})
    assert update_event(session, job.id, event.id, {"notes": "x"}) is None


def test_delete_does_not_move_status_back():
    session, job = _job()
    event = create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(9)})
    assert delete_event(session, job.id, event.id) is True
    assert application_for_job(session, job.id).status == "interview"


def test_list_events_returns_timeline_order():
    session, job = _job()
    create_event(session, job.id, {"kind": "online_assessment", "occurred_at": _at(9)})
    create_event(session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)})
    assert [e.kind for e in list_events(session, job.id)] == [
        "application_submitted",
        "online_assessment",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_events_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.application_events'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/services/application_events.py
"""Application timeline events: validate, sequence, persist, advance status.

Validation is deliberately thin. The real funnel is not a clean sequence —
candidates are referred straight to onsites, recruiters skip the OA, companies
reorder loops — so ordering is never enforced. A tracker that argues about
what happened is worse than useless. Only vocabulary and required-field
conditions are checked.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from resume_agent.tracking.event_vocab import (
    KIND_IMPLIES_STATUS,
    EventKind,
    EventResult,
    Modality,
    Platform,
)
from resume_agent.tracking.queries import application_for_job
from resume_agent.tracking.repository import (
    delete_application_event,
    events_for_application,
    get_application_event,
    next_sequence,
    save_application,
    save_application_event,
)
from resume_agent.tracking.status_rules import advance_application_status
from resume_agent.tracking.tables import Application, ApplicationEvent

_WRITABLE = {
    "kind", "custom_label", "sequence", "occurred_at", "all_day", "timezone",
    "duration_minutes", "modality", "platform", "platform_other",
    "location_or_link", "interviewers", "result", "notes", "reflection",
    "comp_base", "comp_bonus", "comp_equity_annual", "comp_signing",
    "comp_currency", "source",
}


class EventValidationError(Exception):
    """A payload the vocabulary or required-field rules reject."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate(payload: dict[str, Any]) -> None:
    kind = payload.get("kind")
    if kind not in {k.value for k in EventKind}:
        raise EventValidationError(f"Unknown event kind '{kind}'")
    if kind == EventKind.custom.value:
        if not (payload.get("custom_label") or "").strip():
            raise EventValidationError("custom_label is required when kind is 'custom'")
    elif payload.get("occurred_at") is None:
        raise EventValidationError(f"occurred_at is required for kind '{kind}'")

    platform = payload.get("platform")
    if platform is not None and platform not in {p.value for p in Platform}:
        raise EventValidationError(f"Unknown platform '{platform}'")
    if platform == Platform.other.value and not (payload.get("platform_other") or "").strip():
        raise EventValidationError("platform_other is required when platform is 'other'")

    modality = payload.get("modality")
    if modality is not None and modality not in {m.value for m in Modality}:
        raise EventValidationError(f"Unknown modality '{modality}'")

    result = payload.get("result")
    if result is not None and result not in {r.value for r in EventResult}:
        raise EventValidationError(f"Unknown result '{result}'")


def _application(session: Session, job_id: int) -> Application:
    existing = application_for_job(session, job_id)
    if existing is not None:
        return existing
    return save_application(session, Application(job_id=job_id))


def _advance(session: Session, application: Application, kind: str) -> None:
    implied = KIND_IMPLIES_STATUS.get(kind)
    if implied is None:
        return  # `custom` says nothing about the funnel
    moved = advance_application_status(application.status, implied)
    if moved != application.status:
        application.status = moved
        save_application(session, application)


def create_event(session: Session, job_id: int, payload: dict[str, Any]) -> ApplicationEvent:
    _validate(payload)
    application = _application(session, job_id)
    fields = {k: v for k, v in payload.items() if k in _WRITABLE}
    kind = fields["kind"]
    fields.setdefault("sequence", next_sequence(session, application.id, kind))
    event = save_application_event(
        session, ApplicationEvent(application_id=application.id, **fields)
    )
    _advance(session, application, kind)
    return event


def update_event(
    session: Session, job_id: int, event_id: int, payload: dict[str, Any]
) -> ApplicationEvent | None:
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if application is None or event is None or event.application_id != application.id:
        return None
    merged = {field: getattr(event, field) for field in _WRITABLE}
    merged.update({k: v for k, v in payload.items() if k in _WRITABLE})
    _validate(merged)
    for field, value in merged.items():
        setattr(event, field, value)
    saved = save_application_event(session, event)
    _advance(session, application, saved.kind)
    return saved


def delete_event(session: Session, job_id: int, event_id: int) -> bool:
    """Delete an event. Status is never moved back — progression is forward-only."""
    application = application_for_job(session, job_id)
    event = get_application_event(session, event_id)
    if application is None or event is None or event.application_id != application.id:
        return False
    return delete_application_event(session, event_id)


def list_events(session: Session, job_id: int) -> list[ApplicationEvent]:
    application = application_for_job(session, job_id)
    return [] if application is None else events_for_application(session, application.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_events_service.py -v`
Expected: PASS (19 tests including parametrized cases)

If `save_application` or `application_for_job` is not importable from the module shown, locate the real one with `grep -rn "def save_application\b\|def application_for_job" src/resume_agent/tracking/` and import from there.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/services/application_events.py tests/test_application_events_service.py
git add src/resume_agent/services/application_events.py tests/test_application_events_service.py
git commit -m "feat(services): application event validation, sequencing, status advancement"
```

---

### Task 7: Backfill migration for existing `submitted_at`

**Files:**
- Modify: `src/resume_agent/tracking/migrate.py` (append)
- Modify: `src/resume_agent/db.py:88-107` (`init_db`, after the existing `ensure_*` calls)
- Test: `tests/test_application_event_migration.py`

**Interfaces:**
- Consumes: Task 2's table.
- Produces: `ensure_application_submitted_events(engine: Engine) -> None`.

**Note:** no table-creation migration is needed. `init_db` calls `SQLModel.metadata.create_all(engine)` first, which creates the table and its indexes. `ensure_*` functions exist only for `ALTER`-shaped changes to tables already present in deployed databases.

Status is deliberately **not** backfilled into synthetic events: an `interview` status implies an interview happened but carries no date, and an undated synthetic event corrupts exactly the cycle-time numbers Phase 3 exists to produce.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_application_event_migration.py
from datetime import datetime, timezone

from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.migrate import ensure_application_submitted_events
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _seed(submitted_at):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = Job(source="test", company="Acme")
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(
            Application(job_id=job.id, status="submitted", submitted_at=submitted_at)
        )
        session.commit()
    return engine


def test_backfills_one_event_per_submitted_application():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        events = session.exec(select(ApplicationEvent)).all()
    assert len(events) == 1
    assert events[0].kind == "application_submitted"
    assert events[0].all_day is True
    assert events[0].result == "advanced"
    assert events[0].source == "migration"


def test_is_idempotent():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    ensure_application_submitted_events(engine)
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert len(session.exec(select(ApplicationEvent)).all()) == 1


def test_skips_applications_with_no_submitted_at():
    engine = _seed(None)
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert session.exec(select(ApplicationEvent)).all() == []


def test_does_not_synthesize_events_from_status_alone():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = Job(source="test")
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(Application(job_id=job.id, status="interview", submitted_at=None))
        session.commit()
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert session.exec(select(ApplicationEvent)).all() == []


def test_init_db_runs_the_backfill():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    init_db(engine)  # second call must backfill and stay idempotent
    with Session(engine) as session:
        assert len(session.exec(select(ApplicationEvent)).all()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_migration.py -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_application_submitted_events'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/tracking/migrate.py`:

```python
def ensure_application_submitted_events(engine: Engine) -> None:
    """Turn each Application.submitted_at into a real timeline event.

    Every submitted application already carries one true, unambiguous date;
    dropping it would make the first cycle-time chart wrong for no reason.
    Status is NOT backfilled: an `interview` status implies an interview
    happened but carries no date, and an undated synthetic event corrupts the
    very numbers the timeline exists to produce. `source="migration"` keeps
    backfilled rows distinguishable forever.
    """
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        if not {"applications", "application_events"}.issubset(tables):
            return
        rows = conn.execute(
            text(
                "SELECT a.id, a.submitted_at FROM applications a "
                "WHERE a.submitted_at IS NOT NULL AND NOT EXISTS ("
                "  SELECT 1 FROM application_events e "
                "  WHERE e.application_id = a.id "
                "    AND e.kind = 'application_submitted')"
            )
        ).fetchall()
        for application_id, submitted_at in rows:
            conn.execute(
                text(
                    "INSERT INTO application_events ("
                    "  application_id, kind, sequence, occurred_at, all_day, "
                    "  result, source, schema_version, created_at, updated_at"
                    ") VALUES ("
                    "  :application_id, 'application_submitted', 1, :occurred_at, 1, "
                    "  'advanced', 'migration', 1, :now, :now)"
                ),
                {
                    "application_id": application_id,
                    "occurred_at": submitted_at,
                    "now": utcnow(),
                },
            )
```

Add `from resume_agent.tracking.tables import utcnow` to `migrate.py`'s imports if absent. Then register the call at the end of `init_db` in `src/resume_agent/db.py`, after `ensure_url_index(engine)`, and add the import to the `migrate` import block.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_application_event_migration.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking/migrate.py src/resume_agent/db.py
git add src/resume_agent/tracking/migrate.py src/resume_agent/db.py tests/test_application_event_migration.py
git commit -m "feat(tracking): backfill application_submitted events from submitted_at"
```

---

### Task 8: API schemas and routes

**Files:**
- Create: `src/resume_agent/api/schemas/application_events.py`
- Create: `src/resume_agent/api/routers/application_events.py`
- Modify: `src/resume_agent/api/app.py` (import + `include_router` beside `jobs_router`, ~line 345)
- Test: `tests/api/test_application_events.py`

**Interfaces:**
- Consumes: Task 6's service.
- Produces: routes `GET|POST /api/jobs/{job_id}/events`, `PATCH|DELETE /api/jobs/{job_id}/events/{event_id}`; schemas `ApplicationEventOut`, `ApplicationEventCreate`, `ApplicationEventUpdate`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_application_events.py
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _job(client):
    resp = client.post(
        "/api/jobs",
        json={"jdText": "Build things.", "company": "Acme", "title": "SWE"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_create_and_list_events():
    client = _client()
    with client:
        job_id = _job(client)
        created = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "technical_round",
                "occurredAt": "2026-03-09T19:00:00Z",
                "timezone": "America/New_York",
                "durationMinutes": 60,
                "modality": "virtual",
                "platform": "zoom",
                "locationOrLink": "https://zoom.us/j/123",
                "interviewers": "Dana Vale",
                "notes": "LRU cache",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["kind"] == "technical_round"
        assert body["sequence"] == 1
        assert body["result"] == "pending"
        assert body["platform"] == "zoom"

        listed = client.get(f"/api/jobs/{job_id}/events")
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_create_advances_application_status():
    client = _client()
    with client:
        job_id = _job(client)
        client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "application_submitted", "occurredAt": "2026-03-03T12:00:00Z"},
        )
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["application"]["status"] == "submitted"


def test_unknown_kind_is_422_with_validation_error_code():
    client = _client()
    with client:
        job_id = _job(client)
        resp = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "vibe_check", "occurredAt": "2026-03-03T12:00:00Z"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_date_on_a_dated_kind_is_422():
    client = _client()
    with client:
        job_id = _job(client)
        resp = client.post(f"/api/jobs/{job_id}/events", json={"kind": "behavioral"})
        assert resp.status_code == 422


def test_custom_event_without_a_label_is_422():
    client = _client()
    with client:
        job_id = _job(client)
        resp = client.post(f"/api/jobs/{job_id}/events", json={"kind": "custom"})
        assert resp.status_code == 422


def test_events_on_a_missing_job_are_404():
    client = _client()
    with client:
        resp = client.get("/api/jobs/9999/events")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_patch_updates_and_delete_removes():
    client = _client()
    with client:
        job_id = _job(client)
        event_id = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "behavioral", "occurredAt": "2026-03-09T19:00:00Z"},
        ).json()["id"]

        patched = client.patch(
            f"/api/jobs/{job_id}/events/{event_id}",
            json={"result": "advanced", "reflection": "clarified constraints early"},
        )
        assert patched.status_code == 200
        assert patched.json()["result"] == "advanced"
        assert patched.json()["reflection"] == "clarified constraints early"

        assert client.delete(f"/api/jobs/{job_id}/events/{event_id}").status_code == 204
        assert client.get(f"/api/jobs/{job_id}/events").json() == []


def test_patch_on_a_missing_event_is_404():
    client = _client()
    with client:
        job_id = _job(client)
        resp = client.patch(f"/api/jobs/{job_id}/events/999", json={"notes": "x"})
        assert resp.status_code == 404


def test_offer_event_carries_structured_comp():
    client = _client()
    with client:
        job_id = _job(client)
        body = client.post(
            f"/api/jobs/{job_id}/events",
            json={
                "kind": "offer_received",
                "occurredAt": "2026-03-20T12:00:00Z",
                "compBase": 180000,
                "compBonus": 27000,
                "compEquityAnnual": 60000,
                "compSigning": 25000,
                "compCurrency": "USD",
            },
        ).json()
        assert body["compBase"] == 180000
        assert body["totalComp"] == 292000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_application_events.py -v`
Expected: FAIL — 404 on every route (router not registered).

- [ ] **Step 3: Write the schemas**

```python
# src/resume_agent/api/schemas/application_events.py
"""Application timeline event schemas. Total comp is derived, never stored."""

from __future__ import annotations

from datetime import datetime

from pydantic import computed_field

from resume_agent.api.schemas.base import CamelModel


class ApplicationEventOut(CamelModel):
    id: int
    application_id: int
    kind: str
    custom_label: str | None = None
    sequence: int
    occurred_at: datetime | None = None
    all_day: bool
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None
    source: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def total_comp(self) -> int | None:
        """Sum of the components, or None when no component was recorded.

        Derived rather than stored: offers are quoted as components, and
        collapsing them at entry destroys information that cannot be recovered.
        """
        parts = [
            self.comp_base,
            self.comp_bonus,
            self.comp_equity_annual,
            self.comp_signing,
        ]
        present = [p for p in parts if p is not None]
        return sum(present) if present else None


class ApplicationEventCreate(CamelModel):
    kind: str
    custom_label: str | None = None
    sequence: int | None = None
    occurred_at: datetime | None = None
    all_day: bool = False
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str = "pending"
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None


class ApplicationEventUpdate(CamelModel):
    """Every field optional; omitted fields keep their stored value."""

    kind: str | None = None
    custom_label: str | None = None
    sequence: int | None = None
    occurred_at: datetime | None = None
    all_day: bool | None = None
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str | None = None
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None
```

- [ ] **Step 4: Write the router**

```python
# src/resume_agent/api/routers/application_events.py
"""Application timeline event CRUD, nested under the job like /application."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.application_events import (
    ApplicationEventCreate,
    ApplicationEventOut,
    ApplicationEventUpdate,
)
from resume_agent.services.application_events import (
    EventValidationError,
    create_event,
    delete_event,
    list_events,
    update_event,
)
from resume_agent.tracking.repository import get_job

router = APIRouter()


def _require_job(session: Session, job_id: int) -> None:
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")


@router.get("/jobs/{job_id}/events", response_model=list[ApplicationEventOut])
def get_events(job_id: int, session: Session = Depends(get_session)):
    _require_job(session, job_id)
    return [ApplicationEventOut.model_validate(e) for e in list_events(session, job_id)]


@router.post("/jobs/{job_id}/events", response_model=ApplicationEventOut, status_code=201)
def post_event(
    job_id: int,
    body: ApplicationEventCreate,
    session: Session = Depends(get_session),
):
    _require_job(session, job_id)
    payload = body.model_dump(exclude_none=True)
    try:
        event = create_event(session, job_id, payload)
    except EventValidationError as error:
        raise ApiException(422, "VALIDATION_ERROR", error.message) from error
    return ApplicationEventOut.model_validate(event)


@router.patch("/jobs/{job_id}/events/{event_id}", response_model=ApplicationEventOut)
def patch_event(
    job_id: int,
    event_id: int,
    body: ApplicationEventUpdate,
    session: Session = Depends(get_session),
):
    _require_job(session, job_id)
    payload = body.model_dump(exclude_unset=True)
    try:
        event = update_event(session, job_id, event_id, payload)
    except EventValidationError as error:
        raise ApiException(422, "VALIDATION_ERROR", error.message) from error
    if event is None:
        raise ApiException(404, "NOT_FOUND", f"Event #{event_id} not found")
    return ApplicationEventOut.model_validate(event)


@router.delete("/jobs/{job_id}/events/{event_id}", status_code=204)
def remove_event(job_id: int, event_id: int, session: Session = Depends(get_session)):
    _require_job(session, job_id)
    if not delete_event(session, job_id, event_id):
        raise ApiException(404, "NOT_FOUND", f"Event #{event_id} not found")
    return Response(status_code=204)
```

Register it in `src/resume_agent/api/app.py`: add the import beside the other router imports, then next to line 345's `jobs_router` registration add:

```python
    app.include_router(
        application_events_router.router, prefix="/api", dependencies=guarded
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_application_events.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Regenerate the contract**

```bash
make openapi && make client
```

Expected: `contracts/openapi.json`, `contracts/ts/api.ts`, and `web/src/lib/api/schema.ts` all updated with the four new paths.

- [ ] **Step 7: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/api/ tests/api/test_application_events.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(api): application timeline event CRUD routes"
```

---

### Task 9: Web — query and mutation hooks

**Files:**
- Create: `web/src/features/job/use-application-events.ts`
- Test: `web/src/features/job/use-application-events.test.tsx`

**Interfaces:**
- Consumes: Task 8's routes and the regenerated `schema.ts`.
- Produces:
  - `type ApplicationEvent = components["schemas"]["ApplicationEventOut"]`
  - `useApplicationEvents(jobId: number)` → TanStack query, key `["job-events", jobId]`
  - `useCreateEvent(jobId: number)`, `useUpdateEvent(jobId: number)`, `useDeleteEvent(jobId: number)`

All mutations invalidate both `["job-events", jobId]` and `["job", jobId]` — creating an event can change `application.status`, which the job detail query holds.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/use-application-events.test.tsx
import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { useApplicationEvents } from "./use-application-events";

const server = setupServer(
  http.get("/api/jobs/42/events", () =>
    HttpResponse.json([
      {
        id: 1,
        applicationId: 7,
        kind: "technical_round",
        sequence: 1,
        occurredAt: "2026-03-09T19:00:00Z",
        allDay: false,
        result: "pending",
        source: "manual",
        createdAt: "2026-03-01T00:00:00Z",
        updatedAt: "2026-03-01T00:00:00Z",
        totalComp: null,
      },
    ]),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

describe("useApplicationEvents", () => {
  it("loads the timeline for a job", async () => {
    const { result } = renderHook(() => useApplicationEvents(42), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].kind).toBe("technical_round");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- use-application-events`
Expected: FAIL — cannot resolve `./use-application-events`.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/src/features/job/use-application-events.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ApplicationEvent = components["schemas"]["ApplicationEventOut"];
export type ApplicationEventCreate = components["schemas"]["ApplicationEventCreate"];
export type ApplicationEventUpdate = components["schemas"]["ApplicationEventUpdate"];

export const eventsKey = (jobId: number) => ["job-events", jobId] as const;

export function useApplicationEvents(jobId: number) {
  return useQuery({
    queryKey: eventsKey(jobId),
    queryFn: () =>
      unwrap(api.GET("/api/jobs/{job_id}/events", { params: { path: { job_id: jobId } } })),
  });
}

/** Events can move `application.status`, so the job detail query is stale too. */
function useInvalidate(jobId: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: eventsKey(jobId) });
    qc.invalidateQueries({ queryKey: ["job", jobId] });
  };
}

export function useCreateEvent(jobId: number) {
  const invalidate = useInvalidate(jobId);
  return useMutation({
    mutationFn: (body: ApplicationEventCreate) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/events", {
          params: { path: { job_id: jobId } },
          body,
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event added");
    },
    onError: () => toast.error("Failed to add event"),
  });
}

export function useUpdateEvent(jobId: number) {
  const invalidate = useInvalidate(jobId);
  return useMutation({
    mutationFn: (vars: { eventId: number; body: ApplicationEventUpdate }) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}/events/{event_id}", {
          params: { path: { job_id: jobId, event_id: vars.eventId } },
          body: vars.body,
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event updated");
    },
    onError: () => toast.error("Failed to update event"),
  });
}

export function useDeleteEvent(jobId: number) {
  const invalidate = useInvalidate(jobId);
  return useMutation({
    mutationFn: (eventId: number) =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}/events/{event_id}", {
          params: { path: { job_id: jobId, event_id: eventId } },
        }),
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Event removed");
    },
    onError: () => toast.error("Failed to remove event"),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- use-application-events`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/job/use-application-events.ts web/src/features/job/use-application-events.test.tsx
git commit -m "feat(web): application event query and mutation hooks"
```

---

### Task 10: Web — event form dialog

**Files:**
- Create: `web/src/features/job/EventFormDialog.tsx`
- Test: `web/src/features/job/EventFormDialog.test.tsx`

**Interfaces:**
- Consumes: Task 9's types.
- Produces: `<EventFormDialog trigger={ReactNode} event?={ApplicationEvent} onSubmit={(body) => void} />`, plus exported `KIND_LABELS`, `PLATFORM_LABELS`, `MODALITY_LABELS`, `RESULT_LABELS` record maps that `EventRow` (Task 11) reuses.

**Reminder:** per the codebase's known Base UI bug, a bare `<SelectValue />` renders the raw value until the dropdown is opened once. Always pass a children resolver function that maps the value to its label.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/EventFormDialog.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EventFormDialog } from "./EventFormDialog";

describe("EventFormDialog", () => {
  it("submits a minimal dated event", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Add event" }));
    await user.type(screen.getByLabelText(/date/i), "2026-03-09");
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const body = onSubmit.mock.calls[0][0];
    expect(body.kind).toBe("application_submitted");
    expect(body.occurredAt).toContain("2026-03-09");
  });

  it("requires a label when kind is custom", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Add event" }));
    await user.selectOptions(screen.getByLabelText(/stage/i), "custom");
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/label is required/i)).toBeInTheDocument();
  });

  it("shows compensation fields only for an offer", async () => {
    const user = userEvent.setup();
    render(<EventFormDialog trigger={<button>Add event</button>} onSubmit={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Add event" }));
    expect(screen.queryByLabelText(/base salary/i)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/stage/i), "offer_received");
    expect(screen.getByLabelText(/base salary/i)).toBeInTheDocument();
  });

  it("prefills from an existing event when editing", async () => {
    const user = userEvent.setup();
    render(
      <EventFormDialog
        trigger={<button>Edit</button>}
        event={
          {
            id: 1,
            kind: "technical_round",
            notes: "LRU cache",
            occurredAt: "2026-03-09T19:00:00Z",
            allDay: false,
          } as never
        }
        onSubmit={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText(/notes/i)).toHaveValue("LRU cache");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- EventFormDialog`
Expected: FAIL — cannot resolve `./EventFormDialog`.

- [ ] **Step 3: Write minimal implementation**

Build the dialog with the project's existing primitives: `Dialog` from `@/components/ui/dialog`, `Input`, `Label`, `Textarea`, `Button`. Use a **native `<select>`** for the stage/platform/modality/result pickers in this component — the test drives them with `selectOptions`, and a native select sidesteps the Base UI `SelectValue` label bug entirely for a form this dense.

Requirements the tests pin:

- Default `kind` is `application_submitted`.
- A `<label>`-associated date input named "Date"; when `allDay` is unchecked, also a time input. Serialize to an ISO-8601 UTC string in `occurredAt`, setting `allDay: true` when no time was given.
- `custom` kind reveals a "Label" input and blocks submit with the message "Label is required" when blank.
- `offer_received` reveals `compBase` / `compBonus` / `compEquityAnnual` / `compSigning` / `compCurrency`, labelled "Base salary", "Annual bonus", "Equity per year", "Signing bonus", "Currency".
- `platform === "other"` reveals a "Platform name" input.
- Always present: Modality, Platform, Duration (minutes), Location or link, Interviewers, Result, Notes (textarea), Reflection (textarea).
- `timezone` defaults to `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- When `event` is supplied, prefill every field from it and label the submit button "Save".

Export the four label maps for `EventRow`:

```ts
export const KIND_LABELS: Record<string, string> = {
  application_submitted: "Application submitted",
  recruiter_screen: "Recruiter screen",
  online_assessment: "Online assessment",
  questionnaire: "Questionnaire",
  technical_phone_screen: "Technical phone screen",
  technical_round: "Technical round",
  system_design: "System design",
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager",
  onsite_loop: "Onsite loop",
  team_match: "Team match",
  offer_received: "Offer received",
  offer_deadline: "Offer deadline",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  custom: "Other",
};

export const PLATFORM_LABELS: Record<string, string> = {
  zoom: "Zoom",
  teams: "Microsoft Teams",
  google_meet: "Google Meet",
  webex: "Webex",
  tencent_meeting: "Tencent Meeting",
  feishu: "Feishu",
  phone: "Phone",
  hackerrank: "HackerRank",
  codesignal: "CodeSignal",
  coderpad: "CoderPad",
  karat: "Karat",
  other: "Other",
};

export const MODALITY_LABELS: Record<string, string> = {
  onsite: "Onsite",
  virtual: "Virtual",
  phone: "Phone",
  async: "Async",
};

export const RESULT_LABELS: Record<string, string> = {
  pending: "Pending",
  advanced: "Advanced",
  rejected: "Rejected",
  no_response: "No response",
  cancelled: "Cancelled",
  withdrew: "Withdrew",
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- EventFormDialog`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/job/EventFormDialog.tsx web/src/features/job/EventFormDialog.test.tsx
git commit -m "feat(web): application event form dialog"
```

---

### Task 11: Web — event row and timeline list

**Files:**
- Create: `web/src/features/job/EventRow.tsx`
- Create: `web/src/features/job/ApplicationTimeline.tsx`
- Test: `web/src/features/job/ApplicationTimeline.test.tsx`

**Interfaces:**
- Consumes: Tasks 9 and 10.
- Produces: `<EventRow event={ApplicationEvent} jobId={number} />`; `<ApplicationTimeline jobId={number} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/ApplicationTimeline.test.tsx
import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  events: [] as unknown[],
  isLoading: false,
}));

vi.mock("./use-application-events", () => ({
  useApplicationEvents: () => ({ data: mocks.events, isLoading: mocks.isLoading }),
  useCreateEvent: () => ({ mutate: vi.fn() }),
  useUpdateEvent: () => ({ mutate: vi.fn() }),
  useDeleteEvent: () => ({ mutate: vi.fn() }),
}));

import { ApplicationTimeline } from "./ApplicationTimeline";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );
}

const event = (over: Record<string, unknown> = {}) => ({
  id: 1,
  applicationId: 7,
  kind: "technical_round",
  sequence: 2,
  occurredAt: "2026-03-09T19:00:00Z",
  allDay: false,
  result: "pending",
  source: "manual",
  platform: "zoom",
  modality: "virtual",
  createdAt: "2026-03-01T00:00:00Z",
  updatedAt: "2026-03-01T00:00:00Z",
  totalComp: null,
  ...over,
});

describe("ApplicationTimeline", () => {
  it("shows an empty state with an add affordance", () => {
    mocks.events = [];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText(/no events yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add event/i })).toBeInTheDocument();
  });

  it("renders a human label with the round number and platform", () => {
    mocks.events = [event()];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText("Technical round 2")).toBeInTheDocument();
    expect(screen.getByText(/Zoom/)).toBeInTheDocument();
  });

  it("omits the sequence number for non-repeatable kinds", () => {
    mocks.events = [event({ kind: "behavioral", sequence: 1 })];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText("Behavioral")).toBeInTheDocument();
  });

  it("marks a future event as upcoming", () => {
    const future = new Date(Date.now() + 86_400_000).toISOString();
    mocks.events = [event({ occurredAt: future })];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText(/upcoming/i)).toBeInTheDocument();
  });

  it("shows the custom label for a custom event", () => {
    mocks.events = [
      event({ kind: "custom", customLabel: "Referral ping", occurredAt: null }),
    ];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText("Referral ping")).toBeInTheDocument();
  });

  it("shows derived total compensation on an offer", () => {
    mocks.events = [
      event({ kind: "offer_received", totalComp: 292000, compCurrency: "USD" }),
    ];
    render(<ApplicationTimeline jobId={42} />, { wrapper });
    expect(screen.getByText(/292,000/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- ApplicationTimeline`
Expected: FAIL — cannot resolve `./ApplicationTimeline`.

- [ ] **Step 3: Write minimal implementation**

`EventRow.tsx` renders one event:
- Title: `KIND_LABELS[kind]`, suffixed with ` ${sequence}` **only** when `kind` is `technical_round` or `offer_received` (the repeatable kinds). For `custom`, render `customLabel` as the title.
- Date line: `allDay` → date only; otherwise date + time, formatted in the event's `timezone` when present. Undated events show "No date".
- An "Upcoming" badge when `occurredAt` is in the future.
- Meta line: modality, platform (`PLATFORM_LABELS`, or `platformOther` when `platform === "other"`), duration, interviewers — joined with `·`, omitting blanks.
- `locationOrLink` as a link when it parses as a URL, plain text otherwise.
- For `offer_received` with a non-null `totalComp`: render it with `toLocaleString()` and the currency.
- Notes and reflection in a collapsible disclosure, following `EvidencePortfolioDisclosure.tsx`'s pattern.
- Edit (opens `EventFormDialog` with `event` prefilled, wired to `useUpdateEvent`) and Delete (wrapped in `ConfirmDialog`, wired to `useDeleteEvent`).

`ApplicationTimeline.tsx`:
- Calls `useApplicationEvents(jobId)`, renders `<Spinner />` while loading.
- Empty state: "No events yet." plus the add button.
- Otherwise an ordered list of `<EventRow />` (the API already returns timeline order — do not re-sort).
- An "Add event" `EventFormDialog` wired to `useCreateEvent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- ApplicationTimeline`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/job/EventRow.tsx web/src/features/job/ApplicationTimeline.tsx web/src/features/job/ApplicationTimeline.test.tsx
git commit -m "feat(web): application timeline list and event row"
```

---

### Task 12: Web — restructure `ApplicationEditor` around the timeline

**Files:**
- Modify: `web/src/features/job/ApplicationEditor.tsx` (full rewrite, ~58 lines today)
- Modify: `web/src/features/job/TrackingTab.tsx:41` (section heading copy only)
- Test: `web/src/features/job/ApplicationEditor.test.tsx` (create)

**Interfaces:**
- Consumes: Tasks 9 and 11.
- Produces: `<ApplicationEditor jobId={number} application={ApplicationOut | null} />` — signature unchanged, so `TrackingTab` needs no prop changes.

**Design:** status becomes a *header* over the timeline, not a peer widget. Keeping the old dropdown beside a new timeline would leave two widgets showing overlapping truth with no stated precedence. The single-line notes `<Input>` becomes a `<Textarea>` — it has been quietly wrong since it shipped.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/ApplicationEditor.test.tsx
import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ upsert: vi.fn() }));

vi.mock("./use-job-mutations", () => ({
  useUpsertApplication: () => ({ mutate: mocks.upsert }),
}));
vi.mock("./ApplicationTimeline", () => ({
  ApplicationTimeline: ({ jobId }: { jobId: number }) => (
    <div data-testid="timeline">timeline for {jobId}</div>
  ),
}));

import { ApplicationEditor } from "./ApplicationEditor";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );
}

const application = {
  id: 7,
  jobId: 42,
  status: "interview",
  notes: "applied via referral",
} as never;

describe("ApplicationEditor", () => {
  beforeEach(() => mocks.upsert.mockReset());

  it("shows the current status as a header and hosts the timeline", () => {
    render(<ApplicationEditor jobId={42} application={application} />, { wrapper });
    expect(screen.getByText("Interview")).toBeInTheDocument();
    expect(screen.getByTestId("timeline")).toBeInTheDocument();
  });

  it("shows ready when there is no application yet", () => {
    render(<ApplicationEditor jobId={42} application={null} />, { wrapper });
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("does not show the status override until it is requested", async () => {
    const user = userEvent.setup();
    render(<ApplicationEditor jobId={42} application={application} />, { wrapper });
    expect(screen.queryByLabelText(/override status/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /override/i }));
    expect(screen.getByLabelText(/override status/i)).toBeInTheDocument();
  });

  it("saves an overridden status", async () => {
    const user = userEvent.setup();
    render(<ApplicationEditor jobId={42} application={application} />, { wrapper });
    await user.click(screen.getByRole("button", { name: /override/i }));
    await user.selectOptions(screen.getByLabelText(/override status/i), "rejected");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(mocks.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ status: "rejected" }),
    );
  });

  it("renders notes as a multiline textarea", () => {
    render(<ApplicationEditor jobId={42} application={application} />, { wrapper });
    const notes = screen.getByLabelText(/notes/i);
    expect(notes.tagName).toBe("TEXTAREA");
    expect(notes).toHaveValue("applied via referral");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- ApplicationEditor`
Expected: FAIL — the current component renders a Select, not a status header, and notes is an `<input>`.

- [ ] **Step 3: Write minimal implementation**

Rewrite `ApplicationEditor.tsx`:

- Header row: the derived status as a `<Badge>` with a title-cased label (`ready → "Ready"`, `no application → "Ready"`), plus a small "Override" `<Button variant="ghost">`.
- Clicking Override reveals a native `<select>` labelled "Override status" with all six `ApplicationStatus` values, and a "Save" button calling `useUpsertApplication(jobId).mutate({ status, notes })`.
- A `<Textarea>` labelled "Notes" (application-level, distinct from per-event notes), included in the same save.
- Below both, `<ApplicationTimeline jobId={jobId} />`.

Add a `Textarea` import from `@/components/ui/textarea`; if that component does not exist, create it following `input.tsx`'s pattern (same `cn()` + variant conventions, `<textarea>` element, `min-h-16`).

Then in `TrackingTab.tsx:41`, change the section heading from `Application` to `Application & timeline`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- ApplicationEditor`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the whole web suite**

Run: `npm --prefix web run test:run`
Expected: PASS. `TrackingTab.test.tsx` must still pass — if it asserts on the old status Select, update it to assert the new header instead.

- [ ] **Step 6: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/job/
git commit -m "feat(web): restructure ApplicationEditor around the timeline"
```

---

### Task 13: Phase 1 verification and documentation

**Files:**
- Modify: `src/resume_agent/tracking/CLAUDE.md`
- Modify: `CLAUDE.md` (hot-paths table)

- [ ] **Step 1: Run the full verification gate**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
npm --prefix web run lint
npm --prefix web run test:run
npm --prefix web run build
```

Expected: all green. Record the backend and web test counts — the next phase's plan references them as its baseline.

- [ ] **Step 2: Document the subsystem**

Add an "Application timeline" section to `src/resume_agent/tracking/CLAUDE.md` covering:
- Why an event log rather than wide columns (unbounded rounds; the grid is a pivot, not storage).
- The progression-versus-terminal status rule, pointing at ADR-0012 and `status_rules.py`.
- The `has_progress` refinement, pointing at ADR-0013, and the rule that any future `Application` child table must be added to `_application_is_investment` **and** `progressed_job_ids` together.
- Why validation is thin (the real funnel is not a clean sequence).
- That `source="migration"` marks backfilled rows permanently, and that status is deliberately never backfilled into synthetic events.

- [ ] **Step 3: Update the root hot-paths table**

Add to the table in `CLAUDE.md`:

| Path | Role |
| --- | --- |
| `src/resume_agent/tracking/event_vocab.py` | Closed event vocabularies + kind→status mapping + funnel order |
| `src/resume_agent/tracking/status_rules.py` | Progression-vs-terminal application status (ADR-0012) |
| `src/resume_agent/services/application_events.py` | Event validation, sequencing, status advancement |

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/resume_agent/tracking/CLAUDE.md
git commit -m "docs: application timeline subsystem notes"
```

---

## Phase 1 Done When

- `ApplicationEvent` rows persist with the full field set; `create_all` builds the table with no migration.
- Events advance status under progression-versus-terminal; `offer → rejected` works; `result="rejected"` on a round does not.
- An empty `ready` application no longer blocks `delete_job`; one with an event does; `progressed_job_ids` agrees with `has_progress` on identical fixtures.
- Existing `submitted_at` values appear as `application_submitted` events tagged `source="migration"`, idempotently.
- Four CRUD routes work; the contract is regenerated and committed.
- The Tracking tab shows status as a header over a working timeline, with notes as a textarea.
- ADR-0012 and ADR-0013 are written; both CLAUDE.md files are amended.
- `pytest`, `ruff check`, web lint, web tests, and `npm run build` all pass.
