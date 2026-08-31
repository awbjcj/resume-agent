# Run Completion Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a background run's completion reach the UI reliably — the progress bar always reaches 100%, the toast always fires, and the board always refreshes — even when the SSE stream drops repeatedly or the completion lands while no client is connected.

**Architecture:** The run's JSON record under `data/runs/` is already durable for 24 h; we add an `announced_at` stamp and an ack endpoint so a terminal run becomes a recoverable, acknowledgeable fact. On the client, run lifecycle moves out of the SSE transport (`sse.ts`) into `tracker.ts`, which gains unbounded reconnect-with-backoff and a 15 s reconciliation poller. SSE becomes a latency optimization; the poller is the correctness guarantee.

**Tech Stack:** FastAPI + SQLModel + `sse-starlette` (backend); React 19 + Zustand + TanStack Query + `sonner` + `openapi-fetch` (frontend); pytest (backend tests), Vitest + MSW (frontend tests).

**Spec:** `docs/superpowers/specs/2026-08-22-run-completion-delivery-design.md`

## Global Constraints

- Backend tests: `.venv/Scripts/python.exe -m pytest` — offline, no API key, no network.
- Backend lint: `ruff check` (must be clean).
- Frontend tests: run from `web/` — `npm run test:run`.
- Shell is PowerShell on Windows 11; the Bash tool is also available. Use forward slashes in paths.
- **ADR-0003 (tenancy):** `get_settings()` must never be cached across requests. Any new setting is read inside the request/route, never at import time or in a module-level constant.
- **Adding a field to `Settings` requires three files, not one.** `tests/test_config_documentation.py` asserts every `Settings` field has a row in `docs/configuration.md` **and** a line in `.env.example`. Omitting either fails the suite.
- **`RunManager._singleton_lock` is a `threading.RLock`** (`manager.py:201`), so calling `self.get()`, `self._root_for()`, or `self._write()` from inside a `with self._singleton_lock:` block is safe and intentional. Do not "fix" the nesting.
- **After any change to an API schema, regenerate contracts:** `make openapi` then `make client` (the latter runs `scripts/gen_ts_client.sh`, which rewrites `contracts/openapi.json`, `contracts/ts/api.ts`, and copies to `web/src/lib/api/schema.ts`). Commit the regenerated files with the task that changed the schema.
- Branch from `docs/run-completion-delivery-spec` (where the spec lives) so the spec and implementation land in one PR. `main` is protected — do not push to it directly.
- Commit after every task.

---

## File Structure

**Backend — create:**
- none

**Backend — modify:**
- `src/resume_tailor_harness/api/runs/models.py` — `RunSnapshot.announced_at` + parsing
- `src/resume_tailor_harness/api/runs/manager.py` — `mark_announced()`, widened `list_rehydratable()`, late-binding notify closure
- `src/resume_tailor_harness/api/schemas/runs.py` — `RunOut.announced_at`, `AckRunsIn`, `AckRunsOut`
- `src/resume_tailor_harness/api/routers/runs.py` — `POST /api/runs/ack`, pass the announce window into `list_rehydratable`
- `src/resume_tailor_harness/config.py` — `run_announce_window_seconds`
- `.env.example`, `docs/configuration.md` — required by `tests/test_config_documentation.py`
- `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` — regenerated

**Backend — test:**
- `tests/api/test_run_manager.py` — snapshot parsing, `mark_announced`, `list_rehydratable`, notifier regression
- `tests/api/test_run_ack_route.py` (create) — the ack endpoint

**Frontend — create:**
- `web/src/lib/runs/invalidation.ts` — which query keys a finished run refreshes
- `web/src/lib/runs/announce.ts` — completion toasts, including the batch cap
- `web/src/lib/runs/ack.ts` — the ack call
- `web/src/features/runs/use-run-completion-effects.ts` — registers the one global terminal listener
- `web/src/lib/runs/invalidation.test.ts`, `web/src/lib/runs/announce.test.ts`

**Frontend — modify:**
- `web/src/lib/runs/sse.ts` — becomes a pure wire→record translator
- `web/src/lib/runs/tracker.ts` — owns lifecycle, backoff, poller, terminal listeners
- `web/src/features/runs/use-launch-run.ts` — stops announcing; registers per-run invalidation keys
- `web/src/features/runs/use-rehydrate-runs.ts` — delegates to the poller
- `web/src/app/AppLayout.tsx` — mounts `useRunCompletionEffects()`
- `web/src/lib/runs/sse.test.ts`, `web/src/lib/runs/tracker.test.ts`

---

### Task 1: `announced_at` on the run snapshot

Pure data-model change. No behavior yet — later tasks read this field.

**Files:**
- Modify: `src/resume_tailor_harness/api/runs/models.py:27-45` (dataclass), `:97-127` (parser)
- Test: `tests/api/test_run_manager.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunSnapshot.announced_at: datetime | None` — `None` when the key is absent, malformed, or naive. Parsed with the existing `_aware_datetime` helper.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_run_manager.py`:

```python
def _raw_record(**overrides):
    base = {
        "process": "r1",
        "kind": "tailor",
        "state": "done",
        "label": "Tailoring",
        "current": 1,
        "total": 1,
        "started_at": "2026-08-22T00:00:00+00:00",
        "created_at": "2026-08-22T00:00:00+00:00",
        "updated_at": "2026-08-22T00:00:05+00:00",
    }
    base.update(overrides)
    return base


def test_snapshot_announced_at_is_none_when_absent():
    snapshot = parse_run_snapshot("r1", _raw_record())
    assert snapshot is not None
    assert snapshot.announced_at is None


def test_snapshot_parses_announced_at():
    snapshot = parse_run_snapshot(
        "r1", _raw_record(announced_at="2026-08-22T00:01:00+00:00")
    )
    assert snapshot is not None
    assert snapshot.announced_at == datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc)


def test_snapshot_rejects_unusable_announced_at():
    for value in ("not-a-date", "2026-08-22T00:01:00", 12345, None):
        snapshot = parse_run_snapshot("r1", _raw_record(announced_at=value))
        assert snapshot is not None
        assert snapshot.announced_at is None
```

`datetime` and `timezone` are already imported at the top of this test file.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -k announced -v
```

Expected: FAIL — `AttributeError: 'RunSnapshot' object has no attribute 'announced_at'`.

- [ ] **Step 3: Add the field and parse it**

In `src/resume_tailor_harness/api/runs/models.py`, add to the `RunSnapshot` dataclass, after `meta`:

```python
    announced_at: datetime | None = None
```

In `parse_run_snapshot`, add to the `RunSnapshot(...)` construction:

```python
        announced_at=_aware_datetime(raw.get("announced_at")),
```

`_aware_datetime` already returns `None` for non-strings, unparseable strings, and naive datetimes — which is exactly the third test's contract.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v
```

Expected: PASS, with no existing test broken (the field is optional with a default).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/models.py tests/api/test_run_manager.py && git commit -m "feat(runs): parse announced_at on the run snapshot"
```

---

### Task 2: `RunManager.mark_announced()`

