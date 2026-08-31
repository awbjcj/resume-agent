# Closed-Loop Resume — Phase 3: Gmail Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the existing inbound Gmail pipeline (fetch → match → classify → propose) as persisted, reviewable in-app notifications; accepting one applies the application-status transition, dismissing one suppresses it forever.

**Architecture:** A new `Notification` table records each proposed transition keyed idempotently by `(application_id, message_id)`. A Gmail-sync Run (202 + SSE, matching `pull`/`tailor`) fetches recent mail and upserts notifications. A notifications service exposes list-pending / accept / dismiss. New REST endpoints and a frontend notifications bell + inbox let the user review and act.

**Tech Stack:** Python 3 / FastAPI / SQLModel / SQLite, Google Gmail API (read-only), the existing `RunManager` substrate; React + TanStack Query frontend; pytest (offline, Gmail faked) + vitest.

## Global Constraints

- **Inbound only, human-gated.** Classification can misfire; notifications are _proposed_, never auto-applied. Accept is an explicit user action.
- **Idempotent sync.** Re-syncing the same inbox must not duplicate a proposal or resurrect a dismissed one — upsert keyed on `(application_id, message_id)`.
- **Tests are offline.** No Gmail network. Fake `fetch_recent_messages`/`classify`; build `EmailMessage` fixtures. Run: `.venv/Scripts/python.exe -m pytest`.
- **Wire format is camelCase** via `CamelModel`. Regenerate contracts (`bash scripts/gen_ts_client.sh`); `tests/api/test_openapi_contract.py` is the drift gate.
- **Depends on Phase 1** for `Application.cover_letter_id`? No — Phase 3 only touches `Application.status`. It is independent of Phases 1–2 and may be built in any order.
- **Lint clean:** `ruff check` must pass.

---

### Task 1: Surface `message_id` on `EmailMessage`

**Files:**

- Modify: `src/resume_tailor_harness/gmail/client.py:9-17` (`EmailMessage`), `:54-78` (`fetch_recent_messages`)
- Test: `tests/test_gmail_client.py` (append; create if absent)

**Interfaces:**

- Produces: `EmailMessage.message_id: str | None` populated from the Gmail `ref["id"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_client.py
from resume_tailor_harness.gmail.client import EmailMessage, fetch_recent_messages


class _FakeMessages:
    def list(self, **k): return self
    def get(self, **k):
        self._id = k["id"]; return self
    def execute(self):
        # list() then get() both call execute(); disambiguate by stored id.
        if getattr(self, "_id", None):
            return {"id": self._id, "threadId": "t1", "snippet": "hi",
                    "payload": {"headers": [{"name": "From", "value": "a@acme.com"},
                                            {"name": "Subject", "value": "Interview"}]}}
        return {"messages": [{"id": "m123"}]}

class _FakeUsers:
    def messages(self): return _FakeMessages()

class _FakeService:
    def users(self): return _FakeUsers()


def test_fetch_populates_message_id():
    msgs = fetch_recent_messages(_FakeService(), max_results=1)
    assert msgs[0].message_id == "m123"


def test_email_message_accepts_message_id():
    assert EmailMessage(sender="a@b.com", sender_domain="b.com", subject="s",
                        snippet="x", message_id="m1").message_id == "m1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_client.py -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'message_id'`).

- [ ] **Step 3: Add the field and populate it**

In `EmailMessage` (after `thread_id`):

```python
    message_id: str | None = None
```

In `fetch_recent_messages`, set it on construction:

```python
        messages.append(
            EmailMessage(
                sender=sender,
                sender_domain=_domain(sender),
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                thread_id=msg.get("threadId"),
                message_id=ref["id"],
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/gmail/client.py tests/test_gmail_client.py
git commit -m "feat: surface Gmail message_id on EmailMessage"
```

---

