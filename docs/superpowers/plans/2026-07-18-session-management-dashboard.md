# Session Management + Dashboard Upgrade Implementation Plan

> **Execution mode:** Implement task-by-task in one agent with test-driven development. Do not delegate this plan to subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Session management (resume/archive/delete) for Mock Interview and Profile Coach, per-job concurrent interviews with an Interview hub page, and durable user-clearable error records surfaced on the dashboard.

**Architecture:** Interview/coach sessions stay file-based JSON stores gaining `archived_at` + management mutations; the interview single-active guard becomes per-job and turn runs get per-session singleton keys. A new `error_records` table in the workspace DB is fed by a `RunManager` error hook and the pull/refresh work functions. FastAPI routers stay thin adapters; the SPA gets a sessions rail on `/interview`, actions on the coach Past-sessions block, and two dashboard cards.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLite, pydantic CamelModel contract (openapi-typescript), React + TanStack Query + shadcn-style UI kit, vitest.

**Spec:** `docs/superpowers/specs/2026-07-18-session-management-dashboard-design.md`

## Global Constraints

- Tests are offline: `.venv/Scripts/python.exe -m pytest` (backend), `cd web && npx vitest run <file>` (frontend). No API keys, no network.
- Lint: `ruff check` must stay clean.
- Wire format is **camelCase** via `CamelModel`; Python stays snake_case.
- After any change to `api/schemas/*` or router signatures, run `bash scripts/gen_ts_client.sh` and commit the regenerated `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`. `tests/api/test_openapi_contract.py` is the drift gate.
- Run workers open their **own** DB session on the app engine — never a request session.
- Archive is **ended-sessions-only**; deleting an active session is the abandon path.
- Coach stays single-active globally; interviews are one-active-per-job.
- Errors use the `ApiException` envelope; 404 unknown / 409 conflict / 422 validation.
- Keep commits truthful and scoped. Do not add third-party co-author or session
  provenance trailers unless that party actually contributed to the commit.

## Correctness Amendments (binding)

These amendments override conflicting snippets in the tasks below.

1. **Keep intermediate commits import-safe.** Task 1 retains `active_session()` as
   a compatibility projection over `active_sessions()` while Task 3 migrates the
   router to `active_session_for_job()`. Do not deliberately leave the repository
   with a broken import between tasks.
2. **Validate list filters at the HTTP boundary.** Interview and coach `status`
   query parameters are typed as `Literal["active", "ended"] | None`; invalid
   values return the standard 422 envelope instead of a misleading empty list.
3. **Preserve source-run attribution.** `record_source_failures` accepts and
   persists the producing `run_id`; pull and refresh pass `reporter.run_id` so
   `ErrorRecord.run_id` satisfies the design contract.
4. **Make in-process dedup atomic.** Error-record lookup/increment/insert is
   serialized around the complete transaction so concurrent RunManager workers
   cannot create duplicate open `(kind, source_label)` rows or lose increments.
   Add a concurrency regression test.
5. **Recovery must use the correct user database.** The app error hook may use
   `current_context().engine` for a live worker, but startup recovery has no active
   request context. For a recovery payload with `userId`, first validate the user
   against the system database, then resolve that user's workspace engine through
   `EngineRegistry`; do not silently discard the record or write it to the admin
   workspace.
6. **Base UI composition is authoritative.** This repository uses shadcn
   `base-nova` + Base UI. New selects provide `items` on `<Select>`, put
   `SelectItem` inside `SelectGroup`, and use a null placeholder item. Menu items
   live inside `DropdownMenuGroup`; link-rendered Buttons set
   `nativeButton={false}`; Switch controls use labelled `Field` composition; new
   layout uses `gap-*`, not `space-y-*`, and icons inside shadcn controls use
   `data-icon` without manual sizing classes.
7. **Every new query surface has loading, error, and empty states.** In
   particular, SessionsRail, NewInterviewDialog's job/detail queries, coach
   history management, and AttentionCard must expose retryable errors rather than
   collapsing failures into empty UI.
8. **Session actions clear stale selection.** After deleting the selected
   interview, navigate to `/interview` (replace history) after the mutation
   succeeds. Coach archive/delete actions cover the currently displayed ended
   session and active-session abandonment as well as past rows, and clear local
   selection after a successful mutation so removed/hidden detail is not retained.
9. **Preserve the existing Agno boundary.** Interview and coach history remains
   the application's validated file transcript rendered into each turn. Do not
   introduce Agno DB history or reuse an Agno `session_id`; per-session RunManager
   singleton keys provide concurrency without changing agent memory semantics.
10. **Final verification is broader than Task 15's draft commands.** Run the full
    Python suite, `ruff check`, OpenAPI regeneration/drift check, full Vitest,
    TypeScript, web lint, production web build, `git diff --check`, and a Playwright
    browser walkthrough of the dashboard, interview hub, and coach management
    flows at representative desktop and mobile widths. Review the final diff on
    correctness, security, performance, accessibility, and simplicity, then rerun
    affected checks after any refactor.

---

### Task 1: Interview store — archived_at, per-job active, archive/unarchive/delete

**Files:**

- Modify: `src/resume_agent/interview/store.py`
- Test: `tests/test_interview_store.py` (exists — append tests)

**Interfaces:**

- Produces: `active_sessions(interview_dir) -> list[dict]`, `active_session_for_job(interview_dir, job_id: int) -> dict | None`, `archive_session(interview_dir, session_id) -> dict`, `unarchive_session(interview_dir, session_id) -> dict`, `delete_session(interview_dir, session_id) -> None`, `list_sessions(interview_dir, job_id=None, *, include_archived=False) -> list[dict]`. `InterviewSession` gains `archived_at: str | None`. **Removes** `active_session()` (Task 3 updates its one caller, `api/routers/interview.py` — expect that module's tests to fail until Task 3; run only the store tests here).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_interview_store.py`. The snippets below assume a helper `_make_session(tmp_path, session_id, job_id)` — if the file already has an equivalent factory, use it; otherwise add:

```python
def _make_session(interview_dir, session_id: str, *, job_id: int) -> None:
    create_session(
        interview_dir,
        session_id,
        job_id=job_id,
        resume_version_id=1,
        style=InterviewStyle(),
        context=InterviewContext(company="Acme", title="SWE"),
        plan=[PlanItem(id="q1", competency="ownership", question_type="behavioral")],
        opening_turn=InterviewTurnRecord(
            role="interviewer", text="Tell me about a project.", question_id="q1"
        ),
    )
```

```python
from resume_agent.interview.store import (
    active_session_for_job,
    active_sessions,
    archive_session,
    delete_session,
    unarchive_session,
)


def _end(tmp_path, session_id):
    end_with_debrief(tmp_path, session_id, InterviewDebrief(summary="done"))


def test_two_jobs_can_have_active_sessions(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    _make_session(tmp_path, "s2", job_id=2)
    assert {row["session_id"] for row in active_sessions(tmp_path)} == {"s1", "s2"}


def test_second_active_session_for_same_job_rejected(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    with pytest.raises(ValueError, match="active session exists for job"):
        _make_session(tmp_path, "s2", job_id=1)


def test_active_session_for_job_scopes_by_job(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    assert active_session_for_job(tmp_path, 1)["session_id"] == "s1"
    assert active_session_for_job(tmp_path, 2) is None


def test_archive_requires_ended_and_hides_from_default_list(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    with pytest.raises(ValueError, match="only ended sessions"):
        archive_session(tmp_path, "s1")
    _end(tmp_path, "s1")
    row = archive_session(tmp_path, "s1")
    assert row["archived_at"]
    assert list_sessions(tmp_path) == []
    assert [r["session_id"] for r in list_sessions(tmp_path, include_archived=True)] == ["s1"]


def test_unarchive_restores_listing(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    _end(tmp_path, "s1")
    archive_session(tmp_path, "s1")
    assert unarchive_session(tmp_path, "s1")["archived_at"] is None
    assert [r["session_id"] for r in list_sessions(tmp_path)] == ["s1"]
    with pytest.raises(ValueError, match="not archived"):
        unarchive_session(tmp_path, "s1")


def test_delete_session_removes_file_even_when_active(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    delete_session(tmp_path, "s1")
    assert list_sessions(tmp_path, include_archived=True) == []
    with pytest.raises(ValueError, match="unknown session"):
        delete_session(tmp_path, "s1")


def test_delete_sessions_for_job_includes_archived(tmp_path):
    _make_session(tmp_path, "s1", job_id=1)
    _end(tmp_path, "s1")
    archive_session(tmp_path, "s1")
    assert delete_sessions_for_job(tmp_path, 1) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_interview_store.py -q`
Expected: ImportError (`active_sessions` not defined).

- [ ] **Step 3: Implement**

In `src/resume_agent/interview/store.py`:

1. Add field to `InterviewSession` (after `concluded`):

```python
    archived_at: str | None = None
```

1. Replace `list_sessions` and `active_session` with:

```python
def list_sessions(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
) -> list[dict]:
    root = Path(interview_dir)
    if not root.exists():
        return []
    sessions = [_read(path) for path in root.glob("session-*.json")]
    if job_id is not None:
        sessions = [row for row in sessions if row["job_id"] == job_id]
    if not include_archived:
        sessions = [row for row in sessions if not row["archived_at"]]
    return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))


def active_sessions(interview_dir: Path | str) -> list[dict]:
    return [
        row for row in list_sessions(interview_dir) if row["status"] == "active"
    ]


def active_session_for_job(interview_dir: Path | str, job_id: int) -> dict | None:
    return next(
        (row for row in active_sessions(interview_dir) if row["job_id"] == job_id),
        None,
    )
```

1. In `create_session`, replace the guard `if active_session(interview_dir) is not None: raise ValueError("active session exists")` with:

```python
        if active_session_for_job(interview_dir, job_id) is not None:
            raise ValueError(f"active session exists for job {job_id}")
```

1. Add after `end_with_debrief`:

```python
def archive_session(interview_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "ended":
            raise ValueError("only ended sessions can be archived")
        if session["archived_at"]:
            raise ValueError("session already archived")
        session["archived_at"] = _now()

    return mutate_session(interview_dir, session_id, apply)


def unarchive_session(interview_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if not session["archived_at"]:
            raise ValueError("session not archived")
        session["archived_at"] = None

    return mutate_session(interview_dir, session_id, apply)


def delete_session(interview_dir: Path | str, session_id: str) -> None:
    """Permanently remove a session file. Deleting an active session abandons it."""
    with interview_lock():
        path = _session_path(interview_dir, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        path.unlink()
```

1. In `delete_sessions_for_job`, change the loop source to include archived rows:

```python
        for row in list_sessions(interview_dir, job_id=job_id, include_archived=True):
```

- [ ] **Step 4: Run store tests — pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_interview_store.py -q`
Expected: all pass. (`tests/api/test_interview_router.py` and `tests/test_mock_interview_service.py` may fail on the removed `active_session` import — fixed in Task 3; do not run the full suite yet.)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/interview/store.py tests/test_interview_store.py
git commit -m "feat(interview): per-job active sessions + archive/unarchive/delete"
```

---

### Task 2: Coach store — archived_at + archive/unarchive/delete

**Files:**

- Modify: `src/resume_agent/profile/coach_store.py`
- Test: `tests/test_coach_store.py` (exists — append tests)

**Interfaces:**

- Produces: `archive_session(profile_dir, session_id) -> dict`, `unarchive_session(profile_dir, session_id) -> dict`, `delete_session(profile_dir, session_id) -> None`, `list_sessions(profile_dir, *, include_archived=False)`. `CoachSession` gains `archived_at: str | None`. `active_session()` and single-active `create_session` guard are **unchanged**.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coach_store.py`, reusing its session factory (a `create_session` call with one topic + matching opening turn; assume/add helper `_make_session(tmp_path, "s1")` mirroring existing tests, and end via `end_session(tmp_path, "s1", "recap")`):

```python
from resume_agent.profile.coach_store import (
    archive_session,
    delete_session,
    unarchive_session,
)


def test_archive_requires_ended_and_hides_by_default(tmp_path):
    _make_session(tmp_path, "s1")
    with pytest.raises(ValueError, match="only ended sessions"):
        archive_session(tmp_path, "s1")
    end_session(tmp_path, "s1", "recap")
    assert archive_session(tmp_path, "s1")["archived_at"]
    assert list_sessions(tmp_path) == []
    assert [r["session_id"] for r in list_sessions(tmp_path, include_archived=True)] == ["s1"]


def test_unarchive_roundtrip(tmp_path):
    _make_session(tmp_path, "s1")
    end_session(tmp_path, "s1", "recap")
    archive_session(tmp_path, "s1")
    assert unarchive_session(tmp_path, "s1")["archived_at"] is None
    with pytest.raises(ValueError, match="not archived"):
        unarchive_session(tmp_path, "s1")


def test_delete_session_any_status(tmp_path):
    _make_session(tmp_path, "s1")
    delete_session(tmp_path, "s1")
    assert list_sessions(tmp_path, include_archived=True) == []
    with pytest.raises(ValueError, match="unknown session"):
        delete_session(tmp_path, "s1")


def test_archived_ended_session_does_not_block_new_active(tmp_path):
    _make_session(tmp_path, "s1")
    end_session(tmp_path, "s1", "recap")
    archive_session(tmp_path, "s1")
    _make_session(tmp_path, "s2")  # must not raise
    assert active_session(tmp_path)["session_id"] == "s2"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_coach_store.py -q`
Expected: ImportError (`archive_session` not defined).

- [ ] **Step 3: Implement**

In `src/resume_agent/profile/coach_store.py`:

1. Add to `CoachSession` (after `status`): `archived_at: str | None = None`
2. Update `list_sessions`:

```python
def list_sessions(
    profile_dir: Path | str, *, include_archived: bool = False
) -> list[dict]:
    root = coach_dir(profile_dir)
    if not root.exists():
        return []
    sessions = [_read(path) for path in root.glob("session-*.json")]
    if not include_archived:
        sessions = [row for row in sessions if not row["archived_at"]]
    return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))
