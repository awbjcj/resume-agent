# Application Timeline — Phase 2: The Clock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dated events actionable — reminders that work for every user (not just Gmail-connected ones), `.ics` export so events land in the user's real calendar with alarms, and a dashboard card so an upcoming interview is impossible to miss.

**Architecture:** Reminder generation is lifted out of `run_gmail_sync` into its own hourly scheduler tick that runs for all users. Lead times split by owner: the calendar's `VALARM` handles the ~1-hour lead (native, reliable, on the user's phone), the app handles 24h/48h nudges where a ±1 hour smear is irrelevant. `.ics` is generated on the fly by a hand-rolled serializer — no new dependency.

**Tech Stack:** Python 3.13, FastAPI, asyncio, pytest. React 19 + TypeScript, TanStack Query, vitest.

**Prerequisite:** Phase 1 complete and merged (`docs/superpowers/plans/2026-08-29-application-timeline-phase-1-record.md`).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-29-application-timeline-design.md`. Read the "Reminders" and "Calendar export" sections before Task 1.
- **Tests run offline.** `.venv/Scripts/python.exe -m pytest`. No network, no API key.
- **No new Python or npm dependencies.** The `.ics` writer is hand-rolled: RFC 5545 for the subset used here is a few dozen lines, and `icalendar` would be a new dependency for that.
- **All datetimes stored and compared in UTC.** Use `resume_agent.tracking.tables.utcnow`.
- **Time is always injectable.** Every function that reads the clock takes `now: datetime | None = None`. Tests must never sleep or depend on wall time.
- **`gmail.send` remains permanently out of scope.** This phase must not touch OAuth scopes.
- **No `webcal://` feed.** Per the spec, a feed needs a capability token, revoke path, and rate limit under ADR-0008. Per-event and bulk download only, behind the existing session auth.
- **After any API schema change**, run `make openapi && make client` and commit `contracts/` plus `web/src/lib/api/schema.ts`.

## Correctness amendments (reviewed 2026-08-29)

These amendments are binding and supersede narrower snippets later in the plan.

- Finish and verify Phase 1 Tasks 7–13 before starting this phase. Phase 2 routes
  and UI consume the Phase 1 event API; implementing around a partial Phase 1
  would create a second, incompatible path.
- `render_calendar` accepts an injectable `now`. `DTSTAMP` must never read the
  wall clock internally, and tests assert a fixed stamp rather than comparing
  two timing-sensitive renders.
- A timed event stores UTC in `occurred_at`. When `timezone` is present, convert
  the instant with `zoneinfo.ZoneInfo` before formatting the local wall time;
  attaching a `TZID` to the original UTC clock reading is incorrect. Invalid
  IANA names fail event validation with the normal 422 envelope.
- All-day entries are one-day values unless an explicit exclusive end date is
  provided. Their serializer never adds a second day to an already exclusive
  `end`, and duration minutes do not affect an all-day event.
- The per-event download must load the event through `(job_id, event_id)` (or
  verify its application belongs to the requested job). Looking up only by
  `event_id` permits a cross-job download through a mismatched URL.
- Calendar downloads use the repository's purpose-bound download-link flow
  (`openDownload` plus `download_guarded`), not a plain anchor. Local/token mode
  stores its bearer token in JavaScript and a browser navigation cannot attach
  that Authorization header; claiming a direct `<a>` is universally
  authenticated is incompatible with the existing deployment modes.
- “Upcoming pipeline” means non-terminal applications only. Bulk calendar and
  dashboard queries exclude archived jobs, past/cancelled/withdrawn events, and
  applications in `rejected` or `closed`.
- The production reminder loop runs one pass immediately on startup, then waits
  one hour between passes. In-memory test apps do not start the background loop;
  scheduler tests exercise `run_reminder_pass`/`reminder_tick` directly so app
  startup remains deterministic.
- The `.ics` tests cover multibyte UTF-8 folding, timezone conversion across a
  DST boundary, exclusive all-day `DTEND`, stable `UID`, fixed `DTSTAMP`, and
  event/job ownership. The generated file is also checked as bytes with CRLF
  endings before browser/UI verification.
- Event request datetimes must carry an offset and are normalized to UTC before
  SQLite persistence. The web form edits all-day values as calendar dates and
  timed values in their named IANA timezone; converting either through the
  browser's incidental local timezone is a data-corruption bug.
- Calendar text escaping handles bare CR as well as CRLF/LF, and URI properties
  encode CR/LF so user-controlled locations or links cannot inject new iCalendar
  properties.
- The dashboard's “Next 7 days” dataset is restricted to interview kinds plus
  `offer_deadline`. The bulk calendar deliberately remains broader and includes
  every live upcoming pipeline event.
- The hourly scheduler pushes its time, kind, result, application-status, and
  archive filters into SQL, preloads existing episode keys, and commits new
  notifications as one batch. It must not scan all historical events or perform
  a lookup and commit for every candidate each hour.
- Timed form conversion round-trips the requested wall clock through the named
  timezone. Nonexistent spring-forward times are rejected instead of silently
  moving one hour; ambiguous fall-back times consistently choose the earlier
  occurrence. Both DST boundaries have regression coverage.