The locked read-modify-write that stamps a terminal run as announced.

**Files:**
- Modify: `src/resume_tailor_harness/api/runs/manager.py` (add the method next to `get`, around `:517`)
- Test: `tests/api/test_run_manager.py`

**Interfaces:**
- Consumes: `RunSnapshot.announced_at` (Task 1).
- Produces: `RunManager.mark_announced(run_id: str, *, now: str | None = None) -> bool` — returns `True` only when it newly stamped the record. Returns `False` for an unknown run, a non-terminal run, or one already stamped. `now` is an ISO-8601 string injection point for tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_run_manager.py`:

```python
def test_mark_announced_stamps_a_terminal_run_once(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})

    assert mgr.mark_announced(run_id) is True
    snapshot = mgr.get(run_id)
    assert snapshot is not None and snapshot.announced_at is not None

    # Idempotent: a second ack changes nothing and reports nothing done.
    stamped = snapshot.announced_at
    assert mgr.mark_announced(run_id) is False
    assert mgr.get(run_id).announced_at == stamped


def test_mark_announced_refuses_unknown_and_active_runs(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    assert mgr.mark_announced("does-not-exist") is False

    pending = mgr.create("tailor")
    assert mgr.get(pending).state.value == "pending"
    assert mgr.mark_announced(pending) is False
    assert mgr.get(pending).announced_at is None


def test_mark_announced_preserves_the_rest_of_the_record(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"versions": 3}, meta={"jobId": 7})

    before = mgr.get(run_id)
    mgr.mark_announced(run_id)
    after = mgr.get(run_id)

    assert after.result == before.result == {"versions": 3}
    assert after.meta == before.meta == {"jobId": 7}
    assert after.state == before.state
    assert after.kind == before.kind
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -k mark_announced -v
```

Expected: FAIL — `AttributeError: 'RunManager' object has no attribute 'mark_announced'`.

- [ ] **Step 3: Implement the method**

In `src/resume_tailor_harness/api/runs/manager.py`, add immediately after `def get(...)`:

```python
    def mark_announced(self, run_id: str, *, now: str | None = None) -> bool:
        """Stamp a terminal run as announced. True only if newly stamped.

        Read-modify-write under the manager lock and re-reading inside it: a
        worker thread may still be flushing this run's record, and two browser
        tabs can ack the same run at once. Refusing non-terminal runs is what
        keeps this from ever turning a live progress write into a lost update.
        ``_singleton_lock`` is an RLock, so the nested ``get``/``_write`` calls
        are deliberate, not an oversight.
        """
        with self._singleton_lock:
            snapshot = self.get(run_id)
            if snapshot is None or snapshot.state not in TERMINAL_RUN_STATES:
                return False
            if snapshot.announced_at is not None:
                return False
            record = self._read_record(run_id)
            if record is None:
                return False
            record["announced_at"] = now or _now()
            self._write(run_id, record)
            return True
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v && ruff check
```

Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/manager.py tests/api/test_run_manager.py && git commit -m "feat(runs): add RunManager.mark_announced for terminal-run acknowledgement"
```

---

### Task 3: `list_rehydratable` returns unannounced terminal runs

**Files:**
- Modify: `src/resume_tailor_harness/api/runs/manager.py:534-583`, `src/resume_tailor_harness/config.py`, `.env.example`, `docs/configuration.md`
- Test: `tests/api/test_run_manager.py`

**Interfaces:**
- Consumes: `RunSnapshot.announced_at` (Task 1).
- Produces: `RunManager.list_rehydratable(user_id: str | None = None, *, announce_window_seconds: float | None = None, now: datetime | None = None) -> list[RunSnapshot]`. When `announce_window_seconds` is `None` the behavior is exactly today's (active runs + failed revisions) — so every existing caller is unaffected. `Settings.run_announce_window_seconds: int` (default `3600`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_run_manager.py`:

```python
def test_list_rehydratable_omits_terminal_runs_without_a_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    mgr.submit("tailor", lambda reporter: {"ok": True})
    assert mgr.list_rehydratable() == []


def test_list_rehydratable_returns_unannounced_terminal_runs_in_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})

    visible = mgr.list_rehydratable(announce_window_seconds=3600)
    assert [item.run_id for item in visible] == [run_id]

    mgr.mark_announced(run_id)
    assert mgr.list_rehydratable(announce_window_seconds=3600) == []


def test_list_rehydratable_excludes_terminal_runs_past_the_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.submit("tailor", lambda reporter: {"ok": True})
    later = datetime.now(timezone.utc) + timedelta(seconds=7200)

    assert mgr.list_rehydratable(announce_window_seconds=3600, now=later) == []
    # Still individually readable — only announcement is windowed.
    assert mgr.get(run_id) is not None


def test_list_rehydratable_still_returns_active_runs_with_a_window(tmp_path):
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    pending = mgr.create("tailor")
    visible = mgr.list_rehydratable(announce_window_seconds=3600)
    assert [item.run_id for item in visible] == [pending]
```

Add `timedelta` to the test file's `from datetime import ...` line.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -k rehydratable -v
```

Expected: FAIL — `TypeError: list_rehydratable() got an unexpected keyword argument 'announce_window_seconds'`.

- [ ] **Step 3: Widen the method**

In `src/resume_tailor_harness/api/runs/manager.py`, change the import line to:

```python
from datetime import datetime, timedelta, timezone
```

Change the signature and docstring:

```python
    def list_rehydratable(
        self,
        user_id: str | None = None,
        *,
        announce_window_seconds: float | None = None,
        now: datetime | None = None,
    ) -> list[RunSnapshot]:
        """Active runs, failed revisions, and recently-finished unannounced runs.

        ``announce_window_seconds`` is what makes a completion recoverable after
        the client that launched it went away. It is opt-in so every existing
        caller keeps the old contract; only the ``GET /api/runs`` route passes it.
        """
```

Immediately after the `visible = {...}` comprehension, insert:

```python
        if announce_window_seconds is not None:
            cutoff = (now or datetime.now(timezone.utc)) - timedelta(
                seconds=announce_window_seconds
            )
            for snapshot in snapshots:
                if (
                    snapshot.state in TERMINAL_RUN_STATES
                    and snapshot.announced_at is None
                    and snapshot.updated_at >= cutoff
                ):
                    visible[snapshot.run_id] = snapshot
```

- [ ] **Step 4: Add the setting, its env example, and its doc row**

In `src/resume_tailor_harness/config.py`, next to the other run settings:

```python
    # How recently a terminal run must have finished to still be worth
    # announcing when a client reconnects. Beyond this it is stale news; the
    # record stays readable until the 24h sweep either way.
    run_announce_window_seconds: int = Field(default=3600, ge=0, le=86_400)
```

In `.env.example`, near the other run/LLM settings:

```
RUN_ANNOUNCE_WINDOW_SECONDS=3600
```

In `docs/configuration.md`, add a row in the same table as `CLUSTER_BATCH_SIZE` (line ~98), matching the existing `| \`NAME\` | \`default\` | description |` format:

```
| `RUN_ANNOUNCE_WINDOW_SECONDS` | `3600` | How recently a background run must have finished to be announced on reconnect; integer seconds from 0 through 86400. |
```

- [ ] **Step 5: Run the full suite to verify**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py tests/test_config_documentation.py -v && ruff check
```

Expected: PASS. If `test_config_documentation.py` fails, the `.env.example` line or the `docs/configuration.md` row is missing or misformatted.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/api/runs/manager.py src/resume_tailor_harness/config.py .env.example docs/configuration.md tests/api/test_run_manager.py && git commit -m "feat(runs): surface unannounced terminal runs from list_rehydratable"
```

---

### Task 4: `POST /api/runs/ack` and `RunOut.announcedAt`

**Files:**
- Modify: `src/resume_tailor_harness/api/schemas/runs.py:23-34`, `src/resume_tailor_harness/api/runs/sse.py:29-42` (`record_to_run`), `src/resume_tailor_harness/api/routers/runs.py:507-529`
- Create: `tests/api/test_run_ack_route.py`
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`

**Interfaces:**
- Consumes: `RunManager.mark_announced` (Task 2), `list_rehydratable(announce_window_seconds=...)` (Task 3).
- Produces:
  - `RunOut.announced_at: datetime | None = None` → `announcedAt` on the wire.
  - `AckRunsIn { run_ids: list[str] }` → `{ "runIds": [...] }`.
  - `AckRunsOut { acknowledged: int }` → `{ "acknowledged": 2 }`.
  - `POST /api/runs/ack` — always `200`. Unknown, non-terminal, already-acked, and other users' ids are skipped silently, never 404. Ownership is enforced per id.

**Route-ordering note:** `POST /runs/ack` cannot shadow `GET /runs/{run_id}` (different methods) and there is no other `POST /runs/{...}` single-segment route, so placement in the file is free. Put it directly after `list_runs` for readability.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_run_ack_route.py`:

```python
from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def _app(tmp_path):
    return create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )


def test_ack_stamps_terminal_runs_and_removes_them_from_the_listing(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})

        listed = client.get("/api/runs").json()["items"]
        assert [item["runId"] for item in listed] == [run_id]
        assert listed[0]["announcedAt"] is None

        response = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 1}

        assert client.get("/api/runs").json()["items"] == []
        assert client.get(f"/api/runs/{run_id}").json()["announcedAt"] is not None


def test_ack_is_idempotent_and_skips_unusable_ids(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})
        pending = app.state.run_manager.create("tailor")

        first = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert first.json() == {"acknowledged": 1}

        second = client.post(
            "/api/runs/ack", json={"runIds": [run_id, pending, "no-such-run"]}
        )
        assert second.status_code == 200
        assert second.json() == {"acknowledged": 0}


def test_ack_accepts_an_empty_list(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/runs/ack", json={"runIds": []})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_ack_route.py -v
```

Expected: FAIL — 404 on `/api/runs/ack`, and `KeyError: 'announcedAt'`.

- [ ] **Step 3: Add the schemas**

In `src/resume_tailor_harness/api/schemas/runs.py`, add `announced_at` as the last field of `RunOut`:

```python
    announced_at: datetime | None = None
```

Add `from datetime import datetime` to that file's imports, and add the two new models after `RunOut`:

```python
class AckRunsIn(CamelModel):
    """Runs the client has shown the user. Unknown or non-terminal ids are skipped."""

    run_ids: list[str] = Field(default_factory=list, max_length=200)


class AckRunsOut(CamelModel):
    acknowledged: int
```

In `src/resume_tailor_harness/api/runs/sse.py`, add to the `RunOut(...)` construction in `record_to_run`:

```python
        announced_at=snapshot.announced_at,
```

- [ ] **Step 4: Add the route and pass the window**

In `src/resume_tailor_harness/api/routers/runs.py`, add `AckRunsIn` and `AckRunsOut` to the existing `from resume_tailor_harness.api.schemas.runs import (...)` block, then change `list_runs` to pass the window and add the ack route after it:

```python
@router.get("/runs", response_model=Page[RunOut])
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, alias="pageSize", ge=1, le=200),
    mgr: RunManager = Depends(get_run_manager),
):
    context = current_context()
    # Read per request: settings must never be cached across requests (ADR-0003).
    window = get_settings().run_announce_window_seconds
    return to_page(
        paginate(
            mgr.list_rehydratable(
                user_id=context.user_id if context is not None else None,
                announce_window_seconds=window,
            ),
            page=page,
            page_size=page_size,
        ),
        RunOut,
    )


@router.post("/runs/ack", response_model=AckRunsOut)
def ack_runs(body: AckRunsIn, mgr: RunManager = Depends(get_run_manager)):
    """Record that the user has been shown these completions.

    Deliberately forgiving: an id that is unknown, already acked, still running,
    or owned by someone else is skipped rather than raising. The client is
    reporting what it displayed, and a partially stale batch is normal — failing
    the whole request would make the client re-announce everything it just showed.
    """
    context = current_context()
    user_id = context.user_id if context is not None else None
    acknowledged = 0
    for run_id in body.run_ids:
        snapshot = mgr.get(run_id)
        if snapshot is None or (user_id is not None and snapshot.user_id != user_id):
            continue
        if mgr.mark_announced(run_id):
            acknowledged += 1
    return AckRunsOut(acknowledged=acknowledged)
```

`get_settings` is already imported in this file (`from resume_tailor_harness.config import get_settings`).

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/api/ -v && ruff check
```

Expected: PASS, ruff clean.

- [ ] **Step 6: Regenerate the contracts**

```bash
make openapi && make client
```

Confirm `announcedAt`, `AckRunsIn`, and `/api/runs/ack` appear in `web/src/lib/api/schema.ts`.

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/api tests/api/test_run_ack_route.py contracts web/src/lib/api/schema.ts && git commit -m "feat(api): add POST /api/runs/ack and expose announcedAt on RunOut"
```

---

### Task 5: Fix the stale notifier binding

Independent of the ack work. A reconnected SSE stream currently gets no wakeups because the worker holds a bound method on a `StreamNotifier` the manager has already discarded.

**Files:**
- Modify: `src/resume_tailor_harness/api/runs/manager.py:306-320` (`reporter`)
- Test: `tests/api/test_run_manager.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature change. `RunProgressReporter._notify` becomes a closure resolving `self.notifier(run_id)` at call time.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_run_manager.py`:

```python
def test_reporter_wakes_the_current_notifier_after_release(tmp_path):
    """A reconnecting client gets a fresh notifier; the worker must find it.

    ``_release_terminal_notifier`` drops the notifier once nobody is subscribed,
    and ``notifier()`` then setdefaults a NEW object for the next subscriber. A
    reporter that captured the old object's bound method would wake an orphan
    and the reconnected stream would silently fall back to polling.
    """
    mgr = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = mgr.create("tailor")
    reporter = mgr.reporter(run_id, "tailor")

    original = mgr.notifier(run_id)
    # Simulate the release that happens when the last subscriber goes away.
    mgr._stream_notifiers.pop(run_id, None)

    replacement = mgr.notifier(run_id)
    assert replacement is not original

    woken = Event()
    replacement.notify = lambda: woken.set()  # type: ignore[method-assign]

    reporter.begin(1, "Tailoring")

    assert woken.is_set(), "reporter woke a discarded notifier"
```