```

Note: `active_session()` filters on `status == "active"`, and archive requires `status == "ended"`, so an archived row can never be active — the single-active guard is unaffected.

1. Append the same three mutations as the interview store, but locked with `coach_lock()` and pathed with this module's `_session_path`:

```python
def archive_session(profile_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "ended":
            raise ValueError("only ended sessions can be archived")
        if session["archived_at"]:
            raise ValueError("session already archived")
        session["archived_at"] = _now()

    return mutate_session(profile_dir, session_id, apply)


def unarchive_session(profile_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if not session["archived_at"]:
            raise ValueError("session not archived")
        session["archived_at"] = None

    return mutate_session(profile_dir, session_id, apply)


def delete_session(profile_dir: Path | str, session_id: str) -> None:
    """Remove the transcript record only — saved notes are corpus documents."""
    with coach_lock():
        path = _session_path(profile_dir, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        path.unlink()
```

- [ ] **Step 4: Run tests — pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_coach_store.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/coach_store.py tests/test_coach_store.py
git commit -m "feat(coach): session archive/unarchive/delete with archived_at"
```

---

### Task 3: Interview service views + router management endpoints

**Files:**

- Modify: `src/resume_agent/services/mock_interview.py`
- Modify: `src/resume_agent/api/routers/interview.py`
- Modify: `src/resume_agent/api/schemas/interview.py`
- Test: `tests/api/test_interview_router.py` (append), `tests/test_mock_interview_service.py` (fix imports if any)

**Interfaces:**

- Consumes: Task 1 store functions.
- Produces: `sessions_view(interview_dir, job_id=None, *, include_archived=False, status=None) -> dict` (rows gain `"archivedAt"`); `session_view` detail gains `"archivedAt"`. Endpoints: `POST /api/interview/sessions/{session_id}/archive|unarchive` → `InterviewSessionOut`; `DELETE /api/interview/sessions/{session_id}` → 204; `GET /api/interview/sessions?jobId&includeArchived&status`; start conflict → 409 `SESSION_ACTIVE_FOR_JOB` with `details={"sessionId": ...}`. Schemas: `InterviewSessionOut.archived_at: str | None = None`, `InterviewSessionSummaryOut.archived_at: str | None = None`.

- [ ] **Step 1: Write failing router tests**

Append to `tests/api/test_interview_router.py`, following its `_client(tmp_path)` + `_seed(...)` helpers and its pattern of creating store sessions directly under the app data dir (`tmp_path / "data" / "interview"`). Where existing tests build a session via `create_session(...)`, reuse that helper; name it `_store_session` below:

```python
def test_start_conflicts_only_within_same_job(tmp_path):
    client = _client(tmp_path)
    # seed two jobs with resume versions via the existing _seed helper
    job_a, version_a = _seed(client)            # adapt to helper's actual signature
    job_b, version_b = _seed(client)
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "live-a", job_id=job_a)
    # same job -> 409 with the blocking session id
    res = client.post(
        "/api/interview/sessions",
        json={"jobId": job_a, "resumeVersionId": version_a, "style": {}},
    )
    assert res.status_code == 409
    body = res.json()["error"]
    assert body["code"] == "SESSION_ACTIVE_FOR_JOB"
    assert body["details"]["sessionId"] == "live-a"


def test_archive_lifecycle_and_filters(tmp_path):
    client = _client(tmp_path)
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "s1", job_id=1)
    end_with_debrief(interview_dir, "s1", InterviewDebrief(summary="done"))
    # archive an ended session
    res = client.post("/api/interview/sessions/s1/archive")
    assert res.status_code == 200
    assert res.json()["archivedAt"]
    # hidden by default, visible with includeArchived
    assert client.get("/api/interview/sessions").json()["sessions"] == []
    rows = client.get(
        "/api/interview/sessions", params={"includeArchived": "true"}
    ).json()["sessions"]
    assert [r["sessionId"] for r in rows] == ["s1"]
    # unarchive restores
    assert client.post("/api/interview/sessions/s1/unarchive").status_code == 200
    assert client.post("/api/interview/sessions/s1/unarchive").status_code == 409


def test_archive_active_session_conflicts(tmp_path):
    client = _client(tmp_path)
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "live", job_id=1)
    assert client.post("/api/interview/sessions/live/archive").status_code == 409


def test_delete_session(tmp_path):
    client = _client(tmp_path)
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "gone", job_id=1)
    assert client.delete("/api/interview/sessions/gone").status_code == 204
    assert client.delete("/api/interview/sessions/gone").status_code == 404


def test_status_filter(tmp_path):
    client = _client(tmp_path)
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "live", job_id=1)
    _store_session(interview_dir, "done", job_id=2)
    end_with_debrief(interview_dir, "done", InterviewDebrief(summary="x"))
    rows = client.get(
        "/api/interview/sessions", params={"status": "active"}
    ).json()["sessions"]
    assert [r["sessionId"] for r in rows] == ["live"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_interview_router.py -q`
Expected: new tests FAIL (404 on archive route / wrong conflict code); pre-existing tests may also fail on the `active_session` import — all fixed in Step 3.

- [ ] **Step 3: Implement**

`src/resume_agent/services/mock_interview.py`:

- Add `"archivedAt": session["archived_at"],` to both `_view` (after `"status"`) and each row in `sessions_view`.
- Change `sessions_view` signature and listing call:

```python
def sessions_view(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
    status: str | None = None,
) -> dict:
    rows = list_sessions(interview_dir, job_id=job_id, include_archived=include_archived)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return {"sessions": [ ...keep the file's existing per-row dict unchanged... for session in rows]}
```

(The per-row dict already exists in this function — keep every existing key and add `"archivedAt": session["archived_at"]`; only the listing/filter lines above are new.)

`src/resume_agent/api/schemas/interview.py`:

- Add `archived_at: str | None = None` to `InterviewSessionOut` and `InterviewSessionSummaryOut`.

`src/resume_agent/api/routers/interview.py`:

- Replace the `active_session` import with `active_session_for_job`, and import `archive_session, delete_session, unarchive_session` from the store.
- Change `_submit` to accept the key: `def _submit(manager, kind, work, *, singleton: str) -> RunOut:` and pass `singleton_key=singleton`. Call sites:
  - start: `_submit(manager, "mock-interview-open", ..., singleton=f"mock-interview-open:{payload.job_id}")`
  - messages: `_submit(manager, "mock-interview-turn", ..., singleton=f"mock-interview:{session_id}")`
  - end: `_submit(manager, "mock-interview-end", ..., singleton=f"mock-interview:{session_id}")`
- Replace the start guard:

```python
    existing = active_session_for_job(interview_dir, payload.job_id)
    if existing is not None:
        raise ApiException(
            409,
            "SESSION_ACTIVE_FOR_JOB",
            "An active interview session already exists for this job",
            details={"sessionId": existing["session_id"]},
        )
```

- Extend `_value_error`'s conflict-token tuple to `("session ended", "active session", "concluded", "archived", "only ended")`.
- Extend the list endpoint:

```python
@router.get("/interview/sessions", response_model=InterviewSessionsOut)
def list_interview_sessions(
    request: Request,
    job_id: int | None = Query(None, alias="jobId"),
    include_archived: bool = Query(False, alias="includeArchived"),
    status: str | None = Query(None),
):
    return InterviewSessionsOut.model_validate(
        sessions_view(
            get_interview_dir(request),
            job_id=job_id,
            include_archived=include_archived,
            status=status,
        )
    )
```

- Add the management endpoints:

```python
@router.post("/interview/sessions/{session_id}/archive", response_model=InterviewSessionOut)
def archive_interview_session(session_id: str, request: Request):
    interview_dir = get_interview_dir(request)
    try:
        archive_session(interview_dir, session_id)
        return InterviewSessionOut.model_validate(session_view(interview_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/interview/sessions/{session_id}/unarchive", response_model=InterviewSessionOut)
def unarchive_interview_session(session_id: str, request: Request):
    interview_dir = get_interview_dir(request)
    try:
        unarchive_session(interview_dir, session_id)
        return InterviewSessionOut.model_validate(session_view(interview_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/interview/sessions/{session_id}", status_code=204)
def delete_interview_session(session_id: str, request: Request):
    try:
        delete_session(get_interview_dir(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
```

Note: `_value_error` maps "unknown session"/"session not archived" — "not archived" contains no 404 token and hits the new "archived" conflict token → 409, which the unarchive test expects; "unknown session" contains "unknown" → 404.

- Fix any `active_session` import in `tests/test_mock_interview_service.py` (switch to `active_sessions`/`active_session_for_job` as needed).

- [ ] **Step 4: Regenerate contract + run tests**

Run: `bash scripts/gen_ts_client.sh`
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_interview_router.py tests/api/test_openapi_contract.py tests/test_mock_interview_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/mock_interview.py src/resume_agent/api/routers/interview.py src/resume_agent/api/schemas/interview.py contracts/ web/src/lib/api/schema.ts tests/
git commit -m "feat(api): interview session management endpoints + per-job concurrency"
```

---

### Task 4: Coach service views + router management endpoints

**Files:**

- Modify: `src/resume_agent/services/profile_coach.py` (`sessions_view` at line ~96, `session_view`)
- Modify: `src/resume_agent/api/routers/coach.py`
- Modify: `src/resume_agent/api/schemas/coach.py`
- Test: `tests/api/test_coach_router.py` (append)

**Interfaces:**

- Consumes: Task 2 store functions.
- Produces: `POST /api/profile/coach/sessions/{session_id}/archive|unarchive` → `CoachSessionOut`; `DELETE /api/profile/coach/sessions/{session_id}` → 204; `GET /api/profile/coach/sessions?includeArchived&status`. `CoachSessionSummaryOut.archived_at: str | None = None`, `CoachSessionOut.archived_at: str | None = None`.

- [ ] **Step 1: Write failing tests**

Append to `tests/api/test_coach_router.py`, mirroring its existing client/seed helpers (coach sessions live under `tmp_path / "data" / "profile" / "coach"`; reuse the file's session-factory helper, called `_store_session` below, and `end_session` from `resume_agent.profile.coach_store`):

```python
def test_coach_archive_lifecycle(tmp_path):
    client = _client(tmp_path)
    profile_dir = tmp_path / "data" / "profile"
    _store_session(profile_dir, "c1")
    end_session(profile_dir, "c1", "recap")
    assert client.post("/api/profile/coach/sessions/c1/archive").status_code == 200
    assert client.get("/api/profile/coach/sessions").json()["sessions"] == []
    rows = client.get(
        "/api/profile/coach/sessions", params={"includeArchived": "true"}
    ).json()["sessions"]
    assert rows[0]["sessionId"] == "c1" and rows[0]["archivedAt"]
    assert client.post("/api/profile/coach/sessions/c1/unarchive").status_code == 200


def test_coach_archive_active_conflicts(tmp_path):
    client = _client(tmp_path)
    profile_dir = tmp_path / "data" / "profile"
    _store_session(profile_dir, "c1")
    assert client.post("/api/profile/coach/sessions/c1/archive").status_code == 409


def test_coach_delete_session(tmp_path):
    client = _client(tmp_path)
    profile_dir = tmp_path / "data" / "profile"
    _store_session(profile_dir, "c1")
    assert client.delete("/api/profile/coach/sessions/c1").status_code == 204
    assert client.delete("/api/profile/coach/sessions/c1").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_coach_router.py -q`
Expected: new tests FAIL with 404/405 on the new routes.

- [ ] **Step 3: Implement**

`src/resume_agent/services/profile_coach.py`:

- `sessions_view` gains the same keyword filters and an `"archivedAt"` row field:

```python
def sessions_view(
    profile_dir: Path | str,
    *,
    include_archived: bool = False,
    status: str | None = None,
) -> dict:
    rows = list_sessions(profile_dir, include_archived=include_archived)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return {"sessions": [ ...keep the file's existing per-row dict unchanged... for session in rows]}
```

(Keep every existing key in the per-row dict at line ~99 and add `"archivedAt": session["archived_at"]`; only the listing/filter lines are new.)

- Add `"archivedAt": session["archived_at"]` to the detail `session_view` projection.

`src/resume_agent/api/schemas/coach.py`: add `archived_at: str | None = None` to `CoachSessionSummaryOut` and `CoachSessionOut`.

`src/resume_agent/api/routers/coach.py`: import `archive_session, delete_session, unarchive_session` from `resume_agent.profile.coach_store`; extend its `_value_error` conflict tokens with `"archived"` and `"only ended"`; extend the GET list with `includeArchived`/`status` query params exactly as Task 3 did; add:

```python
@router.post("/profile/coach/sessions/{session_id}/archive", response_model=CoachSessionOut)
def archive_coach_session(session_id: str, request: Request):
    profile_dir = get_profile_dir(request)
    try:
        archive_session(profile_dir, session_id)
        return CoachSessionOut.model_validate(session_view(profile_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/profile/coach/sessions/{session_id}/unarchive", response_model=CoachSessionOut)
def unarchive_coach_session(session_id: str, request: Request):
    profile_dir = get_profile_dir(request)
    try:
        unarchive_session(profile_dir, session_id)
        return CoachSessionOut.model_validate(session_view(profile_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/profile/coach/sessions/{session_id}", status_code=204)
def delete_coach_session(session_id: str, request: Request):
    try:
        delete_session(get_profile_dir(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
```

- [ ] **Step 4: Regenerate contract + run tests**

Run: `bash scripts/gen_ts_client.sh`
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_coach_router.py tests/api/test_openapi_contract.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/profile_coach.py src/resume_agent/api/routers/coach.py src/resume_agent/api/schemas/coach.py contracts/ web/src/lib/api/schema.ts tests/api/test_coach_router.py
git commit -m "feat(api): coach session archive/unarchive/delete endpoints"
```

---

### Task 5: ErrorRecord table + errors service

**Files:**

- Modify: `src/resume_agent/tracking/tables.py`
- Create: `src/resume_agent/services/errors.py`
- Test: `tests/test_errors_service.py` (new)

**Interfaces:**

- Produces: `ErrorRecord` SQLModel table (`error_records`); `record_error(session, *, kind, source_label, message, run_id=None, details=None) -> ErrorRecord`; `record_source_failures(session, failures: dict[str, dict[str, str]]) -> int`; `list_error_records(session, status: str | None = "open") -> list[ErrorRecord]`; `set_error_status(session, record_id: int, status: str) -> ErrorRecord`; `dismiss_all(session) -> int`; `count_open(session) -> int`; `RETENTION_DAYS = 30`. `init_db` auto-creates the table (`create_all` adds missing tables to existing DBs — no migration).

- [ ] **Step 1: Write failing tests**

Create `tests/test_errors_service.py`:

```python
from datetime import timedelta

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.errors import (
    count_open,
    dismiss_all,
    list_error_records,
    record_error,
    record_source_failures,
    set_error_status,
)
from resume_agent.tracking.tables import utcnow


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as db:
        yield db


def test_record_error_dedups_open_records(session):
    first = record_error(session, kind="source", source_label="workday:acme", message="HTTP 500")
    second = record_error(session, kind="source", source_label="workday:acme", message="HTTP 503", run_id="r2")
    assert second.id == first.id
    assert second.count == 2
    assert second.message == "HTTP 503"
    assert count_open(session) == 1


def test_resolved_record_does_not_absorb_new_failures(session):
    first = record_error(session, kind="run", source_label="pull", message="boom")
    set_error_status(session, first.id, "resolved")
    fresh = record_error(session, kind="run", source_label="pull", message="boom again")
    assert fresh.id != first.id
    assert fresh.status == "open" and fresh.count == 1


def test_set_status_validates(session):
    record = record_error(session, kind="run", source_label="tailor", message="x")
    with pytest.raises(ValueError, match="unknown error record"):
        set_error_status(session, record.id + 99, "dismissed")
    with pytest.raises(ValueError, match="invalid status"):
        set_error_status(session, record.id, "closed")
    set_error_status(session, record.id, "dismissed")
    with pytest.raises(ValueError, match="not open"):
        set_error_status(session, record.id, "resolved")


def test_dismiss_all_and_status_filter(session):
    record_error(session, kind="run", source_label="pull", message="a")
    record_error(session, kind="run", source_label="tailor", message="b")
    assert dismiss_all(session) == 2
    assert list_error_records(session, status="open") == []
    assert len(list_error_records(session, status="dismissed")) == 2
    assert len(list_error_records(session, status=None)) == 2


def test_list_prunes_stale_terminal_records(session):
    record = record_error(session, kind="run", source_label="pull", message="old")
    set_error_status(session, record.id, "dismissed")
    record.updated_at = utcnow() - timedelta(days=31)
    session.add(record)
    session.commit()
    assert list_error_records(session, status=None) == []


def test_record_source_failures_fans_out(session):
    written = record_source_failures(
        session,
        {"companies": {"https://a.example": "detect failed", "https://b.example": "HTTP 403"}},
    )
    assert written == 2
    labels = {row.source_label for row in list_error_records(session)}
    assert labels == {"companies:https://a.example", "companies:https://b.example"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_errors_service.py -q`
Expected: ImportError (`resume_agent.services.errors` missing).

- [ ] **Step 3: Implement**

Append to `src/resume_agent/tracking/tables.py` (after `SkillSuggestion`):

```python
class ErrorRecord(SQLModel, table=True):
    """A durable, user-clearable failure record surfaced on the dashboard."""

    __tablename__ = cast(Any, "error_records")

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "run" | "source"
    source_label: str = Field(index=True)
    run_id: str | None = None
    message: str = ""
    details_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="open", index=True)  # open | dismissed | resolved
    count: int = 1
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

Create `src/resume_agent/services/errors.py`:

```python
"""Durable error records: dedup on write, user-driven dismiss/resolve, lazy prune."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlmodel import Session, col, select

from resume_agent.tracking.tables import ErrorRecord, utcnow

RETENTION_DAYS = 30
_TERMINAL = {"dismissed", "resolved"}


def record_error(
    session: Session,
    *,
    kind: str,
    source_label: str,
    message: str,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> ErrorRecord:
    existing = session.exec(
        select(ErrorRecord).where(
            ErrorRecord.kind == kind,
            ErrorRecord.source_label == source_label,
            ErrorRecord.status == "open",
        )
    ).first()
    now = utcnow()
    if existing is not None:
        existing.count += 1
        existing.message = message
        existing.run_id = run_id or existing.run_id
        existing.last_seen_at = now
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    record = ErrorRecord(
        kind=kind,
        source_label=source_label,
        message=message,
        run_id=run_id,
        details_json=details,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def record_source_failures(
    session: Session, failures: dict[str, dict[str, str]]
) -> int:
    written = 0
    for connector, unit_failures in failures.items():
        for unit, reason in unit_failures.items():
            record_error(
                session,
                kind="source",
                source_label=f"{connector}:{unit}",
                message=reason,
            )
            written += 1
    return written


def _prune(session: Session) -> None:
    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)
    stale = session.exec(
        select(ErrorRecord).where(
            col(ErrorRecord.status).in_(_TERMINAL),
            ErrorRecord.updated_at < cutoff,
        )
    ).all()
    for record in stale:
        session.delete(record)
    if stale:
        session.commit()


def list_error_records(
    session: Session, status: str | None = "open"
) -> list[ErrorRecord]:
    _prune(session)
    query = select(ErrorRecord).order_by(col(ErrorRecord.last_seen_at).desc())
    if status is not None:
        query = query.where(ErrorRecord.status == status)
    return list(session.exec(query).all())


def set_error_status(session: Session, record_id: int, status: str) -> ErrorRecord:
    if status not in _TERMINAL:
        raise ValueError(f"invalid status: {status}")
    record = session.get(ErrorRecord, record_id)
    if record is None:
        raise ValueError(f"unknown error record: {record_id}")
    if record.status != "open":
        raise ValueError("error record is not open")
    record.status = status
    record.updated_at = utcnow()
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def dismiss_all(session: Session) -> int:
    rows = session.exec(
        select(ErrorRecord).where(ErrorRecord.status == "open")
    ).all()
    now = utcnow()
    for record in rows:
        record.status = "dismissed"
        record.updated_at = now
        session.add(record)
    if rows:
        session.commit()
    return len(rows)


def count_open(session: Session) -> int:
    return len(
        session.exec(select(ErrorRecord).where(ErrorRecord.status == "open")).all()
    )
```

- [ ] **Step 4: Run tests — pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_errors_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/tables.py src/resume_agent/services/errors.py tests/test_errors_service.py
git commit -m "feat(errors): error_records table + dedup/dismiss/resolve service"
```

---

### Task 6: RunManager error hook + app wiring

**Files:**

- Modify: `src/resume_agent/api/runs/manager.py`
- Modify: `src/resume_agent/api/app.py`
- Test: `tests/api/test_run_manager.py` (append)

**Interfaces:**

- Consumes: `record_error` (Task 5).
- Produces: `RunManager(..., on_error: Callable[[dict], None] | None = None)`. Hook payload: `{"runId": str, "kind": str, "error": str, "userId": str | None}`. Fired from the worker's `except Exception` branch (inside the copied contextvars context, so `current_context()` resolves the right workspace) and from `recover_interrupted`. Hook failures are swallowed — error bookkeeping must never mask the original failure.

- [ ] **Step 1: Write failing tests**

Append to `tests/api/test_run_manager.py` (follow its existing pattern of constructing `RunManager(root=tmp_path)` and submitting sync work fns; it uses real thread executors, so wait on the future or poll `manager.get`):

```python
def test_on_error_hook_fires_once_per_failed_run(tmp_path):
    events = []
    manager = RunManager(root=tmp_path, on_error=events.append)
    def boom(reporter):
        raise RuntimeError("kaput")
    run_id = manager.submit("pull", boom)
    _wait_terminal(manager, run_id)  # reuse the file's polling helper, or poll get().state
    assert len(events) == 1
    assert events[0]["runId"] == run_id
    assert events[0]["kind"] == "pull"
    assert "kaput" in events[0]["error"]
    manager.shutdown()


def test_on_error_hook_not_fired_on_success_or_cancel(tmp_path):
    events = []
    manager = RunManager(root=tmp_path, on_error=events.append)
    run_id = manager.submit("pull", lambda reporter: {"ok": True})
    _wait_terminal(manager, run_id)
    assert events == []
    manager.shutdown()


def test_hook_exception_does_not_break_run_record(tmp_path):
    def bad_hook(payload):
        raise ValueError("hook broke")
    manager = RunManager(root=tmp_path, on_error=bad_hook)
    run_id = manager.submit("pull", lambda reporter: 1 / 0)
    _wait_terminal(manager, run_id)
    snapshot = manager.get(run_id)
    assert snapshot.state.value == "error"
    manager.shutdown()


def test_recover_interrupted_fires_hook(tmp_path):
    events = []
    manager = RunManager(root=tmp_path, on_error=events.append)
    run_id = manager.create("pull")  # stuck pending record from a "previous boot"
    assert manager.recover_interrupted() == 1
    assert events[0]["runId"] == run_id
    assert "restarted" in events[0]["error"].lower()
    manager.shutdown()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -q`
Expected: TypeError — `RunManager.__init__` has no `on_error`.

- [ ] **Step 3: Implement**

`src/resume_agent/api/runs/manager.py`:

1. `__init__` gains `on_error: Callable[[dict], None] | None = None` and stores `self.on_error = on_error`. Add a private emitter:

```python
    def _emit_error(self, run_id: str, kind: str, error: str, user_id: str | None) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(
                {"runId": run_id, "kind": kind, "error": error, "userId": user_id}
            )
        except Exception:  # noqa: BLE001 — bookkeeping never masks the run failure
            pass
```

1. In `submit`'s `_runner`, in the `except Exception as exc:` branch, after `reporter.done(...)`:

```python
                    self._emit_error(
                        run_id, kind, f"{type(exc).__name__}: {exc}", reporter.user_id
                    )
```

(`RunProgressReporter.__init__` already receives `user_id=` — confirm it stores `self.user_id`; if it doesn't, add `self.user_id = user_id` there.)

1. In `recover_interrupted`, where a record is stamped `state="error"` with "Backend restarted before this run completed", add:

```python
            self._emit_error(
                run_id,
                str(record.get("kind") or "run"),
                "Backend restarted before this run completed",
                record.get("user_id"),
            )
```

(Match the actual local variable names in that loop when editing.)

`src/resume_agent/api/app.py`, in `create_app` where `app.state.run_manager` is constructed (~line 166):

```python
    def _record_run_error(payload: dict) -> None:
        from sqlmodel import Session as DbSession

        from resume_agent.services.errors import record_error

        ctx = current_context()
        engine = ctx.engine if ctx is not None else app.state.engine
        if engine is None:
            return
        if ctx is None and payload.get("userId"):
            # Startup recovery for a user workspace we cannot resolve here;
            # the run file still shows the error.
            return
        with DbSession(engine) as db:
            record_error(
                db,
                kind="run",
                source_label=str(payload.get("kind") or "run"),
                message=str(payload.get("error") or "unknown error"),
                run_id=str(payload.get("runId") or "") or None,
            )

    app.state.run_manager = RunManager(
        root=manager_root,
        executor=run_executor,
        kind_workers=(
            {"suggestion": suggestion_workers} if run_executor is None else None
        ),
        on_error=_record_run_error,
    )
```

(`current_context` is already imported in `app.py`; verify and add the import if not.)

- [ ] **Step 4: Run tests — pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/api/test_runs_launch.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/runs/manager.py src/resume_agent/api/app.py tests/api/test_run_manager.py
git commit -m "feat(runs): on_error hook writes durable run-failure records"
```

---

### Task 7: Source-failure writer in pull/refresh launches

**Files:**

- Modify: `src/resume_agent/api/routers/runs.py` (`launch_pull` ~line 338, `launch_refresh` ~line 300)
- Test: `tests/api/test_runs_launch.py` (append)

**Interfaces:**

- Consumes: `record_source_failures` (Task 5); `RefreshReport.failures` / `PullReport.failures` (`dict[str, dict[str, str]]`).
- Produces: every API pull/refresh that completes with per-source failures leaves `kind="source"` records. CLI paths untouched.

- [ ] **Step 1: Write failing test**

Append to `tests/api/test_runs_launch.py`, following its existing pattern for stubbing `pull_jobs`/`refresh_jobs` via monkeypatch on the runs router module:

```python
def test_pull_failures_become_source_error_records(tmp_path, monkeypatch):
    client = _client(tmp_path)  # the file's existing app/client helper

    class FakeReport:
        totals = {"companies": 0}
        changed_raw_job_ids = []
        failures = {"companies": {"https://x.example": "detect failed"}}

    monkeypatch.setattr(runs_router, "pull_jobs", lambda *a, **k: FakeReport())
    res = client.post("/api/pull", json={})
    assert res.status_code == 202
    run_id = res.json()["runId"]
    _wait_run(client, run_id)  # the file's run-completion poller
    records = client.get("/api/errors").json()["records"]  # exists after Task 8; until then assert via DB
    assert records[0]["sourceLabel"] == "companies:https://x.example"
```

Until Task 8 lands the `/api/errors` route, assert through the DB instead — resolve the app engine off the client (`client.app.state.engine`) and query with `resume_agent.services.errors.list_error_records`; switch the assertion to the HTTP form in Task 8 if convenient (either form is acceptable to keep).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -q`
Expected: new test FAILS (no records written).

- [ ] **Step 3: Implement**

In `src/resume_agent/api/routers/runs.py`, import `record_source_failures` from `resume_agent.services.errors`. In **both** `launch_pull`'s and `launch_refresh`'s `work(reporter)` functions, after the report is computed and before the return-dict is built, add (adapting the local variable name — `report`):

```python
        if report.failures:
            with get_session(engine) as error_db:
                record_source_failures(error_db, report.failures)
```

Both work fns already close over `engine`; keep the write in its own short session so it commits independently of the pull transaction.

- [ ] **Step 4: Run tests — pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/runs.py tests/api/test_runs_launch.py
git commit -m "feat(runs): record per-source pull failures as error records"
```

---

### Task 8: Errors router + dashboard summary extension

**Files:**

- Create: `src/resume_agent/api/routers/errors.py`, `src/resume_agent/api/schemas/errors.py`
- Modify: `src/resume_agent/api/routers/dashboard.py`, `src/resume_agent/api/schemas/dashboard.py`, `src/resume_agent/api/app.py` (router include)
- Test: `tests/api/test_errors_router.py` (new), `tests/api/test_dashboard_summary.py` (append)

**Interfaces:**

- Consumes: Task 5 service; `sessions_view` (interview, Task 3) and `sessions_view` (coach, Task 4); schemas `InterviewSessionSummaryOut`, `CoachSessionSummaryOut`.
- Produces: `GET /api/errors?status=`, `POST /api/errors/{record_id}/dismiss`, `POST /api/errors/{record_id}/resolve`, `POST /api/errors/dismiss-all`. `DashboardSummaryOut` gains `open_error_count: int = 0`, `active_interviews: list[InterviewSessionSummaryOut]`, `active_coach_session: CoachSessionSummaryOut | None`.

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_errors_router.py` (client helper copied from `tests/api/test_interview_router.py`'s `_client`):

```python
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.services.errors import record_error


def _client(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    )


def _seed_record(client, **kwargs):
    with Session(client.app.state.engine) as db:
        return record_error(db, **kwargs).id


def test_list_defaults_to_open(tmp_path):
    client = _client(tmp_path)
    _seed_record(client, kind="run", source_label="pull", message="boom")
    body = client.get("/api/errors").json()
    row = body["records"][0]
    assert row["kind"] == "run"
    assert row["sourceLabel"] == "pull"
    assert row["status"] == "open"
    assert row["count"] == 1


def test_dismiss_resolve_and_conflicts(tmp_path):
    client = _client(tmp_path)
    rid = _seed_record(client, kind="run", source_label="pull", message="boom")
    assert client.post(f"/api/errors/{rid}/dismiss").json()["status"] == "dismissed"
    assert client.post(f"/api/errors/{rid}/resolve").status_code == 409
    assert client.post("/api/errors/999/dismiss").status_code == 404


def test_dismiss_all(tmp_path):
    client = _client(tmp_path)
    _seed_record(client, kind="run", source_label="pull", message="a")
    _seed_record(client, kind="run", source_label="tailor", message="b")
    assert client.post("/api/errors/dismiss-all").json() == {"dismissed": 2}
    assert client.get("/api/errors").json()["records"] == []


def test_invalid_status_filter(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/errors", params={"status": "weird"}).status_code == 422
```

Append to `tests/api/test_dashboard_summary.py` (reuse its client helper; seed one active interview session on disk exactly as `test_interview_router.py` does):

```python
def test_summary_carries_sessions_and_error_count(tmp_path):
    client = _client(tmp_path)
    _seed_record(client, kind="run", source_label="pull", message="boom")
    interview_dir = tmp_path / "data" / "interview"
    _store_session(interview_dir, "live", job_id=1)
    body = client.get("/api/dashboard/summary").json()
    assert body["openErrorCount"] == 1
    assert body["activeInterviews"][0]["sessionId"] == "live"
    assert body["activeCoachSession"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_errors_router.py tests/api/test_dashboard_summary.py -q`
Expected: 404s / missing keys.

- [ ] **Step 3: Implement**

`src/resume_agent/api/schemas/errors.py`:

```python
"""Error record schemas."""

from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class ErrorRecordOut(CamelModel):
    id: int
    kind: str
    source_label: str
    run_id: str | None = None
    message: str = ""
    status: str
    count: int = 1
    first_seen_at: str
    last_seen_at: str
    updated_at: str


class ErrorRecordsOut(CamelModel):
    records: list[ErrorRecordOut] = Field(default_factory=list)


class DismissAllOut(CamelModel):
    dismissed: int = 0
```

`src/resume_agent/api/routers/errors.py`:

```python
"""User-clearable error records: list, dismiss, resolve."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.errors import DismissAllOut, ErrorRecordOut, ErrorRecordsOut
from resume_agent.services.errors import (
    dismiss_all,
    list_error_records,
    set_error_status,
)

router = APIRouter()
_STATUSES = {"open", "dismissed", "resolved"}


def _row(record) -> ErrorRecordOut:
    return ErrorRecordOut(
        id=record.id,
        kind=record.kind,
        source_label=record.source_label,
        run_id=record.run_id,
        message=record.message,
        status=record.status,
        count=record.count,
        first_seen_at=record.first_seen_at.isoformat(),
        last_seen_at=record.last_seen_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


@router.get("/errors", response_model=ErrorRecordsOut)
def list_errors(
    status: str | None = Query("open"),
    session: Session = Depends(get_session),
):
    if status is not None and status not in _STATUSES:
        raise ApiException(422, "VALIDATION_ERROR", f"invalid status: {status}")
    return ErrorRecordsOut(records=[_row(r) for r in list_error_records(session, status=status)])


def _set_status(session: Session, record_id: int, status: str) -> ErrorRecordOut:
    try:
        return _row(set_error_status(session, record_id, status))
    except ValueError as exc:
        message = str(exc)
        if "unknown" in message:
            raise ApiException(404, "NOT_FOUND", message) from exc
        raise ApiException(409, "CONFLICT", message) from exc


@router.post("/errors/dismiss-all", response_model=DismissAllOut)
def dismiss_all_errors(session: Session = Depends(get_session)):
    return DismissAllOut(dismissed=dismiss_all(session))


@router.post("/errors/{record_id}/dismiss", response_model=ErrorRecordOut)
def dismiss_error(record_id: int, session: Session = Depends(get_session)):
    return _set_status(session, record_id, "dismissed")


@router.post("/errors/{record_id}/resolve", response_model=ErrorRecordOut)
def resolve_error(record_id: int, session: Session = Depends(get_session)):
    return _set_status(session, record_id, "resolved")
```

Route order matters: `dismiss-all` is declared **before** `/{record_id}/dismiss` so it cannot be captured as a record id.

`src/resume_agent/api/schemas/dashboard.py`:

```python
from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.api.schemas.coach import CoachSessionSummaryOut
from resume_agent.api.schemas.interview import InterviewSessionSummaryOut


class DashboardSummaryOut(CamelModel):
    status_counts: dict[str, int]
    queues: dict[str, int]
    applied: int
    open_error_count: int = 0
    active_interviews: list[InterviewSessionSummaryOut] = Field(default_factory=list)
    active_coach_session: CoachSessionSummaryOut | None = None
```

`src/resume_agent/api/routers/dashboard.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_interview_dir, get_profile_dir, get_session
from resume_agent.api.schemas.coach import CoachSessionSummaryOut
from resume_agent.api.schemas.dashboard import DashboardSummaryOut
from resume_agent.api.schemas.interview import InterviewSessionSummaryOut
from resume_agent.services.dashboard import summarize_dashboard
from resume_agent.services.errors import count_open
from resume_agent.services.mock_interview import sessions_view as interview_sessions_view
from resume_agent.services.profile_coach import sessions_view as coach_sessions_view

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(request: Request, session: Session = Depends(get_session)):
    summary = summarize_dashboard(session)
    interviews = interview_sessions_view(get_interview_dir(request), status="active")
    coach_rows = coach_sessions_view(get_profile_dir(request), status="active")["sessions"]
    return DashboardSummaryOut(
        status_counts=summary.status_counts,
        queues=summary.queues,
        applied=summary.applied,
        open_error_count=count_open(session),
        active_interviews=[
            InterviewSessionSummaryOut.model_validate(row)
            for row in interviews["sessions"]
        ],
        active_coach_session=(
            CoachSessionSummaryOut.model_validate(coach_rows[0]) if coach_rows else None
        ),
    )
```

`src/resume_agent/api/app.py`: add `errors` to the router imports and include it beside the dashboard router with the same `guarded` dependencies:

```python
    app.include_router(errors.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Regenerate contract + run tests**

Run: `bash scripts/gen_ts_client.sh`
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_errors_router.py tests/api/test_dashboard_summary.py tests/api/test_openapi_contract.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/errors.py src/resume_agent/api/schemas/errors.py src/resume_agent/api/routers/dashboard.py src/resume_agent/api/schemas/dashboard.py src/resume_agent/api/app.py contracts/ web/src/lib/api/schema.ts tests/api/
git commit -m "feat(api): errors router + dashboard sessions/error-count extension"
```

---

### Task 9: Backend regression sweep

**Files:** none new.

- [ ] **Step 1: Full backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -8` and `ruff check`
Expected: all tests pass, lint clean. Fix any straggler (e.g. a forgotten `active_session` import in CLI or tests) before proceeding.

- [ ] **Step 2: Commit any fixes**

```bash
git add -A && git commit -m "test: backend sweep after session/error-record changes"
```

(Skip the commit if the tree is clean.)

---

### Task 10: Web hooks — session management + errors

**Files:**

- Modify: `web/src/features/interview/use-interview.ts`
- Modify: `web/src/features/coach/use-coach.ts`
- Create: `web/src/features/errors/use-errors.ts`
- Test: `web/src/features/interview/use-interview.test.tsx` (append), `web/src/features/errors/use-errors.test.tsx` (new)

**Interfaces:**

- Consumes: regenerated `web/src/lib/api/schema.ts` (Tasks 3/4/8).
- Produces: `useInterviewSessions(jobId?, includeArchived?)`; `useArchiveInterviewSession()`, `useUnarchiveInterviewSession()`, `useDeleteInterviewSession()` (each `mutate({ sessionId })`); coach equivalents `useArchiveCoachSession()`, `useUnarchiveCoachSession()`, `useDeleteCoachSession()`; `useErrorRecords(status?)`, `useDismissError()`, `useResolveError()`, `useDismissAllErrors()`; `export type ErrorRecord = components["schemas"]["ErrorRecordOut"]`.

- [ ] **Step 1: Write failing tests**

Follow the existing `use-interview.test.tsx` pattern (msw-less fetch mock or `vi.mock` of `@/lib/api/client` — mirror whatever that file already does). New cases:

```tsx
it("archives a session and invalidates session queries", async () => {
  // arrange mocked api.POST to resolve; render useArchiveInterviewSession via renderHook
  // act: result.current.mutate({ sessionId: "s1" })
  // assert: api.POST called with "/api/interview/sessions/{session_id}/archive"
  //         and { params: { path: { session_id: "s1" } } }
});

it("passes includeArchived to the sessions list", async () => {
  // renderHook(() => useInterviewSessions(undefined, true))
  // assert api.GET called with query { includeArchived: true }
});
```

`use-errors.test.tsx`: list defaults to `status=open`; `useDismissAllErrors` posts `/api/errors/dismiss-all` and invalidates `["error-records"]` and `["dashboard-summary"]`.

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/features/interview/use-interview.test.tsx src/features/errors/use-errors.test.tsx`
Expected: FAIL (hooks not exported).

- [ ] **Step 3: Implement**

`use-interview.ts` — extend the list hook and add mutations:

```ts
export function useInterviewSessions(jobId?: number, includeArchived = false) {
  return useQuery({
    queryKey: ["interview-sessions", jobId ?? null, includeArchived],
    queryFn: () =>
      unwrap(
        api.GET("/api/interview/sessions", {
          params: {
            query: {
              ...(jobId != null ? { jobId } : {}),
              ...(includeArchived ? { includeArchived: true } : {}),
            },
          },
        }),
      ) as Promise<components["schemas"]["InterviewSessionsOut"]>,
  });
}

function useSessionListInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["interview-sessions"] }),
      queryClient.invalidateQueries({ queryKey: ["interview-session"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
    ]);
  };
}

export function useArchiveInterviewSession() {
  const invalidate = useSessionListInvalidation();
  return useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) =>
      unwrap(
        api.POST("/api/interview/sessions/{session_id}/archive", {
          params: { path: { session_id: sessionId } },
        }),
      ),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}
```

`useUnarchiveInterviewSession` is identical with the `/unarchive` path. `useDeleteInterviewSession` uses `api.DELETE("/api/interview/sessions/{session_id}", ...)` with the same invalidation plus `toast.success("Interview deleted")`.

`use-coach.ts` — add the three coach equivalents against `/api/profile/coach/sessions/{session_id}/archive|unarchive` and `DELETE /api/profile/coach/sessions/{session_id}`, invalidating that file's existing coach session query keys (match the keys already used there) plus `["dashboard-summary"]`.

`web/src/features/errors/use-errors.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ErrorRecord = components["schemas"]["ErrorRecordOut"];

export function useErrorRecords(
  status: "open" | "dismissed" | "resolved" = "open",
) {
  return useQuery({
    queryKey: ["error-records", status],
    queryFn: () =>
      unwrap(
        api.GET("/api/errors", { params: { query: { status } } }),
      ) as Promise<components["schemas"]["ErrorRecordsOut"]>,
  });
}

function useErrorInvalidation() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["error-records"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
    ]);
  };
}

export function useDismissError() {
  const invalidate = useErrorInvalidation();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      unwrap(
        api.POST("/api/errors/{record_id}/dismiss", {
          params: { path: { record_id: id } },
        }),
      ),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useResolveError() {
  const invalidate = useErrorInvalidation();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      unwrap(
        api.POST("/api/errors/{record_id}/resolve", {
          params: { path: { record_id: id } },
        }),
      ),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDismissAllErrors() {
  const invalidate = useErrorInvalidation();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/errors/dismiss-all", {})),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}
```

- [ ] **Step 4: Run tests — pass**

Run: `cd web && npx vitest run src/features/interview/use-interview.test.tsx src/features/errors/use-errors.test.tsx && npx tsc --noEmit`
Expected: pass, no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/interview/use-interview.ts web/src/features/coach/use-coach.ts web/src/features/errors/
git commit -m "feat(web): session-management and error-record hooks"
```

---

### Task 11: Interview hub — SessionsRail + page integration + NewInterviewDialog

**Files:**

- Create: `web/src/features/interview/SessionsRail.tsx`, `web/src/features/interview/NewInterviewDialog.tsx`
- Modify: `web/src/features/interview/InterviewPage.tsx`, `web/src/features/interview/InterviewSetupDialog.tsx`
- Test: `web/src/features/interview/SessionsRail.test.tsx` (new), `web/src/features/interview/InterviewPage.test.tsx` (extend)

**Interfaces:**

- Consumes: Task 10 hooks; existing `InterviewSetupDialog` (gains an optional `onStarted` no-behavior-change refactor is NOT needed — it already navigates on success).
- Produces: `SessionsRail({ selectedId }: { selectedId: string | null })` — self-fetching via `useInterviewSessions(undefined, showArchived)`; `NewInterviewDialog({ open, onOpenChange })` — job picker over `/api/pipeline` statuses `tailored` + `rendered`, then renders `InterviewSetupDialog` for the chosen job.

- [ ] **Step 1: Write failing tests**

`SessionsRail.test.tsx` (mock `./use-interview` with `vi.mock`, following `InterviewTab.test.tsx`'s style):

```tsx
it("groups sessions into in-progress and completed", () => {
  // mock useInterviewSessions -> one active ("s1", jobId 1) + one ended ("s2", overallScore 4.2)
  // render <SessionsRail selectedId={null} /> inside MemoryRouter
  // assert headings "In progress" and "Completed" and both rows visible
});

it("delete confirm warns for active sessions", async () => {
  // open the kebab menu on the active row, click Delete
  // assert dialog text mentions abandoning without a debrief
  // confirm -> useDeleteInterviewSession().mutate called with { sessionId: "s1" }
});

it("archived toggle refetches with includeArchived", async () => {
  // toggle "Show archived" switch -> useInterviewSessions called with (undefined, true)
});
```

`InterviewPage.test.tsx` additions: page renders the rail alongside the chat; with no `?session=` and one active session, that session is displayed; the "New interview" button opens `NewInterviewDialog`.

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/features/interview/SessionsRail.test.tsx src/features/interview/InterviewPage.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement**

`SessionsRail.tsx`:

```tsx
import { useState } from "react";
import {
  Archive,
  ArchiveRestore,
  EllipsisVertical,
  Plus,
  Trash2,
} from "lucide-react";
import { Link } from "react-router-dom";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { NewInterviewDialog } from "./NewInterviewDialog";
import {
  useArchiveInterviewSession,
  useDeleteInterviewSession,
  useInterviewSessions,
  useUnarchiveInterviewSession,
  type InterviewSessionSummary,
} from "./use-interview";

function SessionRow({
  row,
  selected,
  onDelete,
}: {
  row: InterviewSessionSummary;
  selected: boolean;
  onDelete: (row: InterviewSessionSummary) => void;
}) {
  const archive = useArchiveInterviewSession();
  const unarchive = useUnarchiveInterviewSession();
  const label =
    [row.company, row.title].filter(Boolean).join(" · ") || "Mock interview";
  return (
    <li
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-2",
        selected && "border-primary bg-primary/5",
      )}
    >
      <Link
        to={`/interview?session=${row.sessionId}`}
        className="min-w-0 flex-1 hover:underline"
      >
        <span className="block truncate text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">
          {row.status === "active"
            ? `Question ${row.askedCount} of ${row.questionCount}`
            : row.overallScore != null
              ? `Scored ${row.overallScore}/5`
              : "Completed"}
          {" · "}
          {new Date(row.startedAt).toLocaleDateString()}
        </span>
      </Link>
      {row.archivedAt ? <Badge variant="outline">Archived</Badge> : null}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Actions for ${label}`}
            >
              <EllipsisVertical />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          {row.status === "ended" && !row.archivedAt ? (
            <DropdownMenuItem
              onClick={() => archive.mutate({ sessionId: row.sessionId })}
            >
              <Archive aria-hidden="true" />
              Archive
            </DropdownMenuItem>
          ) : null}
          {row.archivedAt ? (
            <DropdownMenuItem
              onClick={() => unarchive.mutate({ sessionId: row.sessionId })}
            >
              <ArchiveRestore aria-hidden="true" />
              Unarchive
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem variant="destructive" onClick={() => onDelete(row)}>
            <Trash2 aria-hidden="true" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}

export function SessionsRail({ selectedId }: { selectedId: string | null }) {
  const [showArchived, setShowArchived] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [pendingDelete, setPendingDelete] =
    useState<InterviewSessionSummary | null>(null);
  const sessions = useInterviewSessions(undefined, showArchived);
  const remove = useDeleteInterviewSession();

  const rows = sessions.data?.sessions ?? [];
  const inProgress = rows.filter((row) => row.status === "active");
  const completed = rows.filter((row) => row.status === "ended");

  return (
    <aside className="flex w-full flex-col gap-4 lg:w-80 lg:shrink-0">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Sessions</h2>
        <Button size="sm" onClick={() => setNewOpen(true)}>
          <Plus aria-hidden="true" />
          New interview
        </Button>
      </div>
      {inProgress.length ? (
        <section aria-label="In progress" className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            In progress
          </h3>
          <ul className="space-y-2">
            {inProgress.map((row) => (
              <SessionRow
                key={row.sessionId}
                row={row}
                selected={row.sessionId === selectedId}
                onDelete={setPendingDelete}
              />
            ))}
          </ul>
        </section>
      ) : null}
      {completed.length ? (
        <section aria-label="Completed" className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Completed
          </h3>
          <ul className="space-y-2">
            {completed.map((row) => (
              <SessionRow
                key={row.sessionId}
                row={row}
                selected={row.sessionId === selectedId}
                onDelete={setPendingDelete}
              />
            ))}
          </ul>
        </section>
      ) : null}
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <Switch checked={showArchived} onCheckedChange={setShowArchived} />
        Show archived
      </label>

      <NewInterviewDialog open={newOpen} onOpenChange={setNewOpen} />

      <AlertDialog
        open={pendingDelete != null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this interview?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.status === "active"
                ? "This interview is still in progress — deleting it abandons it without a debrief. This cannot be undone."
                : "The transcript and debrief will be permanently removed. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingDelete)
                  remove.mutate({ sessionId: pendingDelete.sessionId });
                setPendingDelete(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}
```

`NewInterviewDialog.tsx` — job picker, then reuse `InterviewSetupDialog`:

```tsx
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { api, fetchAllPages, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import { InterviewSetupDialog } from "./InterviewSetupDialog";
import { useInterviewSessions } from "./use-interview";

type PipelineItem = components["schemas"]["PipelineItem"];
type JobDetail = components["schemas"]["JobDetail"];

function useInterviewableJobs(enabled: boolean) {
  return useQuery({
    queryKey: ["interviewable-jobs"],
    enabled,
    queryFn: async () => {
      const pages = await Promise.all(
        (["tailored", "rendered"] as const).map((status) =>
          fetchAllPages<PipelineItem>((page) =>
            api.GET("/api/pipeline", {
              params: {
                query: { status, sortBy: "stage", page, pageSize: 200 },
              },
            }),
          ),
        ),
      );
      return pages.flat();
    },
  });
}

export function NewInterviewDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [jobId, setJobId] = useState<number | null>(null);
  const jobs = useInterviewableJobs(open);
  const sessions = useInterviewSessions();
  const activeJobIds = useMemo(
    () =>
      new Set(
        (sessions.data?.sessions ?? [])
          .filter((s) => s.status === "active")
          .map((s) => s.jobId),
      ),
    [sessions.data],
  );
  const candidates = (jobs.data ?? []).filter(
    (job) => !activeJobIds.has(job.jobId),
  );
  const detail = useQuery({
    queryKey: ["job-detail", jobId],
    enabled: jobId != null,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId as number } },
        }),
      ) as Promise<JobDetail>,
  });
  const versions = detail.data?.resumeVersions ?? [];

  if (jobId != null && versions.length) {
    return (
      <InterviewSetupDialog
        jobId={jobId}
        versions={versions}
        open={open}
        onOpenChange={(next) => {
          if (!next) setJobId(null);
          onOpenChange(next);
        }}
      />
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New mock interview</DialogTitle>
          <DialogDescription>
            Pick a job with a tailored resume. Jobs with an interview already in
            progress are hidden — resume those from the sessions list.
          </DialogDescription>
        </DialogHeader>
        {jobs.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            Loading jobs…
          </div>
        ) : candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No interviewable jobs yet — tailor a resume first.
          </p>
        ) : (
          <Field>
            <FieldLabel htmlFor="new-interview-job">Job</FieldLabel>
            <Select
              value={jobId != null ? String(jobId) : undefined}
              onValueChange={(v) => setJobId(Number(v))}
            >
              <SelectTrigger id="new-interview-job" className="w-full">
                <SelectValue placeholder="Choose a job" />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((job) => (
                  <SelectItem key={job.jobId} value={String(job.jobId)}>
                    {[job.company, job.title].filter(Boolean).join(" · ")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        {jobId != null && detail.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            Loading resume versions…
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
```

(Verify the `JobDetail` schema field name for versions in `web/src/lib/api/schema.ts` — it is the camelCase projection of the job-detail response; adjust `resumeVersions` if the generated name differs.)

`InterviewPage.tsx` — wrap the existing content in a two-column layout and drop the dead-end empty state:

```tsx
// inside the top-level return, replace the outer <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-8">
// with a flex row hosting the rail + main pane:
return (
  <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 lg:flex-row lg:items-start">
    <SessionsRail selectedId={displayedSessionId} />
    <div className="min-w-0 flex-1">{mainPane}</div>
  </div>
);
```

Refactor mechanically: extract the current `!active` empty state and the chat/debrief block into a `mainPane` variable; the empty state copy changes to "Select a session or start a new interview." The rail is always rendered.

- [ ] **Step 4: Run tests — pass**

Run: `cd web && npx vitest run src/features/interview/ && npx tsc --noEmit`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/interview/
git commit -m "feat(web): interview hub with sessions rail and job-picker dialog"
```

---

### Task 12: InterviewTab per-job semantics + banner aggregate

**Files:**

- Modify: `web/src/features/interview/InterviewTab.tsx`
- Modify: `web/src/features/interview/ActiveInterviewBanner.tsx`
- Test: `web/src/features/interview/InterviewTab.test.tsx`, `web/src/features/interview/ActiveInterviewBanner.test.tsx` (extend)

**Interfaces:**

- Consumes: Task 10 hooks.
- Produces: tab hides Start when this job has an active session (shows a resume hint instead); banner shows the count of active interviews app-wide and links to `/interview` (no End button — ending belongs to the hub/page now).

- [ ] **Step 1: Write failing tests**

```tsx
// InterviewTab.test.tsx
it("offers resume instead of start when the job has an active session", () => {
  // mock useInterviewSessions(jobId) -> one active row
  // assert Start button absent, text /interview in progress/i present,
  // and the active row links to /interview?session=...
});

// ActiveInterviewBanner.test.tsx
it("shows the active-interview count and links to the hub", () => {
  // mock useInterviewSessions -> two active sessions
  // assert text "2 mock interviews in progress" and link to /interview
});

it("renders nothing on /interview or with no active sessions", () => { ... });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/features/interview/InterviewTab.test.tsx src/features/interview/ActiveInterviewBanner.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`InterviewTab.tsx`: compute `const activeRow = rows.find((row) => row.status === "active");` and replace the Start button block:

```tsx
{
  activeRow ? (
    <p className="text-sm text-muted-foreground">
      An interview for this job is in progress — resume it from the list below.
    </p>
  ) : (
    <Button disabled={!canStart} onClick={() => setOpen(true)}>
      <MessagesSquare aria-hidden="true" />
      Start mock interview
    </Button>
  );
}
```

Keep the existing list rows (they already deep-link with Resume badges). Render `InterviewSetupDialog` only when `canStart && !activeRow`.

`ActiveInterviewBanner.tsx`: replace the single-active logic and End dialog with an aggregate:

```tsx
export function ActiveInterviewBanner() {
  const location = useLocation();
  const sessions = useInterviewSessions();
  const active = (sessions.data?.sessions ?? []).filter(
    (s) => s.status === "active",
  );

  if (active.length === 0 || location.pathname === "/interview") return null;

  const single = active.length === 1 ? active[0] : null;
  const label = single
    ? [single.company, single.title].filter(Boolean).join(" · ")
    : `${active.length} mock interviews in progress`;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-amber-500/30 bg-amber-500/10 px-5 py-2.5 text-sm md:px-8 lg:px-10">
      <MessagesSquare
        className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
        aria-hidden="true"
      />
      <span className="min-w-0">
        <span className="font-medium">
          {single ? "Mock interview in progress" : label}
        </span>
        {single && label ? (
          <span className="text-muted-foreground"> — {label}</span>
        ) : null}
      </span>
      <div className="ml-auto">
        <Button
          size="sm"
          render={
            <Link
              to={
                single ? `/interview?session=${single.sessionId}` : "/interview"
              }
            >
              {single ? "Resume" : "Open interviews"}
            </Link>
          }
        />
      </div>
    </div>
  );
}
```

Update the component's doc comment: it is now the app-wide re-entry point for however many interviews are running; per-session End lives on the hub page. Remove the now-unused `useEndInterview` import and AlertDialog imports.

- [ ] **Step 4: Run tests — pass**

Run: `cd web && npx vitest run src/features/interview/ && npx tsc --noEmit`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/interview/InterviewTab.tsx web/src/features/interview/ActiveInterviewBanner.tsx web/src/features/interview/*.test.tsx
git commit -m "feat(web): per-job interview tab semantics + aggregate active banner"
```

---

### Task 13: Coach Past-sessions actions

**Files:**

- Modify: `web/src/features/coach/CoachPage.tsx` (the existing "Past sessions" block at ~line 296)
- Test: `web/src/features/coach/CoachPage.test.tsx` (extend)

**Interfaces:**

- Consumes: Task 10 coach mutations; existing past-sessions rendering.
- Produces: each ended-session row gains a kebab (Archive/Unarchive/Delete with confirm); a "Show archived" switch below the list; archived rows show an Archived badge. Reviewing an ended session (whatever affordance the block already has for opening one — extend it to show transcript + recap read-only if it currently doesn't) stays read-only.

- [ ] **Step 1: Write failing tests**

Extend `CoachPage.test.tsx` following its existing mocking approach for `use-coach`:

```tsx
it("archives an ended coach session from the past-sessions row", async () => {
  // mock sessions list -> one ended session c1
  // open kebab, click Archive -> useArchiveCoachSession().mutate({ sessionId: "c1" })
});

it("delete asks for confirmation and never touches saved notes copy", async () => {
  // click Delete -> dialog copy mentions "Saved notes are kept in your profile"
  // confirm -> useDeleteCoachSession().mutate called
});

it("show-archived toggle lists archived sessions", async () => {
  // toggle -> sessions hook called with includeArchived=true
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/features/coach/CoachPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `CoachPage.tsx`'s Past-sessions block: thread `includeArchived` state into the sessions query hook this page already uses (mirror Task 10's `useInterviewSessions` signature change on the coach list hook if the page fetches via a coach-sessions hook — add the same optional `includeArchived` parameter there), then per row add the same `DropdownMenu` kebab + `AlertDialog` confirm pattern as `SessionsRail.tsx` (Task 11), with coach mutations and this delete copy:

> "The conversation transcript and recap will be permanently removed. Saved notes are kept in your profile."

Add below the list:

```tsx
<label className="flex items-center gap-2 text-sm text-muted-foreground">
  <Switch checked={showArchived} onCheckedChange={setShowArchived} />
  Show archived
</label>
```

- [ ] **Step 4: Run tests — pass**

Run: `cd web && npx vitest run src/features/coach/ && npx tsc --noEmit`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/coach/
git commit -m "feat(web): coach past-session archive/delete management"
```

---

### Task 14: Dashboard cards — In progress + Attention needed

**Files:**

- Create: `web/src/features/dashboard/InProgressCard.tsx`, `web/src/features/dashboard/AttentionCard.tsx`
- Modify: `web/src/features/dashboard/DashboardPage.tsx`, `web/src/features/dashboard/fixtures.ts`
- Test: `web/src/features/dashboard/InProgressCard.test.tsx`, `web/src/features/dashboard/AttentionCard.test.tsx` (new)

**Interfaces:**

- Consumes: extended `DashboardSummaryOut` (Task 8) via `useDashboardSummary()`; `useErrorRecords`/`useDismissError`/`useResolveError`/`useDismissAllErrors` (Task 10); `timeAgo` from `./time-ago`.
- Produces: `InProgressCard({ summary })` and `AttentionCard()` rendered on `DashboardPage`.

- [ ] **Step 1: Write failing tests**

```tsx
// InProgressCard.test.tsx
it("lists active interviews with resume links and the coach session", () => {
  // render with summary fixture: activeInterviews=[{sessionId:"s1", company:"Acme", title:"SWE", askedCount:3, questionCount:8, startedAt:...}],
  // activeCoachSession={sessionId:"c1", startedAt:..., topicCount:4, savedNoteCount:1}
  // assert "Acme · SWE", "Question 3 of 8", link /interview?session=s1,
  // "Profile coaching in progress" linking to /coach
});

it("renders a quiet empty line when nothing is in progress", () => { ... });

// AttentionCard.test.tsx
it("renders open error records with dismiss/resolve and clear all", async () => {
  // mock useErrorRecords -> [{id:1, kind:"source", sourceLabel:"companies:https://x", message:"HTTP 403", count:3, lastSeenAt:...}]
  // assert "seen 3×" text; click Dismiss -> useDismissError().mutate({id:1});
  // click "Clear all" -> useDismissAllErrors().mutate()
});

it("collapses to 'No open errors' when empty", () => { ... });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/features/dashboard/InProgressCard.test.tsx src/features/dashboard/AttentionCard.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`InProgressCard.tsx`:

```tsx
import { Bot, MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { DashboardSummary } from "./use-dashboard-summary";
import { timeAgo } from "./time-ago";

export function InProgressCard({ summary }: { summary: DashboardSummary }) {
  const interviews = summary.activeInterviews ?? [];
  const coach = summary.activeCoachSession ?? null;
  const empty = interviews.length === 0 && coach == null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">In progress</CardTitle>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="text-sm text-muted-foreground">
            Nothing in progress — start a mock interview or a coaching session.
          </p>
        ) : (
          <ul className="space-y-3">
            {interviews.map((row) => (
              <li key={row.sessionId} className="flex items-center gap-3">
                <MessagesSquare
                  className="size-4 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {[row.company, row.title].filter(Boolean).join(" · ") ||
                      "Mock interview"}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Question {row.askedCount} of {row.questionCount} · started{" "}
                    {timeAgo(row.startedAt)}
                  </span>
                </div>
                <Link
                  className="text-sm font-medium text-primary hover:underline"
                  to={`/interview?session=${row.sessionId}`}
                >
                  Resume
                </Link>
              </li>
            ))}
            {coach ? (
              <li className="flex items-center gap-3">
                <Bot
                  className="size-4 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">
                    Profile coaching in progress
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {coach.savedNoteCount} note
                    {coach.savedNoteCount === 1 ? "" : "s"} saved · started{" "}
                    {timeAgo(coach.startedAt)}
                  </span>
                </div>
                <Link
                  className="text-sm font-medium text-primary hover:underline"
                  to="/coach"
                >
                  Resume
                </Link>
              </li>
            ) : null}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
```

`AttentionCard.tsx`:

```tsx
import { CircleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

import {
  useDismissAllErrors,
  useDismissError,
  useErrorRecords,
  useResolveError,
} from "../errors/use-errors";
import { timeAgo } from "./time-ago";

export function AttentionCard() {
  const records = useErrorRecords("open");
  const dismiss = useDismissError();
  const resolve = useResolveError();
  const clearAll = useDismissAllErrors();
  const rows = records.data?.records ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <CircleAlert className="size-4 text-destructive" aria-hidden="true" />
          Attention needed
          {rows.length ? (
            <Badge variant="destructive">{rows.length}</Badge>
          ) : null}
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
      <CardContent>
        {records.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open errors.</p>
        ) : (
          <ul className="space-y-3">
            {rows.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-2">
                <div className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {row.sourceLabel}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {row.message}
                    {row.count > 1 ? ` · seen ${row.count}×` : ""} ·{" "}
                    {timeAgo(row.lastSeenAt)}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => dismiss.mutate({ id: row.id })}
                >
                  Dismiss
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resolve.mutate({ id: row.id })}
                >
                  Resolve
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
```

`DashboardPage.tsx`: render `<InProgressCard summary={summary} />` and `<AttentionCard />` in the existing grid, after the stage rail / queues and before or beside `RecentRuns` — match the page's current grid classes. Extend `fixtures.ts`'s summary fixture with `openErrorCount: 0, activeInterviews: [], activeCoachSession: null` so existing tests keep passing.

- [ ] **Step 4: Run tests — pass**

Run: `cd web && npx vitest run src/features/dashboard/ && npx tsc --noEmit`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/dashboard/
git commit -m "feat(web): dashboard in-progress and attention-needed cards"
```

---

### Task 15: Full verification sweep

- [ ] **Step 1: Backend**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -8` and `ruff check`
Expected: all pass, lint clean.

- [ ] **Step 2: Frontend**

Run: `cd web && npx vitest run 2>&1 | tail -8 && npx tsc --noEmit`
Expected: all pass, no type errors.

- [ ] **Step 3: Contract drift double-check**

Run: `bash scripts/gen_ts_client.sh && git status --short`
Expected: no modifications (contract already committed in Tasks 3/4/8).

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "test: full verification sweep for session management + dashboard"
```

(Skip if clean.)