### Task 2: `Notification` table

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py` (add `Notification` at end)
- Test: `tests/test_tracking_repository.py` (append)

**Interfaces:**

- Produces: `Notification(id, application_id, kind, proposed_status, evidence, message_id, state, created_at)` with `state` default `"pending"`. Created via `SQLModel.metadata.create_all` (new table — no ALTER migration needed).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tracking_repository.py
def test_notification_table_roundtrip():
    from sqlmodel import Session
    from resume_tailor_harness.db import init_db, make_engine
    from resume_tailor_harness.tracking.tables import Notification
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        n = Notification(application_id=1, kind="interview", proposed_status="interview",
                         evidence="Next steps", message_id="m1")
        s.add(n); s.commit(); s.refresh(n)
        assert n.state == "pending"
        assert n.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_repository.py::test_notification_table_roundtrip -v`
Expected: FAIL (`ImportError: cannot import name 'Notification'`).

- [ ] **Step 3: Add the model**

Append to `src/resume_tailor_harness/tracking/tables.py`:

```python
class Notification(SQLModel, table=True):
    __tablename__ = cast(Any, "notifications")

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)
    kind: str
    proposed_status: str
    evidence: str
    message_id: str = Field(index=True)
    state: str = Field(default="pending", index=True)  # pending | accepted | dismissed
    created_at: datetime = Field(default_factory=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_repository.py::test_notification_table_roundtrip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py tests/test_tracking_repository.py
git commit -m "feat: Notification table for Gmail-derived proposals"
```

---

### Task 3: Carry `message_id` on `Proposal`

**Files:**

- Modify: `src/resume_tailor_harness/gmail/propose.py:16-23` (`Proposal`), `:33-59` (`propose_transitions`)
- Test: `tests/test_gmail_propose.py` (append; mirror existing propose tests)

**Interfaces:**

- Produces: `Proposal.message_id: str` carried from the matching email, so the sync upsert has its dedup key.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_propose.py  (append)
from resume_tailor_harness.gmail.client import EmailMessage
from resume_tailor_harness.gmail.propose import propose_transitions
from resume_tailor_harness.tracking.tables import Application, Job


def test_proposal_carries_message_id():
    email = EmailMessage(sender="r@acme.com", sender_domain="acme.com",
                         subject="Interview at Acme", snippet="schedule a call",
                         message_id="m999")
    job = Job(id=1, company="Acme", title="Eng")
    app = Application(id=10, job_id=1, status="submitted")
    out = propose_transitions([email], [(app, job)], lambda e: "interview")
    assert out and out[0].message_id == "m999"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_propose.py::test_proposal_carries_message_id -v`
Expected: FAIL (`TypeError: __init__() ... 'message_id'` / `AttributeError`).

- [ ] **Step 3: Add the field and populate it**

In `Proposal` dataclass add `message_id: str`. In `propose_transitions`, the `proposals.append(...)` call becomes:

```python
        proposals.append(
            Proposal(
                app.id, f"{job.company} - {job.title}", app.status, proposed,
                email.subject, email.message_id or "",
            )
        )
```

(Field order: keep existing positional order and append `message_id` last; update the dataclass field order to match.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_propose.py -v`
Expected: PASS (existing propose tests still green — they ignore the new field or need the extra arg; if a test constructs `Proposal(...)` directly, add the `message_id` arg there).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/gmail/propose.py tests/test_gmail_propose.py
git commit -m "feat: carry message_id on gmail Proposal"
```

---

### Task 4: Notifications service (sync upsert + accept + dismiss + list)

**Files:**

- Create: `src/resume_tailor_harness/services/notifications.py`
- Modify: `src/resume_tailor_harness/tracking/repository.py` (add `notification_by_key`, `pending_notifications`, `save_notification`, `get_notification`)
- Test: `tests/test_services_notifications.py`

**Interfaces:**

- Consumes: `application_job_pairs`, `propose_transitions`, `classify_email`, `update_application_status`.
- Produces:
  - `sync_notifications(session, emails, *, classify=classify_email) -> list[Notification]` — upsert by `(application_id, message_id)`; returns all pending after sync.
  - `accept_notification(session, notification_id) -> Notification | None` — applies `update_application_status`, sets `state="accepted"`.
  - `dismiss_notification(session, notification_id) -> Notification | None` — sets `state="dismissed"`.
  - `list_pending(session) -> list[Notification]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_notifications.py
from sqlmodel import Session
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.gmail.client import EmailMessage
from resume_tailor_harness.services.notifications import (
    accept_notification, dismiss_notification, list_pending, sync_notifications,
)
from resume_tailor_harness.tracking.repository import save_application, save_job
from resume_tailor_harness.tracking.tables import Application, Job