`Event` is already imported from `threading` at the top of this test file.

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -k current_notifier -v
```

Expected: FAIL — `AssertionError: reporter woke a discarded notifier`.

- [ ] **Step 3: Make the binding late**

In `src/resume_tailor_harness/api/runs/manager.py`, inside `def reporter(...)`, change:

```python
            notify=self.notifier(run_id).notify,
```

to:

```python
            # Resolved at call time, not captured: ``_release_terminal_notifier``
            # can discard this run's notifier between reporter construction and
            # the next write, and a reconnecting client will have created a
            # replacement. A captured bound method would wake the orphan.
            notify=lambda: self.notifier(run_id).notify(),
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/api/ -v && ruff check
```

Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/manager.py tests/api/test_run_manager.py && git commit -m "fix(runs): resolve the stream notifier at wake time, not reporter construction"
```

---

### Task 6: `lib/runs/invalidation.ts`

Which query keys a finished run refreshes stops being knowledge that only the launch call site has.

**Files:**
- Create: `web/src/lib/runs/invalidation.ts`, `web/src/lib/runs/invalidation.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_INVALIDATE: readonly string[]` — `["shortlist", "pipeline", "triage", "job"]`
  - `rememberInvalidation(runId: string, keys: readonly string[]): void`
  - `forgetInvalidation(runId: string): void`
  - `invalidationKeys(runId: string, kind: string): string[]` — per-run override, else per-kind map, else `DEFAULT_INVALIDATE`
  - `resetInvalidationForTests(): void`

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/runs/invalidation.test.ts`:

```typescript
import { beforeEach, expect, it } from "vitest";

import {
  DEFAULT_INVALIDATE,
  forgetInvalidation,
  invalidationKeys,
  rememberInvalidation,
  resetInvalidationForTests,
} from "./invalidation";

beforeEach(() => resetInvalidationForTests());

it("falls back to the default keys for an unknown kind", () => {
  expect(invalidationKeys("r1", "somethingNew")).toEqual([...DEFAULT_INVALIDATE]);
});

it("uses the per-kind map for a run it never saw launched", () => {
  expect(invalidationKeys("r1", "refreshClusters")).toEqual(["match-gap"]);
  expect(invalidationKeys("r2", "profile-build")).toEqual([
    "profile-sources",
    "match-gap",
    "setup-status",
  ]);
});

it("prefers a remembered per-run override", () => {
  rememberInvalidation("r1", ["setup-status"]);
  expect(invalidationKeys("r1", "profile-build")).toEqual(["setup-status"]);
});