- A timed form computes one effective timezone (the field value, otherwise the
  browser's IANA timezone) and persists that exact zone used for conversion;
  clearing the field must not save a zone-less instant.
- Event create/update callbacks are awaited. A rejected API mutation leaves the
  dialog and completed draft open, displays the failure, and disables duplicate
  submission while the request is pending.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/config.py` | **Modify.** Two settings beside `follow_up_days` (`config.py:189`). |
| `src/resume_agent/services/reminders.py` | **Modify.** Add interview and offer-deadline reminders beside the existing follow-up logic. Same episode-key idiom. |
| `src/resume_agent/services/gmail_sync.py:45` | **Modify.** Stop calling `create_follow_up_reminders`. |
| `src/resume_agent/services/reminder_scheduler.py` | **Create.** The all-users hourly tick. Separate from `gmail/scheduler.py` because it must run for users with no Gmail token — that independence is the whole point. |
| `src/resume_agent/api/app.py:167-181` | **Modify.** Start/stop the new loop beside the Gmail one. |
| `src/resume_agent/calendar/ics.py` | **Create.** RFC 5545 serializer. New package — it is not tracking, not API, and reusable. |
| `src/resume_agent/calendar/events.py` | **Create.** `ApplicationEvent` → calendar-entry mapping. Split from the serializer so the RFC logic is testable without the ORM. |
| `src/resume_agent/api/routers/calendar.py` | **Create.** Two `.ics` routes. |
| `src/resume_agent/tracking/queries.py` | **Modify.** `upcoming_events(session, within_days, now)`. |
| `src/resume_agent/api/schemas/dashboard.py` | **Modify.** `UpcomingEventOut` + a field on `DashboardSummaryOut`. |
| `src/resume_agent/api/routers/dashboard.py` | **Modify.** Populate it. |
| `web/src/features/dashboard/UpcomingCard.tsx` | **Create.** The Next 7 days card. |
| `web/src/features/dashboard/DashboardPage.tsx` | **Modify.** Mount it. |
| `web/src/features/job/EventRow.tsx` | **Modify.** Add-to-calendar button. |
| `web/src/features/notifications/NotificationsBell.tsx:78-110` | **Modify.** Render the two new kinds. |

---

### Task 1: Reminder settings

**Files:**
- Modify: `src/resume_agent/config.py:189`
- Test: `tests/test_reminder_settings.py`

**Interfaces:**
- Produces: `Settings.interview_reminder_hours: int` (default 24), `Settings.offer_deadline_reminder_days: int` (default 2). Both `ge=0`; `0` disables that reminder.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reminder_settings.py
import pytest
from pydantic import ValidationError

from resume_agent.config import Settings


def test_defaults_match_the_spec():
    settings = Settings()
    assert settings.interview_reminder_hours == 24
    assert settings.offer_deadline_reminder_days == 2


def test_zero_disables_each_reminder():
    settings = Settings(interview_reminder_hours=0, offer_deadline_reminder_days=0)
    assert settings.interview_reminder_hours == 0
    assert settings.offer_deadline_reminder_days == 0


@pytest.mark.parametrize(
    "field", ["interview_reminder_hours", "offer_deadline_reminder_days"]
)
def test_negative_values_are_rejected(field):
    with pytest.raises(ValidationError):
        Settings(**{field: -1})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reminder_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'interview_reminder_hours'`

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/config.py`, directly after line 189's `follow_up_days`:

```python
    # Long-lead nudges only. The ~1-hour lead is owned by the exported .ics
    # VALARM: no poller can deliver a one-hour warning reliably, and the
    # calendar already does it natively on the user's phone.
    interview_reminder_hours: int = Field(default=24, ge=0)  # 0 = off
    offer_deadline_reminder_days: int = Field(default=2, ge=0)  # 0 = off
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reminder_settings.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/config.py tests/test_reminder_settings.py
git add src/resume_agent/config.py tests/test_reminder_settings.py
git commit -m "feat(config): interview and offer-deadline reminder lead times"
```

---

### Task 2: Interview and offer-deadline reminders

**Files:**
- Modify: `src/resume_agent/services/reminders.py`
- Test: `tests/test_event_reminders.py`

**Interfaces:**
- Consumes: Phase 1's `ApplicationEvent`, `EventKind`; Task 1's settings.
- Produces:
  - `INTERVIEW_KIND = "interview_soon"`, `DEADLINE_KIND = "offer_deadline_soon"`
  - `event_reminder_key(event_id: int, occurred_at: datetime, kind: str) -> str`
  - `create_event_reminders(session, *, now=None, interview_hours=None, deadline_days=None) -> list[Notification]`

**Episode keying:** the key embeds `occurred_at`, so rescheduling opens a new episode and a dismissal stays dismissed until the date actually moves. This mirrors `follow_up_key`'s existing design.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_reminders.py
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.reminders import (
    DEADLINE_KIND,
    INTERVIEW_KIND,
    create_event_reminders,
)
from resume_agent.tracking.tables import Application, ApplicationEvent, Job

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _session_with_event(**event_kwargs):
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, status="interview")
    session.add(app)
    session.commit()
    session.refresh(app)
    session.add(ApplicationEvent(application_id=app.id, **event_kwargs))
    session.commit()
    return session


def test_interview_inside_the_window_creates_one_reminder():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    created = create_event_reminders(session, now=NOW)
    assert len(created) == 1
    assert created[0].kind == INTERVIEW_KIND
    assert "Acme" in created[0].evidence


def test_interview_outside_the_window_creates_nothing():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=48)
    )
    assert create_event_reminders(session, now=NOW) == []


def test_past_events_never_remind():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW - timedelta(hours=2)
    )
    assert create_event_reminders(session, now=NOW) == []


def test_offer_deadline_uses_the_day_window():
    session = _session_with_event(
        kind="offer_deadline", occurred_at=NOW + timedelta(days=1)
    )
    created = create_event_reminders(session, now=NOW)
    assert len(created) == 1
    assert created[0].kind == DEADLINE_KIND


def test_reminders_are_idempotent_within_an_episode():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    create_event_reminders(session, now=NOW)
    again = create_event_reminders(session, now=NOW + timedelta(hours=1))
    assert again == []


def test_rescheduling_opens_a_new_episode():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    create_event_reminders(session, now=NOW)
    from sqlmodel import select

    event = session.exec(select(ApplicationEvent)).one()
    event.occurred_at = NOW + timedelta(hours=22)
    session.add(event)
    session.commit()
    assert len(create_event_reminders(session, now=NOW)) == 1


def test_zero_lead_time_disables_each_kind():
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    assert create_event_reminders(session, now=NOW, interview_hours=0) == []

    session2 = _session_with_event(
        kind="offer_deadline", occurred_at=NOW + timedelta(days=1)
    )
    assert create_event_reminders(session2, now=NOW, deadline_days=0) == []


def test_non_interview_kinds_do_not_remind():
    session = _session_with_event(
        kind="application_submitted", occurred_at=NOW + timedelta(hours=20)
    )
    assert create_event_reminders(session, now=NOW) == []


def test_cancelled_events_do_not_remind():
    session = _session_with_event(
        kind="technical_round",
        occurred_at=NOW + timedelta(hours=20),
        result="cancelled",
    )
    assert create_event_reminders(session, now=NOW) == []


def test_naive_datetimes_are_treated_as_utc():
    session = _session_with_event(
        kind="technical_round",
        occurred_at=(NOW + timedelta(hours=20)).replace(tzinfo=None),
    )
    assert len(create_event_reminders(session, now=NOW)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_reminders.py -v`
Expected: FAIL — `ImportError: cannot import name 'INTERVIEW_KIND'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/services/reminders.py`:

```python
INTERVIEW_KIND = "interview_soon"
DEADLINE_KIND = "offer_deadline_soon"

# Which kinds are worth warning about. `application_submitted` is a record of
# something already done; `rejected`/`withdrawn` are exits. Only things the
# user must *prepare for* remind.
_REMINDABLE_INTERVIEW_KINDS = frozenset(
    {
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
    }
)
_DEAD_RESULTS = frozenset({EventResult.cancelled.value, EventResult.withdrew.value})


def event_reminder_key(event_id: int, occurred_at: datetime, kind: str) -> str:
    """Episode key: embeds the date so a reschedule opens a fresh episode."""
    return f"{kind}:{event_id}:{occurred_at.isoformat()}"


def create_event_reminders(
    session: Session,
    *,
    now: datetime | None = None,
    interview_hours: int | None = None,
    deadline_days: int | None = None,
) -> list[Notification]:
    """Long-lead nudges for upcoming interviews and offer deadlines.

    The ~1-hour lead is owned by the exported .ics VALARM, not by this poller.
    """
    settings = get_settings()
    interview_hours = (
        settings.interview_reminder_hours if interview_hours is None else interview_hours
    )
    deadline_days = (
        settings.offer_deadline_reminder_days if deadline_days is None else deadline_days
    )
    now = _aware(now or utcnow())
    created: list[Notification] = []

    windows = {
        INTERVIEW_KIND: (_REMINDABLE_INTERVIEW_KINDS, timedelta(hours=interview_hours)),
        DEADLINE_KIND: ({EventKind.offer_deadline.value}, timedelta(days=deadline_days)),
    }

    for event, app, job in upcoming_event_rows(session):
        if event.id is None or app.id is None or event.occurred_at is None:
            continue
        if event.result in _DEAD_RESULTS:
            continue
        occurred = _aware(event.occurred_at)
        if occurred <= now:
            continue
        for notification_kind, (kinds, window) in windows.items():
            if event.kind not in kinds or not window:
                continue
            if occurred - now > window:
                continue
            key = event_reminder_key(event.id, occurred, notification_kind)
            if notification_by_key(session, app.id, key) is not None:
                continue
            label = "Offer deadline" if notification_kind == DEADLINE_KIND else "Interview"
            created.append(
                save_notification(
                    session,
                    Notification(
                        application_id=app.id,
                        kind=notification_kind,
                        proposed_status="",
                        evidence=(
                            f"{label} {occurred.strftime('%b %d, %H:%M UTC')} — "
                            f"{job.company} · {job.title}"
                        ),
                        message_id=key,
                    ),
                )
            )
    return created
```

Add the imports this needs at the top of the module: `EventKind`, `EventResult` from `resume_agent.tracking.event_vocab`, and a new `upcoming_event_rows` query.

Add that query to `src/resume_agent/tracking/queries.py`, following the existing `application_job_pairs` idiom:

```python
def upcoming_event_rows(
    session: Session,
) -> list[tuple[ApplicationEvent, Application, Job]]:
    """Every dated event with its application and job, archived jobs excluded."""
    archived_col = cast(Any, Job.archived_at)
    occurred_col = cast(Any, ApplicationEvent.occurred_at)
    statement = (
        select(ApplicationEvent, Application, Job)
        .join(Application, ApplicationEvent.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(occurred_col.is_not(None), archived_col.is_(None))
    )
    return list(session.exec(statement).all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_reminders.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/services/reminders.py src/resume_agent/tracking/queries.py tests/test_event_reminders.py
git add src/resume_agent/services/reminders.py src/resume_agent/tracking/queries.py tests/test_event_reminders.py
git commit -m "feat(reminders): interview and offer-deadline nudges"
```

---

### Task 3: Decouple reminders from Gmail

**Files:**
- Create: `src/resume_agent/services/reminder_scheduler.py`
- Modify: `src/resume_agent/services/gmail_sync.py:44-46`
- Modify: `src/resume_agent/api/app.py:167-181`
- Test: `tests/test_reminder_scheduler.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `run_reminder_pass(session, *, now=None) -> dict[str, int]` — `{"followUp": n, "events": m}`
  - `async def reminder_tick(state, *, now=None) -> dict[str, int]`
  - `async def reminder_loop(state) -> None`
  - `REMINDER_INTERVAL_SECONDS = 3600`

**This fixes a pre-existing bug.** `create_follow_up_reminders` has exactly one call site — inside `run_gmail_sync`, after `build_service()` raises for users with no token. Users who never connected Gmail have silently received no reminders at all.

**Why a separate module from `gmail/scheduler.py`:** the entire point is running for users *without* a Gmail token. Sharing the file would invite re-coupling.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reminder_scheduler.py
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.services.reminder_scheduler import (
    REMINDER_INTERVAL_SECONDS,
    run_reminder_pass,
)
from resume_agent.tracking.tables import (
    Application,
    ApplicationEvent,
    Job,
    Notification,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def _job_with_event(session, **event_kwargs):
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, status="interview")
    session.add(app)
    session.commit()
    session.refresh(app)
    session.add(ApplicationEvent(application_id=app.id, **event_kwargs))
    session.commit()


def test_reminder_pass_runs_without_any_gmail_token():
    """The regression this task exists to fix."""
    session = _session()
    _job_with_event(
        session, kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    counts = run_reminder_pass(session, now=NOW)
    assert counts["events"] == 1
    stored = session.exec(select(Notification)).all()
    assert len(stored) == 1


def test_reminder_pass_also_creates_stale_follow_ups():
    session = _session()
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    stale = Application(
        job_id=job.id, status="submitted", updated_at=NOW - timedelta(days=30)
    )
    session.add(stale)
    session.commit()
    counts = run_reminder_pass(session, now=NOW)
    assert counts["followUp"] == 1


def test_reminder_pass_is_idempotent():
    session = _session()
    _job_with_event(
        session, kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    run_reminder_pass(session, now=NOW)
    second = run_reminder_pass(session, now=NOW)
    assert second == {"followUp": 0, "events": 0}


def test_interval_is_hourly():
    assert REMINDER_INTERVAL_SECONDS == 3600


def test_gmail_sync_no_longer_creates_reminders():
    import inspect

    from resume_agent.services import gmail_sync

    source = inspect.getsource(gmail_sync)
    assert "create_follow_up_reminders" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reminder_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.reminder_scheduler'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/services/reminder_scheduler.py
"""Reminders for every user, hourly, independent of Gmail.

Reminder generation previously lived inside `run_gmail_sync`, which calls
`build_service()` first — so a user who never connected Gmail received no
reminders at all, and `gmail/scheduler.py` skipped them entirely. That
coupling was invisible and undocumented. This module owns reminders instead;
Gmail sync owns email classification and nothing else.

Deliberately a separate module from `gmail/scheduler.py`: running for users
*without* a token is the entire point, and sharing a file invites re-coupling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session

from resume_agent.db import get_session
from resume_agent.services.reminders import (
    create_event_reminders,
    create_follow_up_reminders,
)

logger = logging.getLogger(__name__)

REMINDER_INTERVAL_SECONDS = 3600


def run_reminder_pass(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """One user's reminder pass. Pure over (session, now)."""
    follow_ups = create_follow_up_reminders(session, now=now)
    events = create_event_reminders(session, now=now)
    return {"followUp": len(follow_ups), "events": len(events)}


async def reminder_tick(state: Any, *, now: datetime | None = None) -> dict[str, int]:
    """One serial pass over every user. Never raises per-user errors."""
    results: dict[str, int] = {}
    if state.system_engine is None:
        with get_session(state.engine) as session:
            counts = run_reminder_pass(session, now=now)
        results["local"] = counts["followUp"] + counts["events"]
        return results

    from sqlalchemy import select
    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.bootstrap import build_context
    from resume_agent.tenancy.context import use_context
    from resume_agent.tenancy.system_db import User

    with SystemSession(state.system_engine, expire_on_commit=False) as session:
        users = list(
            session.execute(select(User).where(User.disabled_at.is_(None)))
            .scalars()
            .all()
        )
        for user in users:
            session.expunge(user)

    for user in users:
        try:
            context = build_context(
                user,
                state.data_dir,
                state.settings,
                state.engine_registry,
                system_engine=state.system_engine,
                template_dir=state.template_config_dir,
            )
            with use_context(context), get_session(context.engine) as user_session:
                counts = run_reminder_pass(user_session, now=now)
            results[user.id] = counts["followUp"] + counts["events"]
        except Exception as exc:  # noqa: BLE001 — one user never aborts the loop
            logger.warning("reminder pass failed for %s: %s", user.id, exc)
    return results


async def reminder_loop(state: Any) -> None:
    while True:
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)
        try:
            await reminder_tick(state)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            logger.exception("reminder tick crashed")
```

In `src/resume_agent/services/gmail_sync.py`, delete the `create_follow_up_reminders` import and its call at line 45. Keep the two-step reporter contract by relabelling step 1 — change `reporter.step(1, label="Checking follow-ups")` to `reporter.step(1, label="Classifying")` and drop `reminders` from the returned dict, returning `{"pending": len(pending)}`.

In `src/resume_agent/api/app.py`, beside the Gmail scheduler wiring at lines 167-181, add a `reminder_task` started unconditionally (no Gmail-token check) and cancelled in the same shutdown block:

```python
        from resume_agent.services.reminder_scheduler import reminder_loop

        app.state.reminder_task = asyncio.create_task(reminder_loop(app.state))
```

and in shutdown, mirroring the existing cancel/await pattern for `gmail_scheduler_task`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reminder_scheduler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Check for gmail_sync callers asserting on `reminders`**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q -k "gmail"`
Expected: PASS. Any test asserting `result["reminders"]` must be updated to reflect that gmail sync no longer produces reminders — that is the intended behaviour change, not a break.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_agent/services/ src/resume_agent/api/app.py tests/test_reminder_scheduler.py
git add src/resume_agent/services/ src/resume_agent/api/app.py tests/test_reminder_scheduler.py
git commit -m "fix(reminders): decouple from Gmail; hourly all-user tick"
```

---

### Task 4: `.ics` serializer

**Files:**
- Create: `src/resume_agent/calendar/__init__.py` (empty)
- Create: `src/resume_agent/calendar/ics.py`
- Test: `tests/test_ics.py`

**Interfaces:**
- Consumes: nothing (no ORM import — that is the point of the split).
- Produces:
  - `@dataclass CalendarEntry(uid, summary, start, end, all_day, timezone, location, url, description, alarm_minutes_before)`
  - `render_calendar(entries: list[CalendarEntry]) -> str`

**RFC 5545 essentials this must honour:**
- CRLF line endings (`\r\n`) — not optional.
- Lines folded at 75 octets, continuations prefixed with one space.
- `,`, `;`, `\` and newlines escaped in TEXT values.
- All-day: `DTSTART;VALUE=DATE:20260303` and `DTEND` the **following** day (exclusive end).
- Timed: `DTSTART;TZID=America/New_York:20260309T140000`, or `...Z` UTC form when no zone.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ics.py
from datetime import datetime, timezone

from resume_agent.calendar.ics import CalendarEntry, render_calendar

START = datetime(2026, 3, 9, 19, 0, tzinfo=timezone.utc)


def _entry(**over):
    base = dict(
        uid="event-1@resume-agent",
        summary="Technical round — Acme",
        start=START,
        end=datetime(2026, 3, 9, 20, 0, tzinfo=timezone.utc),
        all_day=False,
        timezone=None,
        location=None,
        url=None,
        description=None,
        alarm_minutes_before=60,
    )
    base.update(over)
    return CalendarEntry(**base)


def test_wrapper_and_crlf_line_endings():
    out = render_calendar([_entry()])
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert out.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in out
    assert "\n" not in out.replace("\r\n", "")


def test_timed_event_emits_utc_and_an_alarm():
    out = render_calendar([_entry()])
    assert "DTSTART:20260309T190000Z" in out
    assert "DTEND:20260309T200000Z" in out
    assert "BEGIN:VALARM" in out
    assert "TRIGGER:-PT60M" in out


def test_named_timezone_uses_tzid():
    out = render_calendar([_entry(timezone="America/New_York")])
    assert "DTSTART;TZID=America/New_York:" in out


def test_all_day_uses_value_date_with_an_exclusive_end():
    out = render_calendar([_entry(all_day=True, end=None)])
    assert "DTSTART;VALUE=DATE:20260309" in out
    assert "DTEND;VALUE=DATE:20260310" in out
    assert "BEGIN:VALARM" not in out  # no meaningful hour to alarm against


def test_missing_end_on_a_timed_event_defaults_to_one_hour():
    out = render_calendar([_entry(end=None)])
    assert "DTEND:20260309T200000Z" in out


def test_text_values_are_escaped():
    out = render_calendar(
        [_entry(description="Round 1; round 2, then\nlunch. Path C:\\temp")]
    )
    assert r"\;" in out and r"\," in out and r"\n" in out and r"\\" in out


def test_long_lines_are_folded_at_75_octets_with_a_leading_space():
    out = render_calendar([_entry(description="x" * 400)])
    for line in out.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert "\r\n " in out


def test_uid_is_stable_so_reimport_updates_rather_than_duplicates():
    first = render_calendar([_entry()])
    second = render_calendar([_entry()])
    assert "UID:event-1@resume-agent" in first
    assert first == second.replace(
        second.split("DTSTAMP:")[1].split("\r\n")[0],
        first.split("DTSTAMP:")[1].split("\r\n")[0],
    )


def test_multiple_entries_render_as_multiple_vevents():
    out = render_calendar([_entry(), _entry(uid="event-2@resume-agent")])
    assert out.count("BEGIN:VEVENT") == 2


def test_empty_list_is_a_valid_empty_calendar():
    out = render_calendar([])
    assert "BEGIN:VCALENDAR" in out and "BEGIN:VEVENT" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.calendar'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/calendar/ics.py
"""Minimal RFC 5545 writer for the subset this app emits.

Hand-rolled rather than adding `icalendar`: the subset is a few dozen lines,
and the folding and escaping rules are the only parts worth testing anyway.
No ORM import here — the mapping from ApplicationEvent lives in events.py so
these rules stay testable as pure text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_PRODID = "-//resume-agent//application timeline//EN"
_LINE_OCTETS = 75


@dataclass(frozen=True)
class CalendarEntry:
    uid: str
    summary: str
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    timezone: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    alarm_minutes_before: int | None = None


def _escape(value: str) -> str:
    # Backslash first, or the escapes we add get escaped again.
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Fold at 75 octets; continuations begin with one space (RFC 5545 §3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= _LINE_OCTETS:
        return [line]
    out: list[str] = []
    chunk = bytearray()
    limit = _LINE_OCTETS
    for char in line:
        encoded = char.encode("utf-8")
        if len(chunk) + len(encoded) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = bytearray()
            limit = _LINE_OCTETS - 1  # the leading space costs one octet
        chunk.extend(encoded)
    if chunk:
        out.append(chunk.decode("utf-8"))
    return [out[0]] + [" " + part for part in out[1:]]


def _utc_stamp(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _entry_lines(entry: CalendarEntry) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{entry.uid}",
        f"DTSTAMP:{_utc_stamp(datetime.now(timezone.utc))}",
        f"SUMMARY:{_escape(entry.summary)}",
    ]
    if entry.all_day:
        # DTEND is exclusive for date values, so a one-day event ends tomorrow.
        end = (entry.end or entry.start) + timedelta(days=1)
        lines.append(f"DTSTART;VALUE=DATE:{entry.start.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}")
    else:
        end = entry.end or entry.start + timedelta(hours=1)
        if entry.timezone:
            local = "%Y%m%dT%H%M%S"
            lines.append(f"DTSTART;TZID={entry.timezone}:{entry.start.strftime(local)}")
            lines.append(f"DTEND;TZID={entry.timezone}:{end.strftime(local)}")
        else:
            lines.append(f"DTSTART:{_utc_stamp(entry.start)}")
            lines.append(f"DTEND:{_utc_stamp(end)}")
    if entry.location:
        lines.append(f"LOCATION:{_escape(entry.location)}")
    if entry.url:
        lines.append(f"URL:{_escape(entry.url)}")
    if entry.description:
        lines.append(f"DESCRIPTION:{_escape(entry.description)}")
    if entry.alarm_minutes_before and not entry.all_day:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(entry.summary)}",
            f"TRIGGER:-PT{entry.alarm_minutes_before}M",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def render_calendar(entries: list[CalendarEntry]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
    ]
    for entry in entries:
        lines.extend(_entry_lines(entry))
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ics.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/calendar/ tests/test_ics.py
git add src/resume_agent/calendar/ tests/test_ics.py
git commit -m "feat(calendar): RFC 5545 ics writer"
```

---

### Task 5: Event → calendar entry mapping

**Files:**
- Create: `src/resume_agent/calendar/events.py`
- Test: `tests/test_calendar_events.py`

**Interfaces:**
- Consumes: Task 4's `CalendarEntry`; Phase 1's `ApplicationEvent` and `KIND_LABELS` equivalent.
- Produces: `entry_for_event(event, job) -> CalendarEntry`; `entries_for_upcoming(session, *, now=None, within_days=90) -> list[CalendarEntry]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_events.py
from datetime import datetime, timedelta, timezone

from resume_agent.calendar.events import entries_for_upcoming, entry_for_event
from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Application, ApplicationEvent, Job
from sqlmodel import Session

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _event(**over):
    base = dict(
        id=1,
        application_id=7,
        kind="technical_round",
        sequence=2,
        occurred_at=datetime(2026, 3, 9, 19, 0, tzinfo=timezone.utc),
        all_day=False,
        duration_minutes=90,
        platform="zoom",
        location_or_link="https://zoom.us/j/123",
        interviewers="Dana Vale",
    )
    base.update(over)
    return ApplicationEvent(**base)


def _job():
    return Job(id=42, source="test", company="Acme", title="Senior SWE")


def test_summary_names_the_stage_round_and_company():
    entry = entry_for_event(_event(), _job())
    assert entry.summary == "Technical round 2 — Acme"


def test_duration_drives_the_end_time():
    entry = entry_for_event(_event(), _job())
    assert entry.end - entry.start == timedelta(minutes=90)


def test_missing_duration_leaves_end_unset_for_the_writer_default():
    entry = entry_for_event(_event(duration_minutes=None), _job())
    assert entry.end is None


def test_a_url_link_becomes_both_url_and_location():
    entry = entry_for_event(_event(), _job())
    assert entry.url == "https://zoom.us/j/123"
    assert entry.location == "https://zoom.us/j/123"


def test_a_street_address_is_location_only():
    entry = entry_for_event(_event(location_or_link="1 Main St, Austin TX"), _job())
    assert entry.location == "1 Main St, Austin TX"
    assert entry.url is None


def test_description_carries_interviewers_platform_and_notes():
    entry = entry_for_event(_event(notes="LRU cache"), _job())
    assert "Dana Vale" in entry.description
    assert "Zoom" in entry.description
    assert "LRU cache" in entry.description


def test_uid_is_stable_and_scoped_to_the_event():
    assert entry_for_event(_event(), _job()).uid == "application-event-1@resume-agent"


def test_all_day_events_carry_no_alarm():
    entry = entry_for_event(_event(all_day=True), _job())
    assert entry.all_day is True
    assert entry.alarm_minutes_before is None


def test_timed_events_alarm_one_hour_before():
    assert entry_for_event(_event(), _job()).alarm_minutes_before == 60


def test_upcoming_excludes_past_and_undated_events():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = Job(source="test", company="Acme", title="SWE")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id, status="interview")
        session.add(app)
        session.commit()
        session.refresh(app)
        session.add_all(
            [
                ApplicationEvent(
                    application_id=app.id,
                    kind="technical_round",
                    occurred_at=NOW + timedelta(days=3),
                ),
                ApplicationEvent(
                    application_id=app.id,
                    kind="recruiter_screen",
                    occurred_at=NOW - timedelta(days=3),
                ),
                ApplicationEvent(
                    application_id=app.id, kind="custom", custom_label="ping"
                ),
            ]
        )
        session.commit()
        entries = entries_for_upcoming(session, now=NOW)
    assert len(entries) == 1
    assert "Technical round" in entries[0].summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.calendar.events'`

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/calendar/events.py` with:

- `KIND_LABELS` / `PLATFORM_LABELS` mirroring the web maps from Phase 1 Task 10, as module-level dicts. (Duplicated across the language boundary by necessity; add a comment noting they must stay in sync with `EventFormDialog.tsx`.)
- `entry_for_event(event, job)`:
  - `summary`: `KIND_LABELS[kind]`, plus ` {sequence}` for `technical_round` / `offer_received` only, then ` — {job.company}`. For `custom`, use `custom_label`.
  - `start`: `event.occurred_at`. `end`: `start + duration_minutes` when set, else `None`.
  - `location`/`url`: if `location_or_link` starts with `http://` or `https://`, set both; otherwise `location` only.
  - `description`: interviewers, platform label (or `platform_other`), modality, notes — joined with newlines, blanks skipped.
  - `uid`: `f"application-event-{event.id}@resume-agent"`.
  - `alarm_minutes_before`: `None` when `all_day`, else `60`.
- `entries_for_upcoming(session, *, now=None, within_days=90)`: uses `upcoming_event_rows` from Task 2, filters to `occurred_at > now` and within the window, maps each through `entry_for_event`, sorted by start.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_events.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/calendar/events.py tests/test_calendar_events.py
git add src/resume_agent/calendar/events.py tests/test_calendar_events.py
git commit -m "feat(calendar): map application events to calendar entries"
```

---

### Task 6: Calendar download routes

**Files:**
- Create: `src/resume_agent/api/routers/calendar.py`
- Modify: `src/resume_agent/api/app.py` (register beside the other guarded routers)
- Test: `tests/api/test_calendar_routes.py`

**Interfaces:**
- Consumes: Tasks 4 and 5.
- Produces: `GET /api/jobs/{job_id}/events/{event_id}.ics`, `GET /api/applications/upcoming.ics`.

Both return `text/calendar; charset=utf-8` with a `Content-Disposition: attachment` filename. Both sit behind the existing session auth (`dependencies=guarded`) — no capability token, no public URL.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_calendar_routes.py
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _job_with_event(client, **over):
    job_id = client.post(
        "/api/jobs", json={"jdText": "Build things.", "company": "Acme", "title": "SWE"}
    ).json()["id"]
    body = {
        "kind": "technical_round",
        "occurredAt": "2026-03-09T19:00:00Z",
        "durationMinutes": 60,
        "platform": "zoom",
        "locationOrLink": "https://zoom.us/j/123",
    }
    body.update(over)
    event_id = client.post(f"/api/jobs/{job_id}/events", json=body).json()["id"]
    return job_id, event_id


def test_single_event_ics_download():
    client = _client()
    with client:
        job_id, event_id = _job_with_event(client)
        resp = client.get(f"/api/jobs/{job_id}/events/{event_id}.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "attachment" in resp.headers["content-disposition"]
    assert "BEGIN:VEVENT" in resp.text
    assert "TRIGGER:-PT60M" in resp.text


def test_single_event_ics_is_404_for_an_unknown_event():
    client = _client()
    with client:
        job_id, _ = _job_with_event(client)
        resp = client.get(f"/api/jobs/{job_id}/events/9999.ics")
    assert resp.status_code == 404


def test_upcoming_ics_returns_a_valid_empty_calendar_when_nothing_is_scheduled():
    client = _client()
    with client:
        resp = client.get("/api/applications/upcoming.ics")
    assert resp.status_code == 200
    assert "BEGIN:VCALENDAR" in resp.text
    assert "BEGIN:VEVENT" not in resp.text


def test_undated_custom_event_cannot_be_exported():
    client = _client()
    with client:
        job_id = client.post(
            "/api/jobs", json={"jdText": "x", "company": "Acme", "title": "SWE"}
        ).json()["id"]
        event_id = client.post(
            f"/api/jobs/{job_id}/events",
            json={"kind": "custom", "customLabel": "ping"},
        ).json()["id"]
        resp = client.get(f"/api/jobs/{job_id}/events/{event_id}.ics")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_calendar_routes.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/api/routers/calendar.py
"""Calendar downloads. Authenticated like every other route.

No subscribable feed: a webcal:// URL is unauthenticated by construction
(calendar clients send no session cookie) and would expose every company
applied to and every interview date to anyone holding the link. That needs a
capability token, a revoke path, and a rate limit under ADR-0008 — its own
design pass, not a subsection of this one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.calendar.events import entries_for_upcoming, entry_for_event
from resume_agent.calendar.ics import render_calendar
from resume_agent.tracking.repository import get_application_event, get_job

router = APIRouter()

_MEDIA_TYPE = "text/calendar; charset=utf-8"


def _attachment(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type=_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/events/{event_id}.ics")
def event_ics(job_id: int, event_id: int, session: Session = Depends(get_session)):
    job = get_job(session, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    event = get_application_event(session, event_id)
    if event is None:
        raise ApiException(404, "NOT_FOUND", f"Event #{event_id} not found")
    if event.occurred_at is None:
        raise ApiException(
            422, "VALIDATION_ERROR", "An undated event cannot be exported to a calendar"
        )
    body = render_calendar([entry_for_event(event, job)])
    return _attachment(body, f"event-{event_id}.ics")


@router.get("/applications/upcoming.ics")
def upcoming_ics(session: Session = Depends(get_session)):
    body = render_calendar(entries_for_upcoming(session))
    return _attachment(body, "upcoming-interviews.ics")
```

Register in `app.py` beside the other guarded routers.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_calendar_routes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Regenerate the contract, lint, commit**

```bash
make openapi && make client
ruff check src/resume_agent/api/routers/calendar.py
git add src/resume_agent/api/ tests/api/test_calendar_routes.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(api): ics download routes for events and upcoming pipeline"
```

---

### Task 7: Dashboard upcoming-events data

**Files:**
- Modify: `src/resume_agent/tracking/queries.py`
- Modify: `src/resume_agent/api/schemas/dashboard.py`
- Modify: `src/resume_agent/api/routers/dashboard.py`
- Test: `tests/api/test_dashboard_upcoming.py`

**Interfaces:**
- Produces:
  - `upcoming_events(session, *, within_days=7, now=None) -> list[tuple[ApplicationEvent, Job]]` — ascending by date.
  - `UpcomingEventOut(event_id, job_id, company, title, kind, custom_label, sequence, occurred_at, all_day, timezone, modality, platform, location_or_link)`
  - `DashboardSummaryOut.upcoming_events: list[UpcomingEventOut]`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_dashboard_upcoming.py
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")


def _job_with_event(client, company, delta, kind="technical_round"):
    job_id = client.post(
        "/api/jobs", json={"jdText": "x", "company": company, "title": "SWE"}
    ).json()["id"]
    client.post(
        f"/api/jobs/{job_id}/events", json={"kind": kind, "occurredAt": _iso(delta)}
    )
    return job_id


def test_upcoming_events_appear_in_the_summary():
    client = _client()
    with client:
        _job_with_event(client, "Acme", timedelta(days=2))
        body = client.get("/api/dashboard/summary").json()
    assert len(body["upcomingEvents"]) == 1
    entry = body["upcomingEvents"][0]
    assert entry["company"] == "Acme"
    assert entry["kind"] == "technical_round"


def test_events_beyond_seven_days_are_excluded():
    client = _client()
    with client:
        _job_with_event(client, "Acme", timedelta(days=30))
        body = client.get("/api/dashboard/summary").json()
    assert body["upcomingEvents"] == []


def test_past_events_are_excluded():
    client = _client()
    with client:
        _job_with_event(client, "Acme", timedelta(days=-2))
        body = client.get("/api/dashboard/summary").json()
    assert body["upcomingEvents"] == []


def test_offer_deadlines_are_included():
    client = _client()
    with client:
        _job_with_event(client, "Acme", timedelta(days=1), kind="offer_deadline")
        body = client.get("/api/dashboard/summary").json()
    assert body["upcomingEvents"][0]["kind"] == "offer_deadline"


def test_results_are_chronological():
    client = _client()
    with client:
        _job_with_event(client, "Later", timedelta(days=5))
        _job_with_event(client, "Sooner", timedelta(days=1))
        body = client.get("/api/dashboard/summary").json()
    assert [e["company"] for e in body["upcomingEvents"]] == ["Sooner", "Later"]


def test_summary_still_works_with_no_events():
    client = _client()
    with client:
        body = client.get("/api/dashboard/summary").json()
    assert body["upcomingEvents"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_dashboard_upcoming.py -v`
Expected: FAIL — `KeyError: 'upcomingEvents'`

- [ ] **Step 3: Write minimal implementation**

Add `upcoming_events` to `tracking/queries.py`, filtering `upcoming_event_rows` (Task 2) to `now < occurred_at <= now + within_days`, sorted ascending, returning `(event, job)` pairs.

Add `UpcomingEventOut` to `api/schemas/dashboard.py` with the fields listed above, and `upcoming_events: list[UpcomingEventOut] = Field(default_factory=list)` on `DashboardSummaryOut` (defaulted so existing constructions keep working).

Populate it in `api/routers/dashboard.py` where the summary is assembled.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_dashboard_upcoming.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Regenerate the contract, lint, commit**

```bash
make openapi && make client
.venv/Scripts/python.exe -m pytest -q -k dashboard
ruff check
git add src/resume_agent/ tests/api/test_dashboard_upcoming.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(api): upcoming events on the dashboard summary"
```

---

### Task 8: Web — Next 7 days card and calendar buttons

**Files:**
- Create: `web/src/features/dashboard/UpcomingCard.tsx`
- Create: `web/src/features/dashboard/UpcomingCard.test.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`
- Modify: `web/src/features/job/EventRow.tsx`
- Modify: `web/src/features/notifications/NotificationsBell.tsx:78-110`

**Interfaces:**
- Consumes: Tasks 6 and 7.
- Produces: `<UpcomingCard />`, reading `useDashboardSummary()`.

**Download note:** `.ics` routes are authenticated, so a plain `<a href>` works — the browser sends the session cookie. Do **not** fetch-then-blob; a direct link is simpler and correct here.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/dashboard/UpcomingCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ upcoming: [] as unknown[] }));

vi.mock("./use-dashboard-summary", () => ({
  useDashboardSummary: () => ({
    data: { upcomingEvents: mocks.upcoming },
    isLoading: false,
  }),
}));

vi.mock("react-router-dom", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

import { UpcomingCard } from "./UpcomingCard";

const entry = (over: Record<string, unknown> = {}) => ({
  eventId: 1,
  jobId: 42,
  company: "Acme",
  title: "Senior SWE",
  kind: "technical_round",
  sequence: 2,
  occurredAt: "2026-03-09T19:00:00Z",
  allDay: false,
  platform: "zoom",
  ...over,
});

describe("UpcomingCard", () => {
  it("renders nothing when there is nothing scheduled", () => {
    mocks.upcoming = [];
    const { container } = render(<UpcomingCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists an upcoming interview with its company", () => {
    mocks.upcoming = [entry()];
    render(<UpcomingCard />);
    expect(screen.getByText(/next 7 days/i)).toBeInTheDocument();
    expect(screen.getByText(/Acme/)).toBeInTheDocument();
    expect(screen.getByText(/Technical round 2/)).toBeInTheDocument();
  });

  it("links each entry to its job", () => {
    mocks.upcoming = [entry()];
    render(<UpcomingCard />);
    expect(screen.getByRole("link", { name: /Acme/ })).toHaveAttribute(
      "href",
      expect.stringContaining("42"),
    );
  });

  it("flags an offer deadline distinctly", () => {
    mocks.upcoming = [entry({ kind: "offer_deadline", sequence: 1 })];
    render(<UpcomingCard />);
    expect(screen.getByText(/offer deadline/i)).toBeInTheDocument();
  });

  it("offers an add-to-calendar download for the whole window", () => {
    mocks.upcoming = [entry()];
    render(<UpcomingCard />);
    expect(screen.getByRole("link", { name: /add to calendar/i })).toHaveAttribute(
      "href",
      "/api/applications/upcoming.ics",
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- UpcomingCard`
Expected: FAIL — cannot resolve `./UpcomingCard`.

- [ ] **Step 3: Write minimal implementation**

`UpcomingCard.tsx`, following `AttentionCard.tsx`'s structure (`Card` / `CardHeader` / `CardTitle` / `CardContent`):
- Returns `null` when the list is empty — a card that says "nothing scheduled" is noise on a dashboard.
- Title "Next 7 days", with a `<Badge>` carrying the count.
- Each row: relative day ("Tomorrow", "In 3 days"), the stage label (reusing `KIND_LABELS` exported from `EventFormDialog.tsx`, with the sequence suffix for repeatable kinds only), and `<Link to={`/pipeline?job=${jobId}`}>` on the company. Match the deep-link query parameter the codebase already uses for job detail — check `PipelineContainer.tsx` and follow it.
- `offer_deadline` rows get a `destructive` badge variant.
- A footer `<a href="/api/applications/upcoming.ics">Add to calendar</a>`.

Mount `<UpcomingCard />` in `DashboardPage.tsx` **above** `AttentionCard` — a forgotten interview outranks an error record.

In `EventRow.tsx`, add an "Add to calendar" `<a>` linking to `/api/jobs/{jobId}/events/{eventId}.ics`, rendered only when `occurredAt` is non-null.

In `NotificationsBell.tsx`, extend the `item.kind === "follow_up"` branches at lines 78, 102, and 108 to handle `interview_soon` and `offer_deadline_soon`: show the evidence text, and make the action a "View job" link rather than "Accept" (these are nudges, not proposals with a status to accept).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- UpcomingCard`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the whole web suite**

Run: `npm --prefix web run test:run`
Expected: PASS. `DashboardPage.test.tsx` and `NotificationsBell.test.tsx` may need fixtures extended with `upcomingEvents: []` — that is expected.

- [ ] **Step 6: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/dashboard/ web/src/features/job/EventRow.tsx web/src/features/notifications/NotificationsBell.tsx
git commit -m "feat(web): next-7-days card, calendar downloads, reminder notifications"
```

---

### Task 9: Phase 2 verification and documentation

- [ ] **Step 1: Run the full gate**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
npm --prefix web run lint
npm --prefix web run test:run
npm --prefix web run build
```

Expected: all green, backend and web counts at or above the Phase 1 baseline.

- [ ] **Step 2: Manually verify one `.ics` file imports**

Start the app, create an event with a date and time, download its `.ics`, and open it in a real calendar client (Google Calendar's "Import", or Outlook). Confirm: correct date and time, correct duration, the alarm present, the location clickable. **This is the one thing unit tests cannot prove** — RFC conformance and client acceptance are different bars.

- [ ] **Step 3: Document**

Update `src/resume_agent/gmail/CLAUDE.md`: reminders are no longer produced by `run_gmail_sync`. State plainly that they previously were, that this silently denied reminders to users without a Gmail token, and that `services/reminder_scheduler.py` now owns them on an hourly all-user tick.

Create `src/resume_agent/calendar/CLAUDE.md` covering: why hand-rolled rather than `icalendar`; the folding/escaping/exclusive-DTEND rules that are easy to get wrong; the lead-time split (VALARM owns ~1 hour, the app owns 24h/48h) and why; and why there is no `webcal://` feed.

Add to the root `CLAUDE.md` architecture map:

| Area | Lives in |
| --- | --- |
| Calendar export (`.ics`, RFC 5545) | `src/resume_agent/calendar/CLAUDE.md` |

- [ ] **Step 4: Commit**

```bash
git add src/resume_agent/calendar/CLAUDE.md src/resume_agent/gmail/CLAUDE.md CLAUDE.md
git commit -m "docs: calendar export and reminder decoupling notes"
```

---

## Phase 2 Done When

- Reminders fire for a user with **no Gmail token** — the pre-existing bug is fixed and pinned by a test.
- `run_gmail_sync` no longer calls `create_follow_up_reminders`; an hourly all-user tick does.
- Interview reminders fire 24h out, offer-deadline reminders 48h out; `0` disables each; rescheduling opens a new episode and idempotence holds within one.
- `.ics` downloads work for a single event and for the upcoming pipeline, with correct all-day handling, `TZID`, folding, escaping, and a `VALARM`.
- **A downloaded `.ics` has been imported into a real calendar client and verified by hand.**
- The dashboard shows a Next 7 days card above the attention card; the notification bell renders both new kinds.
- Full gate green.