def _seed(s):
    job = save_job(s, Job(source="url", company="Acme", title="Eng"))
    app = save_application(s, Application(job_id=job.id, status="submitted"))
    return job, app


def _email(mid):
    return EmailMessage(sender="r@acme.com", sender_domain="acme.com",
                        subject="Interview at Acme", snippet="schedule a call", message_id=mid)


def test_sync_creates_pending_and_is_idempotent():
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        _seed(s)
        first = sync_notifications(s, [_email("m1")], classify=lambda e: "interview")
        assert len(first) == 1
        # Re-sync the same email: no duplicate.
        again = sync_notifications(s, [_email("m1")], classify=lambda e: "interview")
        assert len(again) == 1


def test_accept_applies_transition_and_dismiss_suppresses():
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        job, app = _seed(s)
        [n] = sync_notifications(s, [_email("m1")], classify=lambda e: "interview")
        accepted = accept_notification(s, n.id)
        assert accepted.state == "accepted"
        from resume_tailor_harness.tracking.repository import get_application
        assert get_application(s, app.id).status == "interview"
        # A dismissed proposal stays out of pending even after re-sync.
        [n2] = sync_notifications(s, [_email("m2")], classify=lambda e: "interview")
        dismiss_notification(s, n2.id)
        sync_notifications(s, [_email("m2")], classify=lambda e: "interview")
        assert all(p.message_id != "m2" for p in list_pending(s))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_notifications.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Add repository helpers**

Append to `src/resume_tailor_harness/tracking/repository.py` (ensure `Notification` is imported):

```python
def save_notification(session: Session, notification: Notification) -> Notification:
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification


def get_notification(session: Session, notification_id: int) -> Notification | None:
    return session.get(Notification, notification_id)


def notification_by_key(
    session: Session, application_id: int, message_id: str
) -> Notification | None:
    return session.exec(
        select(Notification).where(
            Notification.application_id == application_id,
            Notification.message_id == message_id,
        )
    ).first()


def pending_notifications(session: Session) -> list[Notification]:
    return list(session.exec(select(Notification).where(Notification.state == "pending")).all())
```

- [ ] **Step 4: Implement the service**

```python
# src/resume_tailor_harness/services/notifications.py
"""Surface inbound Gmail proposals as reviewable, persisted notifications."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from sqlmodel import Session

from resume_tailor_harness.gmail.classify import classify_email
from resume_tailor_harness.gmail.client import EmailMessage
from resume_tailor_harness.gmail.propose import propose_transitions
from resume_tailor_harness.tracking.queries import application_job_pairs
from resume_tailor_harness.tracking.repository import (
    get_notification, notification_by_key, pending_notifications,
    save_notification, update_application_status,
)
from resume_tailor_harness.tracking.tables import Notification


def sync_notifications(
    session: Session,
    emails: Sequence[EmailMessage],
    *,
    classify: Callable[[EmailMessage], str] = classify_email,
) -> list[Notification]:
    """Upsert a Notification per proposal, keyed (application_id, message_id)."""
    pairs = application_job_pairs(session)
    for proposal in propose_transitions(emails, pairs, classify):
        if not proposal.message_id:
            continue
        existing = notification_by_key(session, proposal.application_id, proposal.message_id)
        if existing is not None:
            continue  # already pending/accepted/dismissed — never resurrect
        save_notification(session, Notification(
            application_id=proposal.application_id,
            kind=proposal.proposed_status,
            proposed_status=proposal.proposed_status,
            evidence=proposal.evidence,
            message_id=proposal.message_id,
        ))
    return pending_notifications(session)


def accept_notification(session: Session, notification_id: int) -> Notification | None:
    n = get_notification(session, notification_id)
    if n is None:
        return None
    update_application_status(session, n.application_id, n.proposed_status)
    n.state = "accepted"
    return save_notification(session, n)


def dismiss_notification(session: Session, notification_id: int) -> Notification | None:
    n = get_notification(session, notification_id)
    if n is None:
        return None
    n.state = "dismissed"
    return save_notification(session, n)


def list_pending(session: Session) -> list[Notification]:
    return pending_notifications(session)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_notifications.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/services/notifications.py src/resume_tailor_harness/tracking/repository.py tests/test_services_notifications.py
git commit -m "feat: notifications service with idempotent gmail sync, accept, dismiss"
```