it("forgets an override so a recycled id cannot inherit it", () => {
  rememberInvalidation("r1", ["setup-status"]);
  forgetInvalidation("r1");
  expect(invalidationKeys("r1", "profile-build")).toEqual([
    "profile-sources",
    "match-gap",
    "setup-status",
  ]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm run test:run -- invalidation
```

Expected: FAIL — cannot resolve `./invalidation`.

- [ ] **Step 3: Implement the module**

Create `web/src/lib/runs/invalidation.ts`:

```typescript
/**
 * Which query keys a finished run should refresh.
 *
 * This used to be an argument to `launch()`, which meant a run discovered any
 * other way — by the reconciliation poller, or on page load after the launching
 * tab was gone — refreshed nothing, and the board silently kept stale data.
 * The launch call site is still the most specific source of truth when it
 * exists, so it registers an override; the per-kind map is the fallback for
 * every run this session did not launch.
 */

export const DEFAULT_INVALIDATE = [
  "shortlist",
  "pipeline",
  "triage",
  "job",
] as const;

const BY_KIND: Record<string, readonly string[]> = {
  refreshClusters: ["match-gap"],
  maintainTaxonomy: ["match-gap"],
  undoTaxonomyMaintenance: ["match-gap"],
  "profile-build": ["profile-sources", "match-gap", "setup-status"],
  "github-sync": ["profile-sources"],
  gmailSync: ["notifications"],
};

const overrides = new Map<string, readonly string[]>();

export function rememberInvalidation(
  runId: string,
  keys: readonly string[],
): void {
  overrides.set(runId, [...keys]);
}

export function forgetInvalidation(runId: string): void {
  overrides.delete(runId);
}

export function invalidationKeys(runId: string, kind: string): string[] {
  return [...(overrides.get(runId) ?? BY_KIND[kind] ?? DEFAULT_INVALIDATE)];
}

export function resetInvalidationForTests(): void {
  overrides.clear();
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web && npm run test:run -- invalidation
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs/invalidation.ts web/src/lib/runs/invalidation.test.ts && git commit -m "feat(web): make run invalidation keys a property of the run, not the call site"
```

---

### Task 7: `lib/runs/announce.ts`

Move `announceCompletion` out of the launch closure and add the batch cap.

**Files:**
- Create: `web/src/lib/runs/announce.ts`, `web/src/lib/runs/announce.test.ts`
- Modify: `web/src/features/runs/use-launch-run.ts:13-61` (delete the local `announceCompletion`)

**Interfaces:**
- Consumes: `RunRecord` from `./store`.
- Produces: `announceCompletions(runs: readonly RunRecord[]): void` — 3 or fewer runs produce one toast each; 4 or more produce exactly one summary toast and no individual ones. An empty array does nothing.
- `ANNOUNCE_TOAST_CAP = 3` is exported for the test.

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/runs/announce.test.ts`:

```typescript
import { beforeEach, expect, it, vi } from "vitest";

import type { RunRecord } from "./store";

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));

import { announceCompletions } from "./announce";

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "",
    current: 1,
    total: 1,
    etaText: null,
    result: { jobs: [{ versionCount: 2 }] },
    ...overrides,
  };
}

beforeEach(() => {
  toast.success.mockReset();
  toast.error.mockReset();
  toast.info.mockReset();
});

it("does nothing for an empty batch", () => {
  announceCompletions([]);
  expect(toast.success).not.toHaveBeenCalled();
});

it("announces a tailor completion with its version count", () => {
  announceCompletions([run()]);
  expect(toast.success).toHaveBeenCalledOnce();
  expect(toast.success.mock.calls[0][0]).toContain("2 resume versions");
});

it("routes failures and cancellations to their own toast kinds", () => {
  announceCompletions([run({ status: "failed", error: "boom" })]);
  expect(toast.error).toHaveBeenCalledOnce();

  announceCompletions([run({ status: "cancelled" })]);
  expect(toast.info).toHaveBeenCalledOnce();
});

it("gives three completions three toasts", () => {
  announceCompletions([
    run({ runId: "a" }),
    run({ runId: "b" }),
    run({ runId: "c" }),
  ]);
  expect(toast.success).toHaveBeenCalledTimes(3);
});

it("collapses four completions into exactly one summary toast", () => {
  announceCompletions([
    run({ runId: "a" }),
    run({ runId: "b" }),
    run({ runId: "c" }),
    run({ runId: "d" }),
  ]);
  expect(toast.success).toHaveBeenCalledOnce();
  expect(toast.success.mock.calls[0][0]).toContain("4 runs finished");
  expect(toast.error).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm run test:run -- announce
```

Expected: FAIL — cannot resolve `./announce`.

- [ ] **Step 3: Implement the module**

Create `web/src/lib/runs/announce.ts` by moving the body of `announceCompletion` out of `use-launch-run.ts` verbatim and wrapping it in the batch cap:

```typescript
import { toast } from "sonner";

import type { RunRecord } from "./store";

/**
 * Completions arrive one at a time on the live path and in batches when a
 * client reconnects after a disconnect. Past this many in one batch, individual
 * toasts stop being information and start being a wall — so the batch collapses
 * into a single summary. The cap limits noise only; every run is still acked.
 */
export const ANNOUNCE_TOAST_CAP = 3;

function announceOne(run: RunRecord): void {
  if (run.status === "failed") {
    toast.error(`${run.kind} failed: ${run.error ?? "unknown error"}`);
    return;
  }
  if (run.status === "cancelled") {
    toast.info(`${run.kind} cancelled`);
    return;
  }
  if (run.kind === "tailor") {
    const rawJobs = (run.result as { jobs?: unknown } | null)?.jobs;
    const jobs: unknown[] = Array.isArray(rawJobs) ? rawJobs : [];
    const versions = jobs.reduce<number>((total, job) => {
      const count = (job as { versionCount?: unknown } | null)?.versionCount;
      return total + (typeof count === "number" ? count : 0);
    }, 0);
    toast.success(
      `Tailoring complete: ${versions} resume versions created. Open a job's Versions tab to render PDF.`,
    );
    return;
  }
  if (run.kind === "refreshClusters") {
    const result = (run.result as Record<string, unknown> | null) ?? {};
    const count = (key: string) =>
      typeof result[key] === "number" ? result[key] : 0;
    toast.success(
      `Regroup complete: ${count("assignedSkills")} assigned · ${count("aliasesMerged")} aliases merged · ${count("domainsCreated")} domains created · ${count("uncertainSkills")} uncertain · ${count("failedSkills")} failed · ${count("skippedStaleSkills")} skipped.`,
    );
    return;
  }
  if (run.kind === "maintainTaxonomy") {
    const result = (run.result as Record<string, unknown> | null) ?? {};
    const actions = Array.isArray(result.actions) ? result.actions.length : 0;
    toast.success(
      result.changed
        ? `Taxonomy maintenance applied ${actions} change${actions === 1 ? "" : "s"}.`
        : "Taxonomy maintenance found no safe changes.",
    );
    return;
  }
  if (run.kind === "undoTaxonomyMaintenance") {
    toast.success("Restored the previous taxonomy maintenance generation.");
    return;
  }
  toast.success(`${run.kind} completed`);
}

export function announceCompletions(runs: readonly RunRecord[]): void {
  if (runs.length === 0) return;
  if (runs.length > ANNOUNCE_TOAST_CAP) {
    const failed = runs.filter((run) => run.status === "failed").length;
    const detail = failed > 0 ? ` (${failed} failed)` : "";
    toast.success(`${runs.length} runs finished while you were away${detail}.`);
    return;
  }
  for (const run of runs) announceOne(run);
}
```

Delete `announceCompletion` from `web/src/features/runs/use-launch-run.ts` and remove its now-unused `import { toast } from "sonner"` only if no other code in that file uses `toast` — `launch`'s catch block and `cancelRun` both still do, so **keep the import**.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web && npm run test:run -- announce && npx tsc -b --noEmit
```

Expected: announce tests PASS. `use-launch-run.ts` will not typecheck yet if it still calls `announceCompletion` — Task 11 rewires it. If you want a green tree at this commit, temporarily point its `onDone` at `announceCompletions([completed])`; Task 11 removes that.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs/announce.ts web/src/lib/runs/announce.test.ts web/src/features/runs/use-launch-run.ts && git commit -m "feat(web): extract run completion announcements with a batch cap"
```

---

### Task 8: `lib/runs/ack.ts`

**Files:**
- Create: `web/src/lib/runs/ack.ts`

**Interfaces:**
- Consumes: `POST /api/runs/ack` (Task 4).
- Produces: `ackRuns(runIds: readonly string[]): Promise<void>` — never throws. A failed ack is logged-and-swallowed: re-announcing once after a reload is strictly better than blowing up the completion path.

- [ ] **Step 1: Write the module**

There is no separate test file for this — it is exercised through `tracker.test.ts` in Task 10, which asserts the call is made. Create `web/src/lib/runs/ack.ts`:

```typescript
import { api, unwrap } from "@/lib/api/client";

/**
 * Tell the server these completions have been shown to the user, so a later
 * reconnect does not announce them again.
 *
 * Never throws. The client also holds an in-session guard, so a failed ack
 * cannot double-announce within this session; the worst case is one repeat
 * after a reload. Losing a completion is the bug we are fixing — showing one
 * twice is a nuisance.
 */
export async function ackRuns(runIds: readonly string[]): Promise<void> {
  if (runIds.length === 0) return;
  try {
    await unwrap(api.POST("/api/runs/ack", { body: { runIds: [...runIds] } }));
  } catch {
    // Intentionally swallowed — see above.
  }
}
```

- [ ] **Step 2: Verify it typechecks against the generated client**

```bash
cd web && npx tsc -b --noEmit
```

Expected: no error on `/api/runs/ack`. If the path is unknown, `make openapi && make client` was not run in Task 4.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/runs/ack.ts && git commit -m "feat(web): add the run acknowledgement call"
```

---

### Task 9: Move run lifecycle from `sse.ts` into `tracker.ts`

The structural change. `sse.ts` and `tracker.ts` must change together — an intermediate state where `sse.ts` has stopped removing runs but `tracker.ts` has not started would leave every finished run in the store forever.

**Files:**
- Modify: `web/src/lib/runs/sse.ts:36-100`, `web/src/lib/runs/tracker.ts` (whole file), `web/src/lib/runs/sse.test.ts`, `web/src/lib/runs/tracker.test.ts`

**Interfaces:**
- Consumes: `announceCompletions` (Task 7), `ackRuns` (Task 8), `invalidationKeys`/`forgetInvalidation` (Task 6).
- Produces:
  - `watchRun(runId, kind, onDone?, onTransportError?): () => void` — unchanged signature; `onmessage` no longer touches `useRunStore.remove` and no longer schedules removal.
  - `type TerminalListener = (runs: RunRecord[]) => void`
  - `addTerminalListener(listener: TerminalListener): () => void` — returns an unsubscribe.
  - `completeRuns(runs: readonly RunRecord[]): void` — the one lifecycle path: upsert, dedupe, notify listeners as a batch, schedule removal.
  - `TERMINAL_DISPLAY_MS = 4000`

- [ ] **Step 1: Write the failing tests**

Add to `web/src/lib/runs/sse.test.ts`:

```typescript
it("leaves store removal to the tracker", async () => {
  watchRun("r1", "tailor");
  await vi.waitFor(() => expect(FakeEventSource.current).toBeDefined());

  FakeEventSource.current.onmessage?.({
    data: JSON.stringify({ state: "done", percent: 100, label: "Done" }),
  } as MessageEvent);

  vi.advanceTimersByTime(10_000);
  expect(useRunStore.getState().runs.r1).toBeDefined();
});
```

Add to `web/src/lib/runs/tracker.test.ts`. The tracker never calls `announceCompletions` or `ackRuns` — those belong to the React listener in Task 11 — so no new module mocks are needed here; the test observes effects through a registered listener instead.

```typescript
import { addTerminalListener, completeRuns } from "./tracker";
import { useRunStore } from "./store";

it("runs one lifecycle for a completion and removes it after the display window", () => {
  vi.useFakeTimers();
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  const finished = {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
  } satisfies RunRecord;
  completeRuns([finished]);

  expect(seen).toEqual([[finished]]);
  expect(useRunStore.getState().runs.r1?.percent).toBe(100);

  vi.advanceTimersByTime(4000);
  expect(useRunStore.getState().runs.r1).toBeUndefined();
  vi.useRealTimers();
});

it("announces a completion exactly once even if two paths report it", () => {
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  const finished = {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "Done",
    current: 1,
    total: 1,
    etaText: null,
  } satisfies RunRecord;

  completeRuns([finished]);
  completeRuns([finished]);

  expect(seen).toEqual([[finished]]);
});

it("keeps a failed revise visible for the retry UI", () => {
  vi.useFakeTimers();
  completeRuns([
    {
      runId: "r9",
      kind: "revise",
      status: "failed",
      percent: 40,
      phase: "",
      current: 0,
      total: 1,
      etaText: null,
      error: "boom",
      meta: { versionId: 3, instruction: "tighten the summary" },
    },
  ]);

  vi.advanceTimersByTime(10_000);
  expect(useRunStore.getState().runs.r9).toBeDefined();
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm run test:run -- runs
```

Expected: FAIL — `completeRuns` and `addTerminalListener` are not exported.

- [ ] **Step 3: Strip lifecycle out of `sse.ts`**

In `web/src/lib/runs/sse.ts`, replace the terminal branch of `onmessage`:

```typescript
    useRunStore.getState().upsert(run);
    if (state === "done" || state === "error" || state === "cancelled") {
      eventSource.close();
      onDone?.(run);
    }
```

Delete the `setTimeout(... remove ...)` block and the `revise`/`coverLetterRevise` special case — both move to the tracker in Step 4. Remove the now-unused import of `useRunStore` only if nothing else in the file uses it (the non-terminal `upsert` above still does, so **keep it**).

- [ ] **Step 4: Give `tracker.ts` the lifecycle**

In `web/src/lib/runs/tracker.ts`, add the imports and the lifecycle machinery:

```typescript
import { forgetInvalidation } from "./invalidation";

/** How long a finished run stays on screen at 100% before the bar collapses. */
export const TERMINAL_DISPLAY_MS = 4000;

export type TerminalListener = (runs: RunRecord[]) => void;

const terminalListeners = new Set<TerminalListener>();
/** Runs already put through the lifecycle, so SSE and the poller cannot double-fire. */
const completed = new Set<string>();

export function addTerminalListener(listener: TerminalListener): () => void {
  terminalListeners.add(listener);
  return () => terminalListeners.delete(listener);
}

/** Failed revisions carry the retry instruction in `meta`; the retry UI needs them. */
function isDurableFailure(run: RunRecord): boolean {
  return (
    run.status === "failed" &&
    ["revise", "coverLetterRevise"].includes(run.kind)
  );
}

/**
 * The single terminal path, reached from the SSE stream and from the poller
 * alike. Batched because a reconnect can surface several completions at once
 * and the announcement cap is a property of the batch, not of each run.
 */
export function completeRuns(runs: readonly RunRecord[]): void {
  const fresh = runs.filter((run) => !completed.has(run.runId));
  if (fresh.length === 0) return;
  for (const run of fresh) {
    completed.add(run.runId);
    useRunStore.getState().upsert(run);
  }
  for (const listener of terminalListeners) listener([...fresh]);
  for (const run of fresh) {
    forgetInvalidation(run.runId);
    if (isDurableFailure(run)) continue;
    setTimeout(() => useRunStore.getState().remove(run.runId), TERMINAL_DISPLAY_MS);
  }
}
```

Change `finish` to route through it:

```typescript
function finish(entry: TrackedRun, run: RunRecord): void {
  entry.unsubscribe();
  tracked.delete(entry.seed.runId);
  completeRuns([run]);
  for (const callback of entry.callbacks) callback(run);
}
```

Extend `resetRunTrackerForTests` so state does not leak between tests:

```typescript
export function resetRunTrackerForTests(): void {
  for (const entry of tracked.values()) entry.unsubscribe();
  tracked.clear();
  terminalListeners.clear();
  completed.clear();
}
```

The tracker deliberately imports **neither** `announceCompletions` nor `ackRuns`. It emits terminal batches and nothing more; the React-side listener registered in Task 11 turns them into toasts, acks, and invalidations. Keeping that inversion is what lets the tracker stay a module singleton with no `QueryClient` and no `sonner` dependency — and it is why `completeRuns` is testable with a plain listener and no module mocks.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd web && npm run test:run -- runs && npx tsc -b --noEmit
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/runs/sse.ts web/src/lib/runs/tracker.ts web/src/lib/runs/sse.test.ts web/src/lib/runs/tracker.test.ts && git commit -m "refactor(web): move run lifecycle out of the SSE transport into the tracker"
```

---

### Task 10: Unbounded reconnect and the reconciliation poller

**Files:**
- Modify: `web/src/lib/runs/tracker.ts`, `web/src/lib/runs/tracker.test.ts`, `web/src/features/runs/use-rehydrate-runs.ts`

**Interfaces:**
- Consumes: `completeRuns` (Task 9).
- Produces:
  - `startRunPoller(): void` — idempotent; starts the interval if it is not already running.
  - `stopRunPoller(): void`
  - `pollRunsNow(): Promise<void>` — one reconciliation pass; exported so tests and `useRehydrateRuns` can drive it without waiting on a timer.
  - `POLL_INTERVAL_MS = 15_000`, `RECONNECT_MAX_MS = 30_000`
- Reconnect delay sequence: `1000, 2000, 4000, 8000, 16000, 30000, 30000, …` with ±20 % jitter, reset to `1000` on any received message. No attempt cap.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/lib/runs/tracker.test.ts`:

```typescript
it("reconnects indefinitely with backoff instead of giving up after one try", async () => {
  vi.useFakeTimers();
  mocks.apiGet.mockResolvedValue({ data: { items: [] }, error: undefined });
  trackRun({ runId: "r1", kind: "tailor" });

  // Fail the transport five times; the old cap gave up after one.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const onError = mocks.watchRun.mock.calls.at(-1)![3] as () => void;
    onError();
    await vi.advanceTimersByTimeAsync(60_000);
  }

  expect(mocks.watchRun.mock.calls.length).toBeGreaterThan(5);
  expect(isTracking("r1")).toBe(true);
  vi.useRealTimers();
});

it("finishes a tracked run the poller finds terminal", async () => {
  mocks.apiGet.mockResolvedValue({
    data: {
      items: [
        {
          runId: "r1",
          kind: "tailor",
          state: "done",
          label: "Done",
          percent: 100,
          current: 1,
          total: 1,
        },
      ],
    },
    error: undefined,
  });
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));
  trackRun({ runId: "r1", kind: "tailor" });

  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["r1"]);
  expect(isTracking("r1")).toBe(false);
});

it("announces a terminal run it never tracked", async () => {
  mocks.apiGet.mockResolvedValue({
    data: {
      items: [
        {
          runId: "orphan",
          kind: "tailor",
          state: "done",
          label: "Done",
          percent: 100,
          current: 1,
          total: 1,
        },
      ],
    },
    error: undefined,
  });
  const seen: RunRecord[][] = [];
  addTerminalListener((runs) => seen.push(runs));

  await pollRunsNow();

  expect(seen.flat().map((run) => run.runId)).toEqual(["orphan"]);
});

it("starts tracking an active run it discovers", async () => {
  mocks.apiGet.mockResolvedValue({
    data: {
      items: [
        {
          runId: "live",
          kind: "tailor",
          state: "running",
          label: "Tailoring",
          percent: 40,
          current: 2,
          total: 5,
        },
      ],
    },
    error: undefined,
  });

  await pollRunsNow();

  expect(isTracking("live")).toBe(true);
});
```

Update the file's `stateToStatus` mock so it maps every state the tests use:

```typescript
vi.mock("./sse", () => ({
  stateToStatus: (state: string) =>
    state === "done"
      ? "succeeded"
      : state === "error"
        ? "failed"
        : state === "cancelled"
          ? "cancelled"
          : "running",
  watchRun: mocks.watchRun,
}));
```

Add `pollRunsNow` to the tracker import line.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm run test:run -- tracker
```

Expected: FAIL — `pollRunsNow` is not exported; the reconnect test stops at 2 calls.

- [ ] **Step 3: Replace the reconnect policy**

In `web/src/lib/runs/tracker.ts`, replace the `reconnects` field on `TrackedRun` with `delayMs: number`, and replace `reconcile` with:

```typescript
export const POLL_INTERVAL_MS = 15_000;
export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_MAX_MS = 30_000;

function nextDelay(current: number): number {
  const raw = Math.min(current * 2, RECONNECT_MAX_MS);
  return Math.round(raw * (0.8 + Math.random() * 0.4));
}

/**
 * A dropped stream is not evidence the run failed, and there is no honest
 * number of retries at which it becomes evidence. The old `reconnects < 1`
 * cap simply picked a point to start being silently wrong. Unbounded retry is
 * affordable here because the poller independently reconciles every tracked
 * run, so a stream that never comes back costs one request per POLL_INTERVAL_MS.
 */
function scheduleReconnect(entry: TrackedRun): void {
  if (tracked.get(entry.seed.runId) !== entry) return;
  const delay = entry.delayMs;
  entry.delayMs = nextDelay(entry.delayMs);
  setTimeout(() => {
    if (tracked.get(entry.seed.runId) !== entry) return;
    subscribe(entry);
  }, delay);
}
```

Change `subscribe` to reset the delay on a received message and to schedule instead of give up:

```typescript
function subscribe(entry: TrackedRun): void {
  entry.unsubscribe = watchRun(
    entry.seed.runId,
    entry.seed.kind,
    (run) => finish(entry, run),
    () => scheduleReconnect(entry),
    () => {
      entry.delayMs = RECONNECT_BASE_MS;
    },
  );
}
```

Add the fifth parameter to `watchRun` in `web/src/lib/runs/sse.ts`:

```typescript
export function watchRun(
  runId: string,
  kind: string,
  onDone?: (run: RunRecord) => void,
  onTransportError?: () => void,
  onMessage?: () => void,
): () => void {
```

and call `onMessage?.()` as the first statement inside `eventSource.onmessage`, before the `JSON.parse`.

In `trackRun`, initialise `delayMs: RECONNECT_BASE_MS` instead of `reconnects: 0`, and call `startRunPoller()` at the end.

- [ ] **Step 4: Add the poller**

Append to `web/src/lib/runs/tracker.ts`:

```typescript
const TERMINAL_STATUSES = ["succeeded", "failed", "cancelled"] as const;

let pollTimer: ReturnType<typeof setInterval> | null = null;

/**
 * Reconcile every run the server considers live or newly finished.
 *
 * This is the correctness guarantee; SSE is only the latency optimisation. It
 * covers three cases the live stream cannot: a run whose stream died, a run
 * that finished while no client was connected, and a run launched from another
 * tab or device.
 */
export async function pollRunsNow(): Promise<void> {
  let items: RunStatusPayload[];
  try {
    const page = (await unwrap(
      api.GET("/api/runs", { params: { query: { page: 1, pageSize: 200 } } }),
    )) as { items?: RunStatusPayload[] };
    items = page.items ?? [];
  } catch {
    return; // A transport error is not evidence about any run.
  }

  const finished: RunRecord[] = [];
  for (const payload of items) {
    const run = recordFromStatus(payload);
    if (TERMINAL_STATUSES.includes(run.status as (typeof TERMINAL_STATUSES)[number])) {
      const entry = tracked.get(run.runId);
      if (entry) {
        entry.unsubscribe();
        tracked.delete(run.runId);
        for (const callback of entry.callbacks) callback(run);
      }
      finished.push(run);
      continue;
    }
    useRunStore.getState().upsert(run);
    if (!tracked.has(run.runId)) trackRun({ runId: run.runId, kind: run.kind });
  }
  // One batch, so the announcement cap sees the whole reconnect at once.
  completeRuns(finished);
  if (tracked.size === 0) stopRunPoller();
}

export function startRunPoller(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => void pollRunsNow(), POLL_INTERVAL_MS);
}

export function stopRunPoller(): void {
  if (pollTimer === null) return;
  clearInterval(pollTimer);
  pollTimer = null;
}
```

`recordFromStatus` already exists in this file but expects `kind` on the payload; `RunOut` supplies it, so widen `RunStatusPayload` to `interface RunStatusPayload extends RunSeed { ... }` as it already is — no change needed. Call `stopRunPoller()` from `resetRunTrackerForTests`.

- [ ] **Step 5: Point `useRehydrateRuns` at the poller**

Replace the body of `web/src/features/runs/use-rehydrate-runs.ts` with:

```typescript
import { useEffect } from "react";

import { pollRunsNow, startRunPoller, stopRunPoller } from "@/lib/runs/tracker";

/**
 * Recover in-flight and recently-finished runs on mount.
 *
 * The reconciliation pass itself lives in the tracker, so `/api/runs` has one
 * owner: this hook used to fetch it independently, which meant a reload and a
 * poll tick could disagree about what was running.
 */
export function useRehydrateRuns(): void {
  useEffect(() => {
    void pollRunsNow();
    startRunPoller();
    return () => stopRunPoller();
  }, []);
}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd web && npm run test:run && npx tsc -b --noEmit && npm run lint
```

Expected: PASS. If `use-rehydrate-runs.test.tsx` exists and asserts the old direct-fetch behavior, update it to assert `pollRunsNow` ran instead.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/runs/tracker.ts web/src/lib/runs/sse.ts web/src/lib/runs/tracker.test.ts web/src/features/runs/use-rehydrate-runs.ts && git commit -m "feat(web): unbounded SSE reconnect plus a run reconciliation poller"
```

---

### Task 11: Wire the global completion effects

**Files:**
- Create: `web/src/features/runs/use-run-completion-effects.ts`
- Modify: `web/src/features/runs/use-launch-run.ts`, `web/src/app/AppLayout.tsx:113`

**Interfaces:**
- Consumes: `addTerminalListener` (Task 9), `announceCompletions` (Task 7), `ackRuns` (Task 8), `invalidationKeys`/`rememberInvalidation` (Task 6).
- Produces: `useRunCompletionEffects(): void` — mounted once at the app root.

- [ ] **Step 1: Write the hook**

Create `web/src/features/runs/use-run-completion-effects.ts`:

```typescript
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ackRuns } from "@/lib/runs/ack";
import { announceCompletions } from "@/lib/runs/announce";
import { invalidationKeys } from "@/lib/runs/invalidation";
import { addTerminalListener } from "@/lib/runs/tracker";

/**
 * The one place a finished run turns into user-visible effects.
 *
 * Mount once, at the app root. It lives in React rather than in the tracker
 * because it needs the QueryClient, and the tracker is a module singleton with
 * no business holding one. Announcement runs before invalidation: a completion
 * notice should never wait on a board refetch.
 */
export function useRunCompletionEffects(): void {
  const queryClient = useQueryClient();
  useEffect(
    () =>
      addTerminalListener((runs) => {
        announceCompletions(runs);
        void ackRuns(runs.map((run) => run.runId));
        const keys = new Set(
          runs.flatMap((run) => invalidationKeys(run.runId, run.kind)),
        );
        for (const key of keys) {
          void queryClient.invalidateQueries({ queryKey: [key] });
        }
      }),
    [queryClient],
  );
}
```

- [ ] **Step 2: Simplify `useLaunchRun`**

In `web/src/features/runs/use-launch-run.ts`, import `rememberInvalidation` from `@/lib/runs/invalidation`, drop the `announceCompletion`/`announceCompletions` call and the `qc` usage from the `trackRun` callback, and register the caller's keys instead:

```typescript
      rememberInvalidation(run.runId, invalidate);
      useRunStore.getState().upsert({ /* unchanged */ });
      trackRun({ runId: run.runId, kind });
```

Remove the now-unused `useQueryClient` import and the `const qc = useQueryClient();` line if nothing else in the file uses them. Keep the `invalidate` parameter on `launch` — all ~25 call sites still pass it, and it is now the per-run override.

- [ ] **Step 3: Mount the hook**

In `web/src/app/AppLayout.tsx`, add the import next to `useRehydrateRuns` and call it on the line after:

```typescript
import { useRunCompletionEffects } from "@/features/runs/use-run-completion-effects";
```

```typescript
  useRehydrateRuns();
  useRunCompletionEffects();
```

Order matters: the listener must be registered before the first poll dispatches a batch. `useEffect` bodies run in declaration order, and `useRehydrateRuns` calls `pollRunsNow()` asynchronously, so registering second is still safe — but declare `useRunCompletionEffects()` **first** to remove the timing question entirely.

- [ ] **Step 4: Run the full frontend suite**

```bash
cd web && npm run test:run && npx tsc -b --noEmit && npm run lint
```

Expected: PASS, no type errors, no lint errors. In particular `use-launch-run.test.tsx` (if it asserts toasts) should now assert that no toast fires from the launch path itself.

- [ ] **Step 5: Run the full backend suite**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
```

Expected: PASS, ruff clean.

- [ ] **Step 6: Verify end to end**

Start the app, launch a tailor run, and while it is running restart the backend to kill the SSE stream. Confirm without touching the page:

1. the bar keeps updating (poller) and reaches **100%** when the run finishes,
2. the completion toast appears,
3. the board shows the new resume versions,
4. reloading the page does **not** re-announce the same completion.

Then launch a run, close the tab before it finishes, and reopen: the completion should be announced exactly once on load.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/runs web/src/app/AppLayout.tsx && git commit -m "feat(web): announce, ack, and invalidate every run completion from one listener"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| `announced_at` on the run record, threaded to `RunOut.announcedAt` | 1, 4 |
| `list_rehydratable` widened by one clause, windowed | 3 |
| `run_announce_window_seconds` setting (default 3600) | 3 |
| `POST /api/runs/ack`, idempotent, ownership-checked, forgiving | 4 |
| Locked read-modify-write for ack | 2 |
| `sse.ts` becomes a pure translator | 9 |
| `tracker.ts` owns the lifecycle; failed-`revise` exemption rehomed | 9 |
| Reconciliation poller (15 s), one owner of `/api/runs` | 10 |
| Unbounded reconnect with capped backoff and jitter | 10 |
| Toast fires before invalidation | 11 |
| Late-binding notifier | 5 |
| Invalidation keys as a property of the run kind | 6, 11 |
| 3-or-fewer individual toasts, 4-or-more one summary | 7 |
| Ack failure degrades safely (in-session guard) | 8, 9 |
| End-to-end kill-the-stream check | 11 |

No spec requirement is unassigned.

**Placeholder scan:** No "TBD", "add appropriate error handling", or "similar to Task N". Every code step carries the literal code.

**Type consistency:** `announced_at` (Python) / `announcedAt` (wire, TS) used consistently. `completeRuns` (plural, batched) is the name in Tasks 9, 10, 11 — not `completeRun`. `invalidationKeys(runId, kind)` takes both arguments everywhere it appears. `TerminalListener` receives `RunRecord[]`, never a single record. `mark_announced` is the Python method name in Tasks 2, 3, and 4.

**Known intermediate state** (called out in the task itself rather than hidden): Task 7 leaves `use-launch-run.ts` temporarily calling `announceCompletions` directly until Task 11 rewires it. Every other task leaves the tree green.

**Fixed during this review:** Task 9 originally had the tracker import `announceCompletions` and `ackRuns` "for Task 10's poller" — but the poller reaches them through `completeRuns`' listeners, so those imports would have been dead and would have failed lint. Removed, along with the module mocks the tracker test no longer needs. This is the dependency inversion the design depends on: the tracker emits, React reacts.