---

### Task 5: API — notifications schemas, list/accept/dismiss router, Gmail-sync Run

**Files:**

- Create: `src/resume_tailor_harness/api/schemas/notifications.py`
- Create: `src/resume_tailor_harness/api/routers/notifications.py`
- Modify: `src/resume_tailor_harness/api/routers/runs.py` (add `launch_gmail_sync`)
- Modify: `src/resume_tailor_harness/api/app.py` (register notifications router)
- Test: `tests/api/test_notifications.py`

**Interfaces:**

- Consumes: `list_pending`, `accept_notification`, `dismiss_notification` (Task 4); `build_gmail_service`, `fetch_recent_messages`, `sync_notifications`.
- Produces:
  - `NotificationOut{id, application_id, kind, proposed_status, evidence, message_id, state, created_at}`.
  - `GET /api/notifications` → `list[NotificationOut]` (pending).
  - `POST /api/notifications/{id}/accept` → `NotificationOut`.
  - `POST /api/notifications/{id}/dismiss` → `NotificationOut`.
  - `POST /api/gmail/sync` → `202 RunOut` (kind `"gmailSync"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_notifications.py
def test_list_accept_dismiss(client, seed_application):
    # seed_application: persists a Job + Application, returns application id.
    from resume_tailor_harness.api.routers import notifications as N
    app_id = seed_application

    # Seed one pending notification directly via the service-less path.
    from resume_tailor_harness.tracking.tables import Notification
    from resume_tailor_harness.tracking.repository import save_notification
    with client.app_session() as s:  # helper exposing a Session on the test engine
        n = save_notification(s, Notification(
            application_id=app_id, kind="interview", proposed_status="interview",
            evidence="Next steps", message_id="m1"))
        nid = n.id

    listed = client.get("/api/notifications").json()
    assert any(x["id"] == nid for x in listed)

    accepted = client.post(f"/api/notifications/{nid}/accept").json()
    assert accepted["state"] == "accepted"
```

(Adapt `seed_application` / `app_session` to the existing api test harness — read `tests/api/conftest.py` first and reuse its engine/session fixtures; if it exposes the engine, open a `Session(engine)` directly instead of `client.app_session()`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_notifications.py -v`
Expected: FAIL (404 / no module).

- [ ] **Step 3: Add the schema**

```python
# src/resume_tailor_harness/api/schemas/notifications.py
from __future__ import annotations

from datetime import datetime

from resume_tailor_harness.api.schemas.base import CamelModel


class NotificationOut(CamelModel):
    id: int
    application_id: int
    kind: str
    proposed_status: str
    evidence: str
    message_id: str
    state: str
    created_at: datetime
```

- [ ] **Step 4: Add the notifications router**

```python
# src/resume_tailor_harness/api/routers/notifications.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.notifications import NotificationOut
from resume_tailor_harness.services.notifications import (
    accept_notification, dismiss_notification, list_pending,
)

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(session: Session = Depends(get_session)):
    return [NotificationOut.model_validate(n) for n in list_pending(session)]


@router.post("/notifications/{notification_id}/accept", response_model=NotificationOut)
def accept(notification_id: int, session: Session = Depends(get_session)):
    n = accept_notification(session, notification_id)
    if n is None:
        raise ApiException(404, "NOT_FOUND", f"Notification #{notification_id} not found")
    return NotificationOut.model_validate(n)


@router.post("/notifications/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss(notification_id: int, session: Session = Depends(get_session)):
    n = dismiss_notification(session, notification_id)
    if n is None:
        raise ApiException(404, "NOT_FOUND", f"Notification #{notification_id} not found")
    return NotificationOut.model_validate(n)
```

- [ ] **Step 5: Add the Gmail-sync Run**

In `src/resume_tailor_harness/api/routers/runs.py`, mirror `launch_pull`:

```python
@router.post("/gmail/sync", response_model=RunOut, status_code=202)
def launch_gmail_sync(request: Request, mgr: RunManager = Depends(get_run_manager)):
    engine = _engine(request)

    def work(reporter):
        from resume_tailor_harness.gmail.client import build_gmail_service, fetch_recent_messages
        from resume_tailor_harness.services.notifications import sync_notifications
        reporter.begin(1, "Scanning Gmail")
        service = build_gmail_service()
        emails = fetch_recent_messages(service)
        with get_session(engine) as session:
            pending = sync_notifications(session, emails)
        reporter.step(1)
        return {"pending": len(pending)}

    run_id = mgr.submit("gmailSync", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
```

- [ ] **Step 6: Register the notifications router**

In `src/resume_tailor_harness/api/app.py`: `from resume_tailor_harness.api.routers import notifications as notifications_router` and `app.include_router(notifications_router.router, prefix="/api", dependencies=guarded)`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_notifications.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/resume_tailor_harness/api/ tests/api/test_notifications.py
git commit -m "feat: notifications API + gmail-sync run endpoint"
```

---

### Task 6: Regenerate API contracts

**Files:**

- Modify: `contracts/openapi.json`, `contracts/ts/api.ts`
- Verify: `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Regenerate**

Run: `bash scripts/gen_ts_client.sh`

- [ ] **Step 2: Verify drift gate + full suite**

Run: `.venv/Scripts/python.exe -m pytest` then `ruff check`
Expected: all PASS, lint clean.

- [ ] **Step 3: Commit**

```bash
git add contracts/
git commit -m "chore: regenerate contracts for notifications endpoints"
```

---

### Task 7: Frontend — notifications hooks

**Files:**

- Create: `web/src/features/notifications/use-notifications.ts`
- Test: `web/src/features/notifications/use-notifications.test.tsx`

**Interfaces:**

- Produces: `useNotifications()` (query `GET /api/notifications`, key `["notifications"]`), `useAcceptNotification()`, `useDismissNotification()`, `useGmailSync()` (POST `/api/gmail/sync`) — accept/dismiss/sync invalidate `["notifications"]`.

- [ ] **Step 1: Write the failing test**

Mirror an existing feature hook test (e.g. `web/src/features/sources/`); assert `useNotifications` fetches `/api/notifications` and `useAcceptNotification` POSTs to `/accept` then invalidates. Read a neighboring `*.test.tsx` for the project's query-client + fetch-mock harness.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/notifications/use-notifications.test.tsx`
Expected: FAIL (no module).

- [ ] **Step 3: Implement the hooks**

```ts
// web/src/features/notifications/use-notifications.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api/client"; // match the real helper names
import type { components } from "@/lib/api/schema";

type Notification = components["schemas"]["NotificationOut"];
const KEY = ["notifications"];

export function useNotifications() {
  return useQuery<Notification[]>({
    queryKey: KEY,
    queryFn: () => apiGet("/api/notifications"),
  });
}

export function useAcceptNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPost(`/api/notifications/${id}/accept`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDismissNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPost(`/api/notifications/${id}/dismiss`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useGmailSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/api/gmail/sync", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
```

(Adapt `apiGet`/`apiPost` to the helpers actually exported by `@/lib/api/client` — read it first.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/notifications/use-notifications.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/notifications/
git commit -m "feat: notifications query + mutation hooks"
```

---

### Task 8: Frontend — notifications bell + inbox

**Files:**

- Create: `web/src/features/notifications/NotificationsBell.tsx`
- Modify: `web/src/app/AppLayout.tsx` (mount the bell in the header)
- Test: `web/src/features/notifications/NotificationsBell.test.tsx`

**Interfaces:**

- Consumes: `useNotifications`, `useAcceptNotification`, `useDismissNotification`, `useGmailSync` (Task 7).
- Produces: a header control showing a pending-count badge; opening it lists each pending notification with its `evidence` + proposed transition and Accept / Dismiss buttons, plus a "Sync Gmail" button.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/notifications/NotificationsBell.test.tsx
import { render, screen } from "@testing-library/react";
import { NotificationsBell } from "./NotificationsBell";
// wrap with the project's QueryClientProvider helper; mock useNotifications to
// return one pending item (or mock the fetch layer the other tests use).

it("shows the pending count badge", async () => {
  renderWithClient(<NotificationsBell />); // with one mocked pending notification
  expect(await screen.findByText("1")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/notifications/NotificationsBell.test.tsx`
Expected: FAIL (no module).

- [ ] **Step 3: Implement the bell**

```tsx
// web/src/features/notifications/NotificationsBell.tsx
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import {
  useAcceptNotification,
  useDismissNotification,
  useGmailSync,
  useNotifications,
} from "./use-notifications";

export function NotificationsBell() {
  const { data: items = [] } = useNotifications();
  const accept = useAcceptNotification();
  const dismiss = useDismissNotification();
  const sync = useGmailSync();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="relative"
          aria-label="Notifications"
        >
          🔔
          {items.length > 0 && (
            <span
              className="absolute -right-1 -top-1 rounded-full bg-primary px-1.5 text-xs
              font-semibold text-primary-foreground"
            >
              {items.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold">Notifications</span>
          <Button
            size="sm"
            variant="outline"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            {sync.isPending ? "Syncing…" : "Sync Gmail"}
          </Button>
        </div>
        {items.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing pending.</p>
        )}
        <ul className="space-y-2">
          {items.map((n) => (
            <li key={n.id} className="rounded-lg border p-2 text-sm">
              <div className="font-medium">→ {n.proposedStatus}</div>
              <div className="text-xs text-muted-foreground">{n.evidence}</div>
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => accept.mutate(n.id)}>
                  Accept
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => dismiss.mutate(n.id)}
                >
                  Dismiss
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 4: Mount it in the header**

In `web/src/app/AppLayout.tsx`, import `NotificationsBell` and render `<NotificationsBell />` in the top bar (near the theme toggle — read the file to find the header element).

- [ ] **Step 5: Run test + typecheck**

Run: `cd web && npx vitest run src/features/notifications/NotificationsBell.test.tsx && npx tsc --noEmit`
Expected: PASS / no type errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/notifications/NotificationsBell.tsx web/src/app/AppLayout.tsx web/src/features/notifications/NotificationsBell.test.tsx
git commit -m "feat: notifications bell with accept/dismiss and Gmail sync"
```

---

### Task 9: Full verification pass

- [ ] **Step 1: Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest` then `ruff check`
Expected: all PASS, lint clean.

- [ ] **Step 2: Frontend suite + typecheck + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all PASS, build succeeds.

- [ ] **Step 3: Commit (if cleanup)**

```bash
git add -A && git commit -m "chore: phase-3 notifications verification"
```

---

## Self-Review

**Spec coverage (Phase 3):**

- Sync as Run + SSE → Task 5 (`launch_gmail_sync`, kind `gmailSync`). ✓
- `Notification` table `{application_id, kind, proposed_status, evidence, message_id, state, created_at}` → Task 2. ✓
- Idempotent upsert on `(application_id, message_id)` → Task 4 (`test_sync_creates_pending_and_is_idempotent`, `notification_by_key`). ✓
- `message_id` surfaced on `EmailMessage` (not `thread_id`) → Task 1; carried via `Proposal` → Task 3. ✓
- Accept applies transition + `accepted`; dismiss suppresses forever → Task 4 (`test_accept_applies_transition_and_dismiss_suppresses`). ✓
- Human-gated (no auto-apply) → service only changes status on explicit `accept_notification`. ✓
- Frontend notifications surface (badge + inbox, accept/dismiss, sync) → Tasks 7, 8. ✓
- Contract regen → Task 6. ✓

**Placeholder scan:** none. Tasks 5/7/8 instruct mirroring existing test harnesses (`conftest`, neighboring feature tests) — deliberate reuse of an existing fixture layer, not missing logic.

**Type consistency:** `sync_notifications(session, emails, *, classify=...)` called identically in Task 5's run. `accept_notification`/`dismiss_notification(session, id) -> Notification | None` match between Tasks 4 and 5. `Proposal.message_id` (Task 3) is the field `sync_notifications` reads (Task 4). `NotificationOut` camelCase fields (`proposedStatus`, `messageId`) consumed in the Task 8 component (`n.proposedStatus`). Run kind string `"gmailSync"` is the only literal; no other task depends on it.
