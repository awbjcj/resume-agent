# Architecture Deepening Round 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the half-executed round-3 deepenings, extract the Session substrate the Coach and Interview stacks copied, deepen the board filter query into one dependency, measure (then conditionally fix) the board read path, and bring the docs (CLAUDE.md, CONTEXT.md, ADR index, round-3 plan status) back in sync with reality.

**Architecture:** Every code task is a behavior-preserving deepening: an existing, duplicated piece of knowledge gets exactly one author behind one interface. New seams: `sessions/store.py` (**Session substrate** — file custody for ADR-0006 turn-per-run sessions, with the coach and interview stores as its two adapters), `sessions/turns.py` (one `TurnRejected` + one `format_with_retry`), and `board_filter_query` (the board endpoints' shared query surface). The performance phase is measurement-first per the performance-optimization discipline: a benchmark task produces numbers; the fix task runs only if its stated threshold is exceeded.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, pydantic v2, pytest (offline — every agent and the browser are faked), Typer CLI, React/TS web (untouched except regenerated contracts in Task 7).

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline; no API key, no network). Lint: `ruff check`.
- **Prerequisite:** Task 1 executes the remaining tasks of `docs/superpowers/plans/2026-07-16-architecture-deepening-round-3.md` (Tasks 4–9; Tasks 1–3 already shipped in `72dc10c`). Tasks 2+ of THIS plan depend on round-3 Task 6 (`api/runs/launch.py`) existing.
- **Contract policy:** `contracts/openapi.json` must be byte-identical after every task EXCEPT Task 7, which may regenerate it with an order-only diff (verified by the jq gate inside that task). No parameter, route, or schema may be added, removed, renamed, or retyped anywhere in this plan.
- **Dirty working tree:** the checkout has unrelated uncommitted Gmail changes (`src/resume_agent/api/routers/gmail.py`, `web/src/features/settings/*`). NEVER run `git add -A` or `git add .` — stage files explicitly in every commit, including when executing the round-3 plan (its Tasks 4–5 say `git add -A`; substitute the explicit file lists given in Task 1 below).
- Behavior-preserving: every existing test passes unmodified unless a task explicitly says otherwise (no task in this plan modifies an existing test's assertions).
- Vocabulary: CONTEXT.md terms (Coach session, Board seam, Workspace, UserContext) plus the two terms Task 11 adds (Session substrate, Launch seam).
- Windows dev box: use `.venv/Scripts/python.exe -m pytest ...` exactly as written.
- Commit after every task (small, single-purpose commits).

---

## Background for implementers (read once)

1. **Round-3 status:** Phase A (registry unit-addressing: `find_unit`, `spec_for`, spec table walks in `services/sources.py`) shipped in commit `72dc10c`. Phases B (workspace layout constants), C (launch seam), D (JobDetailRow inheritance) did not: `"data/profile/facts.json"` is still declared in 10 modules, and the submit→get→assert→`record_to_run` tail is copied in `api/routers/runs.py`, `coach.py`, `interview.py`, `profile.py`, `sources.py`, `match_gap.py`.
2. **The twin session stores:** `profile/coach_store.py` and `interview/store.py` duplicate ~120 lines exactly: the `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` session-id regex, `_session_path` (`session-<id>.json`), a module-level `threading.RLock` context manager, `_now()` (UTC ISO seconds), validated `_read`/`_write` through `atomic_write_text`, `list_sessions` (glob + archived filter + `(started_at, session_id)` sort), `load_session`, active filtering, `mutate_session` (load→fn→write→reload under lock), `archive_session`/`unarchive_session` (identical error strings: "only ended sessions can be archived", "session already archived", "session not archived"), and `delete_session`. Kind-specific logic (coach: agenda topics, draft notes, recap, impact; interview: job scoping, plan items, debrief) is genuine variation and stays put.
3. **`TurnRejected` is defined twice** — `profile/coach.py:75` and `interview/agent.py:67`, both `class TurnRejected(ValueError)`. `_format_with_retry` is copied in `services/profile_coach.py` and `services/mock_interview.py`, differing only in the prompt label (`COACH NOTES` vs `INTERVIEWER NOTES`).
4. **Already cached — do NOT re-fix:** `profile.store.load_facts` and `taxonomy.skills.load_aliases` both carry an (mtime_ns, size)-keyed cache. The board read path's only remaining hydration suspicion is `jd_text`: `select(Job)` loads it for every row, but `ShortlistItem` and `TriageItem` never ship it (`PipelineItem` and `JobDetail` do — their queries must keep loading it).
5. **`BoardFilter`** (`services/board.py:56`) is a frozen dataclass — use `dataclasses.replace` to derive variants.
6. **Wire aliases** in the board query surface: `employmentType`, `companySize`, `minFit`, `maxFit`, `minSalary`, `staleDays`, `staleMinDays`, `sortBy`, `pageSize`. Per-endpoint `sortBy` defaults differ: shortlist `"fit"`, pipeline `"stage"`, triage `"fit"`. Triage additionally has `archived: bool = False` declared FIRST.
7. **`Job` table** (`tracking/tables.py`): every column except `source` is optional/defaulted — the benchmark seeds rows with `source`, `url`, `company`, `title`, `location`, `jd_text`, `status`, `fit_score`, `criteria_json`, `dedup_key`.

---

# Phase 0 — finish round 3

### Task 1: Execute round-3 Tasks 4–9 and record Phase A as done

**Files:**

- Follow: `docs/superpowers/plans/2026-07-16-architecture-deepening-round-3.md` (Tasks 4–9 — complete step-by-step code lives there; do not re-derive it)
- Modify: that same plan file (checkbox status)

**Interfaces:**

- Consumes: nothing from this plan.
- Produces (used by Tasks 2, 11): `api/runs/launch.py` with `launch(mgr, kind, work, *, singleton_key=None, singleton_conflict="join", meta=None, busy_code=None, busy_message="A run is already active for this item") -> RunOut` and `session_work(engine, fn)`; layout constants in `tenancy/paths.py` (`FACTS_PATH`, `SEARCH_PATH`, `CONNECTORS_PATH`, `REVIEW_PATH`, `REVIEW_DEEP_PATH`, `TELEMETRY_PATH`, `SKILL_ALIASES_PATH`); `JobDetailRow(ShortlistRow)`.

- [ ] **Step 1: Mark Phase A complete in the round-3 plan**

In `docs/superpowers/plans/2026-07-16-architecture-deepening-round-3.md`, check every `- [ ]` box in Tasks 1–3 (change to `- [x]`) and add directly under the `## Global Constraints` section:

```markdown
> **Status 2026-07-19:** Phase A (Tasks 1–3) shipped in `72dc10c`. Phases B–D
> executed via `2026-07-19-architecture-deepening-round-4.md` Task 1.
```

- [ ] **Step 2: Execute round-3 Tasks 4–5 (Phase B — workspace layout)**

Follow the round-3 plan verbatim, with one amendment: where its Task 4 Step 5 and Task 5 Step 4 say `git add -A`, instead stage explicitly:

```bash
# Task 4 commit:
git add src/resume_agent/discovery/connectors/telemetry.py src/resume_agent/taxonomy/skills.py src/resume_agent/services/sources.py tests/tenancy/test_workspace.py
# Task 5 commit:
git add src/resume_agent/tenancy/paths.py src/resume_agent/services/discovery.py src/resume_agent/services/tailoring.py src/resume_agent/services/board.py src/resume_agent/services/cover_letters.py src/resume_agent/services/cover_letter_revision.py src/resume_agent/services/revision.py src/resume_agent/cli.py src/resume_agent/api/routers/match_gap.py src/resume_agent/api/routers/suggestions.py src/resume_agent/tracking/queries.py src/resume_agent/discovery/pipeline.py
```

- [ ] **Step 3: Execute round-3 Tasks 6–8 (Phase C — launch seam)**

Follow the round-3 plan verbatim (its commits already stage explicitly).

- [ ] **Step 4: Execute round-3 Task 9 (Phase D — JobDetailRow) and its final verification checklist**

Follow the round-3 plan verbatim, including its CLAUDE.md documentation step at the end (commit message `docs: record round-3 deepenings in CLAUDE.md`).

- [ ] **Step 5: Check the round-3 boxes and commit the plan-status edits**

Mark Tasks 4–9 checkboxes `- [x]` in the round-3 plan file.

```bash
git add docs/superpowers/plans/2026-07-16-architecture-deepening-round-3.md
git commit -m "docs(plans): round-3 fully executed; record Phase A commit and round-4 handoff"
```

---

# Phase 1 — the Launch seam covers the routers written after round 3

### Task 2: Interview router launches through the shared seam

**Files:**

- Modify: `src/resume_agent/api/routers/interview.py:62-82` (`_submit`)
- Test: `tests/api/test_interview_router.py` (unmodified)

**Interfaces:**

- Consumes: `launch` from Task 1 (`api/runs/launch.py`).
- Produces: identical HTTP behavior — `INTERVIEW_BUSY` 409 with `{"runId": ...}` details, `RunResetConflict` → 409, `RunQuotaError` → 429. `_submit`'s signature (`manager, kind, work, *, singleton`) and its call sites stay unchanged.

- [ ] **Step 1: Replace the `_submit` body**

In `src/resume_agent/api/routers/interview.py`, replace the whole `_submit` function with:

```python
def _submit(
    manager: RunManager, kind: str, work, *, singleton: str
) -> RunOut:
    return launch(
        manager,
        kind,
        work,
        singleton_key=singleton,
        singleton_conflict="raise",
        busy_code="INTERVIEW_BUSY",
        busy_message="An interview turn is already running",
    )
```

Add `from resume_agent.api.runs.launch import launch`. Delete the imports that ruff now flags as unused (`RunSingletonConflict`, `RunResetConflict`, `RunQuotaError`, `record_to_run` — keep any still used elsewhere in the file; trust ruff, not this list).

- [ ] **Step 2: Run the interview router tests, then lint**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_interview_router.py -q`
Expected: PASS unmodified.
Run: `ruff check src/resume_agent/api/routers/interview.py`
Expected: clean.

- [ ] **Step 3: Grep gate — no bare submit tails remain in routers**

Run: `grep -rn "record = mgr.get(run_id)\|record = manager.get(run_id)" src/resume_agent/api/routers`
Expected: no hits outside `suggestions.py` (which rides its own service seam by design — see round-3 Task 8).

- [ ] **Step 4: Commit**

```bash
git add src/resume_agent/api/routers/interview.py
git commit -m "refactor(api): interview router launches through the shared seam"
```

---

# Phase 2 — the Session substrate

### Task 3: `sessions/store.py` — `SessionStore`

**Files:**

- Create: `src/resume_agent/sessions/__init__.py`
- Create: `src/resume_agent/sessions/store.py`
- Test: `tests/test_session_store.py` (new)

**Interfaces:**

- Consumes: `ExtensibleModel` (`models/base.py`), `atomic_write_text` (`progress.py`).
- Produces (used by Tasks 4–5): in `resume_agent.sessions.store`:
  - `valid_session_id(session_id: str) -> bool`
  - `now_iso() -> str` — UTC ISO-8601, seconds precision
  - `class SessionStore(Generic[M])` with `__init__(self, model: type[M], *, label: str)` and methods `lock()` (context manager), `path(root, session_id) -> Path`, `read(path) -> dict`, `write(root, session: dict) -> None`, `list(root, *, include_archived=False) -> list[dict]`, `load(root, session_id) -> dict`, `active(root) -> list[dict]`, `mutate(root, session_id, fn) -> dict`, `archive(root, session_id) -> dict`, `unarchive(root, session_id) -> dict`, `delete(root, session_id) -> None`.
  - Model contract: `model` must define `session_id: str`, `started_at: str`, `status` with values including `"active"`/`"ended"`, and `archived_at: str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_store.py`:

```python
"""The Session substrate: file custody shared by every turn-per-run session kind."""

import pytest

from resume_agent.models.base import ExtensibleModel
from resume_agent.sessions.store import SessionStore, now_iso, valid_session_id


class _Session(ExtensibleModel):
    session_id: str = ""
    started_at: str = ""
    ended_at: str | None = None
    status: str = "active"
    archived_at: str | None = None
    payload: str = ""


@pytest.fixture()
def store() -> SessionStore[_Session]:
    return SessionStore(_Session, label="probe")


def _seed(store, root, session_id, *, status="active", started_at="2026-07-19T00:00:00+00:00"):
    root.mkdir(parents=True, exist_ok=True)
    store.write(
        root,
        _Session(session_id=session_id, started_at=started_at, status=status).model_dump(mode="json"),
    )


def test_valid_session_id_rules():
    assert valid_session_id("abc-123_X")
    assert not valid_session_id("")
    assert not valid_session_id("-leading-dash")
    assert not valid_session_id("has/slash")
    assert not valid_session_id("x" * 65)


def test_path_rejects_invalid_id(store, tmp_path):
    with pytest.raises(ValueError, match="unknown session"):
        store.path(tmp_path, "../escape")


def test_write_load_round_trip_validates(store, tmp_path):
    _seed(store, tmp_path, "s1")
    loaded = store.load(tmp_path, "s1")
    assert loaded["session_id"] == "s1"
    assert (tmp_path / "session-s1.json").exists()


def test_load_unknown_raises(store, tmp_path):
    with pytest.raises(ValueError, match="unknown session"):
        store.load(tmp_path, "nope")


def test_read_invalid_json_names_the_label(store, tmp_path):
    bad = tmp_path / "session-bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid probe session"):
        store.read(bad)


def test_list_sorts_and_filters_archived(store, tmp_path):
    _seed(store, tmp_path, "b", started_at="2026-07-19T02:00:00+00:00")
    _seed(store, tmp_path, "a", started_at="2026-07-19T01:00:00+00:00")
    _seed(store, tmp_path, "c", status="ended", started_at="2026-07-19T00:30:00+00:00")
    store.archive(tmp_path, "c")
    assert [row["session_id"] for row in store.list(tmp_path)] == ["a", "b"]
    assert [row["session_id"] for row in store.list(tmp_path, include_archived=True)] == ["c", "a", "b"]


def test_list_missing_root_is_empty(store, tmp_path):
    assert store.list(tmp_path / "absent") == []


def test_active_filters_status(store, tmp_path):
    _seed(store, tmp_path, "live")
    _seed(store, tmp_path, "done", status="ended")
    assert [row["session_id"] for row in store.active(tmp_path)] == ["live"]


def test_mutate_applies_and_persists(store, tmp_path):
    _seed(store, tmp_path, "s1")
    out = store.mutate(tmp_path, "s1", lambda s: s.__setitem__("payload", "changed"))
    assert out["payload"] == "changed"
    assert store.load(tmp_path, "s1")["payload"] == "changed"


def test_archive_lifecycle_rules(store, tmp_path):
    _seed(store, tmp_path, "s1")
    with pytest.raises(ValueError, match="only ended sessions can be archived"):
        store.archive(tmp_path, "s1")
    store.mutate(tmp_path, "s1", lambda s: s.__setitem__("status", "ended"))
    archived = store.archive(tmp_path, "s1")
    assert archived["archived_at"]
    with pytest.raises(ValueError, match="session already archived"):
        store.archive(tmp_path, "s1")
    restored = store.unarchive(tmp_path, "s1")
    assert restored["archived_at"] is None
    with pytest.raises(ValueError, match="session not archived"):
        store.unarchive(tmp_path, "s1")


def test_delete_removes_file_and_rejects_unknown(store, tmp_path):
    _seed(store, tmp_path, "s1")
    store.delete(tmp_path, "s1")
    assert not (tmp_path / "session-s1.json").exists()
    with pytest.raises(ValueError, match="unknown session"):
        store.delete(tmp_path, "s1")


def test_now_iso_is_utc_seconds():
    stamp = now_iso()
    assert stamp.endswith("+00:00")
    assert "." not in stamp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.sessions'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/sessions/__init__.py`:

```python
"""Durable turn-per-run session infrastructure (ADR-0006)."""
```

Create `src/resume_agent/sessions/store.py`:

```python
"""File custody for durable turn-per-run sessions (ADR-0006).

One SessionStore instance per session kind owns the custody rules the Profile
Coach and Mock Interview stores used to copy: session-id validation, the
``session-<id>.json`` naming scheme, the process-wide mutation lock, validated
atomic read/write, listing with the archived filter and stable sort, active
filtering, delta-under-lock mutation, and the archive/unarchive/delete
lifecycle. Kind-specific behavior — turn schemas, creation invariants, delta
application — stays in the kind's own module.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generic, TypeVar

from resume_agent.models.base import ExtensibleModel
from resume_agent.progress import atomic_write_text

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

M = TypeVar("M", bound=ExtensibleModel)


def valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID.fullmatch(session_id))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStore(Generic[M]):
    """Custody for one session kind's files under a resolved root directory.

    ``model`` must define ``session_id``, ``started_at``, ``status`` (with
    ``"active"``/``"ended"`` among its values), and ``archived_at``.
    """

    def __init__(self, model: type[M], *, label: str) -> None:
        self.model = model
        self.label = label
        self._lock = threading.RLock()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Serialize this kind's session mutations in this process."""
        with self._lock:
            yield

    def path(self, root: Path | str, session_id: str) -> Path:
        if not valid_session_id(session_id):
            raise ValueError(f"unknown session: {session_id}")
        return Path(root) / f"session-{session_id}.json"

    def read(self, path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return self.model.model_validate(raw).model_dump(mode="json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {self.label} session: {path}") from exc

    def write(self, root: Path | str, session: dict) -> None:
        validated = self.model.model_validate(session)
        session_id = validated.model_dump(mode="json")["session_id"]
        if not valid_session_id(session_id):
            raise ValueError("invalid session id")
        atomic_write_text(
            self.path(root, session_id),
            validated.model_dump_json(indent=2) + "\n",
        )

    def list(self, root: Path | str, *, include_archived: bool = False) -> list[dict]:
        base = Path(root)
        if not base.exists():
            return []
        sessions = [self.read(path) for path in base.glob("session-*.json")]
        if not include_archived:
            sessions = [row for row in sessions if not row["archived_at"]]
        return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))

    def load(self, root: Path | str, session_id: str) -> dict:
        path = self.path(root, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        return self.read(path)

    def active(self, root: Path | str) -> list[dict]:
        return [row for row in self.list(root) if row["status"] == "active"]

    def mutate(
        self, root: Path | str, session_id: str, fn: Callable[[dict], None]
    ) -> dict:
        with self.lock():
            session = self.load(root, session_id)
            fn(session)
            self.write(root, session)
            return self.load(root, session_id)

    def archive(self, root: Path | str, session_id: str) -> dict:
        def apply(session: dict) -> None:
            if session["status"] != "ended":
                raise ValueError("only ended sessions can be archived")
            if session["archived_at"]:
                raise ValueError("session already archived")
            session["archived_at"] = now_iso()

        return self.mutate(root, session_id, apply)

    def unarchive(self, root: Path | str, session_id: str) -> dict:
        def apply(session: dict) -> None:
            if not session["archived_at"]:
                raise ValueError("session not archived")
            session["archived_at"] = None

        return self.mutate(root, session_id, apply)

    def delete(self, root: Path | str, session_id: str) -> None:
        with self.lock():
            path = self.path(root, session_id)
            if not path.exists():
                raise ValueError(f"unknown session: {session_id}")
            path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_store.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/sessions tests/test_session_store.py
git add src/resume_agent/sessions tests/test_session_store.py
git commit -m "feat(sessions): SessionStore — the Session substrate for turn-per-run session kinds"
```

---

### Task 4: The coach store becomes a Session-substrate adapter

**Files:**

- Modify: `src/resume_agent/profile/coach_store.py`
- Test: `tests/test_coach_store.py`, `tests/test_profile_coach_service.py`, `tests/api/test_coach_router.py` (all unmodified)

**Interfaces:**

- Consumes: `SessionStore`, `now_iso`, `valid_session_id` from Task 3.
- Produces: every existing public and private name in `coach_store` keeps its exact signature and behavior — `coach_dir`, `coach_lock`, `list_sessions`, `load_session`, `active_session`, `create_session`, `mutate_session`, `apply_turn_delta`, `set_draft_status`, `end_session`, `archive_session`, `unarchive_session`, `delete_session`, `set_impact`, and the models (`CoachTopic`, `CoachDraftNote`, `CoachTurnRecord`, `CoachSession`).

- [ ] **Step 1: Rewrite the custody half as delegates**

In `src/resume_agent/profile/coach_store.py`: keep the module docstring and the four model classes exactly as they are. Replace the imports and everything from `_COACH_LOCK` down to `mutate_session` (inclusive) with:

```python
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.interview import ResearchAction
from resume_agent.sessions.store import SessionStore, now_iso, valid_session_id
```

(then the unchanged model classes, then:)

```python
_STORE: SessionStore[CoachSession] = SessionStore(CoachSession, label="coach")


def coach_dir(profile_dir: Path | str) -> Path:
    return Path(profile_dir) / "coach"


def _valid_session_id(session_id: str) -> bool:
    return valid_session_id(session_id)


def _session_path(profile_dir: Path | str, session_id: str) -> Path:
    return _STORE.path(coach_dir(profile_dir), session_id)


def coach_lock() -> AbstractContextManager[None]:
    """Serialize coach session and approval mutations in this process."""
    return _STORE.lock()


def _now() -> str:
    return now_iso()


def _write(profile_dir: Path | str, session: dict) -> None:
    _STORE.write(coach_dir(profile_dir), session)


def list_sessions(
    profile_dir: Path | str, *, include_archived: bool = False
) -> list[dict]:
    return _STORE.list(coach_dir(profile_dir), include_archived=include_archived)


def load_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.load(coach_dir(profile_dir), session_id)


def active_session(profile_dir: Path | str) -> dict | None:
    return next(iter(_STORE.active(coach_dir(profile_dir))), None)


def mutate_session(
    profile_dir: Path | str,
    session_id: str,
    fn: Callable[[dict], None],
) -> dict:
    return _STORE.mutate(coach_dir(profile_dir), session_id, fn)
```

Keep `create_session`, `apply_turn_delta`, `set_draft_status`, `end_session`, and `set_impact` exactly as they are (they call `coach_lock()`, `_now()`, `_write()`, `mutate_session()` — all still present). Replace `archive_session`, `unarchive_session`, and `delete_session` with:

```python
def archive_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.archive(coach_dir(profile_dir), session_id)


def unarchive_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.unarchive(coach_dir(profile_dir), session_id)


def delete_session(profile_dir: Path | str, session_id: str) -> None:
    """Remove the transcript record without touching saved profile notes."""
    _STORE.delete(coach_dir(profile_dir), session_id)
```

Delete the now-orphaned module-level names: `_COACH_LOCK`, `_SESSION_ID`, `_read`, and the `json`, `re`, `threading`, `contextmanager`, `datetime`, `timezone`, `atomic_write_text` imports (ruff will name any survivors this list gets wrong).

- [ ] **Step 2: Run the coach suites unmodified**

Run: `.venv/Scripts/python.exe -m pytest tests/test_coach_store.py tests/test_profile_coach_service.py tests/api/test_coach_router.py tests/test_cli_profile_coach.py -q`
Expected: PASS with zero test edits. If any test imports a deleted private (`_read`, `_SESSION_ID`), restore that one name as a delegate instead of editing the test.

- [ ] **Step 3: Lint and commit**

```bash
ruff check src/resume_agent/profile/coach_store.py
git add src/resume_agent/profile/coach_store.py
git commit -m "refactor(coach): coach store rides the Session substrate"
```

---

### Task 5: The interview store becomes a Session-substrate adapter

**Files:**

- Modify: `src/resume_agent/interview/store.py`
- Test: `tests/test_interview_store.py`, `tests/test_mock_interview_service.py`, `tests/api/test_interview_router.py` (all unmodified)

**Interfaces:**

- Consumes: `SessionStore`, `now_iso`, `valid_session_id` from Task 3.
- Produces: every existing name keeps its exact signature and behavior — including the job-scoped variation: `list_sessions(interview_dir, job_id=None, *, include_archived=False)`, `active_sessions`, `active_session_for_job`, `active_session`, `delete_sessions_for_job`, and the models (`InterviewStyle`, `InterviewContext`, `PlanItem`, `InterviewTurnRecord`, `QuestionReview`, `InterviewDebrief`, `InterviewSession`, `STYLE_EXTRA_CAP`).

- [ ] **Step 1: Rewrite the custody half as delegates**

In `src/resume_agent/interview/store.py`: keep the module docstring, `STYLE_EXTRA_CAP`, and the seven model classes exactly as they are. Replace the imports and everything from `_INTERVIEW_LOCK` down to `mutate_session` (inclusive) with:

```python
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.sessions.store import SessionStore, now_iso, valid_session_id
```

(then the unchanged model classes, then:)

```python
_STORE: SessionStore[InterviewSession] = SessionStore(InterviewSession, label="interview")


def _valid_session_id(session_id: str) -> bool:
    return valid_session_id(session_id)


def _session_path(interview_dir: Path | str, session_id: str) -> Path:
    return _STORE.path(interview_dir, session_id)


def interview_lock() -> AbstractContextManager[None]:
    """Serialize interview session mutations in this process."""
    return _STORE.lock()


def _now() -> str:
    return now_iso()


def _write(interview_dir: Path | str, session: dict) -> None:
    _STORE.write(interview_dir, session)


def list_sessions(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
) -> list[dict]:
    sessions = _STORE.list(interview_dir, include_archived=include_archived)
    if job_id is not None:
        sessions = [row for row in sessions if row["job_id"] == job_id]
    return sessions


def load_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.load(interview_dir, session_id)


def active_sessions(interview_dir: Path | str) -> list[dict]:
    return _STORE.active(interview_dir)


def active_session_for_job(interview_dir: Path | str, job_id: int) -> dict | None:
    return next(
        (row for row in active_sessions(interview_dir) if row["job_id"] == job_id),
        None,
    )


def active_session(interview_dir: Path | str) -> dict | None:
    """Compatibility projection for callers that only need any active session."""
    return next(iter(active_sessions(interview_dir)), None)


def mutate_session(
    interview_dir: Path | str,
    session_id: str,
    fn: Callable[[dict], None],
) -> dict:
    return _STORE.mutate(interview_dir, session_id, fn)
```

Keep `create_session`, `apply_answer_delta`, and `end_with_debrief` exactly as they are (they call `interview_lock()`, `_now()`, `_write()`, `mutate_session()`). Replace `archive_session`, `unarchive_session`, `delete_session`, and `delete_sessions_for_job` with:

```python
def archive_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.archive(interview_dir, session_id)


def unarchive_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.unarchive(interview_dir, session_id)


def delete_session(interview_dir: Path | str, session_id: str) -> None:
    """Permanently remove a session; deleting an active session abandons it."""
    _STORE.delete(interview_dir, session_id)


def delete_sessions_for_job(interview_dir: Path | str, job_id: int) -> int:
    """Remove all interview session files for a deleted job. Returns count removed."""
    removed = 0
    with _STORE.lock():
        for row in list_sessions(interview_dir, job_id=job_id, include_archived=True):
            _STORE.path(interview_dir, row["session_id"]).unlink(missing_ok=True)
            removed += 1
    return removed
```

Delete the orphans: `_INTERVIEW_LOCK`, `_SESSION_ID`, `_read`, and the `json`, `re`, `threading`, `contextmanager`, `datetime`, `timezone`, `Iterator`, `atomic_write_text` imports (trust ruff).

- [ ] **Step 2: Run the interview suites unmodified**

Run: `.venv/Scripts/python.exe -m pytest tests/test_interview_store.py tests/test_mock_interview_service.py tests/api/test_interview_router.py -q`
Expected: PASS with zero test edits. Same escape hatch as Task 4 for tests importing deleted privates.

- [ ] **Step 3: Duplication grep gate**

Run: `grep -rn "session-\*.json\|A-Za-z0-9\]\[A-Za-z0-9_-\]{0,63}" src/resume_agent --include="*.py" | grep -v sessions/store.py`
Expected: no hits — the glob pattern and id regex have exactly one author.

- [ ] **Step 4: Lint and commit**

```bash
ruff check src/resume_agent/interview/store.py
git add src/resume_agent/interview/store.py
git commit -m "refactor(interview): interview store rides the Session substrate"
```

---

### Task 6: One `TurnRejected`, one `format_with_retry`, one key-check

**Files:**

- Create: `src/resume_agent/sessions/turns.py`
- Modify: `src/resume_agent/profile/coach.py:75` (the `TurnRejected` class), `src/resume_agent/interview/agent.py:67` (same)
- Modify: `src/resume_agent/services/profile_coach.py` (`_format_with_retry`), `src/resume_agent/services/mock_interview.py` (`_format_with_retry`)
- Modify: `src/resume_agent/llm_runner.py` (add `missing_model_keys`), `src/resume_agent/api/routers/coach.py` (`_guard_setup`), `src/resume_agent/api/routers/interview.py` (`_guard_keys`), `src/resume_agent/cli.py` (`profile_coach_cmd` key check)
- Test: `tests/test_session_turns.py` (new); existing coach/interview suites unmodified

**Interfaces:**

- Consumes: `Runner` protocol as used today (`formatter.run(prompt).content`).
- Produces:
  - `resume_agent.sessions.turns.TurnRejected(ValueError)` — the single class; `profile.coach.TurnRejected` and `interview.agent.TurnRejected` become re-exports of it, so every existing `raise`/`except`/test import keeps working and the classes are now identical.
  - `resume_agent.sessions.turns.format_with_retry(formatter, notes, schema, validate, *, label: str)` — one formatter pass, validate, one retry on `TurnRejected`.
  - `resume_agent.llm_runner.missing_model_keys(settings) -> list[str]` — `"tier (model)"` labels for the configured mid/cheap models whose provider key is absent.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_turns.py`:

```python
"""Shared turn formatting: one retry on rejection, type-checked output."""

import pytest

from resume_agent.sessions.turns import TurnRejected, format_with_retry


class _Out:
    def __init__(self, value: str):
        self.value = value


class _Formatter:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)

        class _Resp:
            content = self._outputs.pop(0)

        return _Resp()


def test_happy_path_formats_once():
    formatter = _Formatter([_Out("ok")])
    result = format_with_retry(
        formatter, "raw notes", _Out, lambda out: out, label="COACH NOTES"
    )
    assert result.value == "ok"
    assert formatter.prompts == ["COACH NOTES (UNTRUSTED):\nraw notes"]


def test_wrong_type_raises_typeerror():
    formatter = _Formatter(["not the schema"])
    with pytest.raises(TypeError, match="Expected _Out"):
        format_with_retry(formatter, "n", _Out, lambda out: out, label="X")


def test_rejection_retries_once_with_feedback():
    formatter = _Formatter([_Out("bad"), _Out("good")])

    def validate(out):
        if out.value == "bad":
            raise TurnRejected("quote missing")
        return out

    result = format_with_retry(formatter, "n", _Out, validate, label="INTERVIEWER NOTES")
    assert result.value == "good"
    assert "PREVIOUS OUTPUT REJECTED: quote missing" in formatter.prompts[1]


def test_second_rejection_propagates():
    formatter = _Formatter([_Out("bad"), _Out("bad")])

    def validate(out):
        raise TurnRejected("still wrong")

    with pytest.raises(TurnRejected):
        format_with_retry(formatter, "n", _Out, validate, label="X")


def test_turn_rejected_is_one_class_everywhere():
    from resume_agent.interview.agent import TurnRejected as interview_cls
    from resume_agent.profile.coach import TurnRejected as coach_cls

    assert coach_cls is TurnRejected
    assert interview_cls is TurnRejected


def test_missing_model_keys_labels(monkeypatch):
    from resume_agent import llm_runner
    from resume_agent.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model: None)
    labels = llm_runner.missing_model_keys(settings)
    assert labels == [
        f"mid ({settings.mid_model})",
        f"cheap ({settings.cheap_model})",
    ]
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model: "key")
    assert llm_runner.missing_model_keys(settings) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_turns.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.sessions.turns'`.

- [ ] **Step 3: Implement `sessions/turns.py`**

```python
"""Structured-output turn helpers shared by the coach and interviewer stacks."""

from __future__ import annotations


class TurnRejected(ValueError):
    """A formatted turn failed validation against the session's rules."""


def format_with_retry(formatter, notes: object, schema, validate, *, label: str):
    """Format untrusted notes into ``schema`` and validate, retrying once.

    The retry feeds the rejection reason back to the formatter; a second
    rejection propagates. Non-``schema`` output is a TypeError immediately.
    """
    prompt = f"{label} (UNTRUSTED):\n{notes}"
    formatted = formatter.run(prompt).content
    if not isinstance(formatted, schema):
        raise TypeError(f"Expected {schema.__name__}, got {type(formatted).__name__}")
    try:
        return validate(formatted)
    except TurnRejected as first:
        retry = formatter.run(f"{prompt}\n\nPREVIOUS OUTPUT REJECTED: {first}").content
        if not isinstance(retry, schema):
            raise TypeError(
                f"Expected {schema.__name__}, got {type(retry).__name__}"
            ) from first
        return validate(retry)
```

- [ ] **Step 4: Re-point the twins**

1. `src/resume_agent/profile/coach.py` — delete the `class TurnRejected(ValueError): ...` block (line ~75) and add to the module's imports: `from resume_agent.sessions.turns import TurnRejected`. Keep the name exported (add a `# noqa: F401` only if ruff flags it AND nothing in the module references it — the module raises it, so it will be referenced).
2. `src/resume_agent/interview/agent.py` — same replacement for its class at line ~67.
3. `src/resume_agent/services/profile_coach.py` — delete `_format_with_retry`; add `from resume_agent.sessions.turns import format_with_retry`; change its two call sites from `_format_with_retry(formatter, notes, schema, validate)` to `format_with_retry(formatter, notes, schema, validate, label="COACH NOTES")`.
4. `src/resume_agent/services/mock_interview.py` — same, with `label="INTERVIEWER NOTES"`.
5. `src/resume_agent/llm_runner.py` — append:

```python
def missing_model_keys(settings) -> list[str]:
    """Configured mid/cheap tier models whose provider key is absent.

    Returns ``"tier (model)"`` labels for surfaces that gate LLM features on
    key presence (coach router, interview router, coach CLI).
    """
    configured = (("mid", settings.mid_model), ("cheap", settings.cheap_model))
    return [
        f"{tier} ({model})" for tier, model in configured if not resolve_api_key(model)
    ]
```

1. `src/resume_agent/api/routers/coach.py` `_guard_setup` — replace the four `configured =` / `missing =` lines with `missing = missing_model_keys(settings)` (import `missing_model_keys` from `resume_agent.llm_runner`, replacing the `resolve_api_key` import if it becomes unused).
2. `src/resume_agent/api/routers/interview.py` `_guard_keys` — same replacement.
3. `src/resume_agent/cli.py` `profile_coach_cmd` — same replacement for its `configured` / `missing` block.

- [ ] **Step 5: Run the new and affected suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_turns.py tests/test_profile_coach.py tests/test_profile_coach_service.py tests/test_interview_agent.py tests/test_mock_interview_service.py tests/api/test_coach_router.py tests/api/test_interview_router.py tests/test_cli_profile_coach.py -q`
Expected: PASS with zero test edits.

- [ ] **Step 6: Grep gates**

Run: `grep -rn "class TurnRejected" src/resume_agent --include="*.py"`
Expected: only `sessions/turns.py`.
Run: `grep -rn "_format_with_retry" src/resume_agent --include="*.py"`
Expected: no hits.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/resume_agent tests/test_session_turns.py
git add src/resume_agent/sessions/turns.py src/resume_agent/profile/coach.py src/resume_agent/interview/agent.py src/resume_agent/services/profile_coach.py src/resume_agent/services/mock_interview.py src/resume_agent/llm_runner.py src/resume_agent/api/routers/coach.py src/resume_agent/api/routers/interview.py src/resume_agent/cli.py tests/test_session_turns.py
git commit -m "refactor(sessions): one TurnRejected, one format_with_retry, one missing-keys check"
```

---

# Phase 3 — the board filter query gets one author

### Task 7: `board_filter_query` dependency

**Files:**

- Modify: `src/resume_agent/api/routers/boards.py`
- Modify (regenerate): `contracts/openapi.json`, `contracts/ts/api.ts`
- Test: `tests/api/test_boards.py` (unmodified), `tests/api/test_openapi_contract.py`

**Interfaces:**

- Consumes: `board.BoardFilter` (frozen dataclass), `_csv` (same module).
- Produces: `board_filter_query(default_sort: str)` — a dependency factory returning a FastAPI dependency that yields a `board.BoardFilter` from the 19 shared query params (wire aliases per Background fact 6). Triage keeps its own leading `archived` param and derives the final filter with `dataclasses.replace`.

**Contract note:** this is the one task allowed to regenerate `contracts/`. The diff must be order-only — the jq gate in Step 4 proves no parameter was added, removed, renamed, or retyped.

- [ ] **Step 1: Add the dependency factory and rewrite the three endpoints**

In `src/resume_agent/api/routers/boards.py`, delete `_filter_from_query` and add in its place:

```python
def board_filter_query(default_sort: str):
    """The boards' shared filter surface, declared once.

    A factory because the wire default for ``sortBy`` is per-board (shortlist
    and triage rank by fit, pipeline by stage) while the parameter set is not.
    """

    def dependency(
        q: str | None = None,
        source: str | None = None,
        status: str | None = None,
        remote: str | None = None,
        sponsorship: str | None = None,
        seniority: str | None = None,
        employment_type: str | None = Query(None, alias="employmentType"),
        industry: str | None = None,
        country: str | None = None,
        region: str | None = None,
        city: str | None = None,
        company_size: str | None = Query(None, alias="companySize"),
        skills: str | None = None,
        min_fit: int | None = Query(None, alias="minFit"),
        max_fit: int | None = Query(None, alias="maxFit"),
        min_salary: int | None = Query(None, alias="minSalary"),
        stale_days: int | None = Query(None, alias="staleDays"),
        stale_min_days: int | None = Query(None, alias="staleMinDays"),
        sort: str = Query(default_sort, alias="sortBy"),
    ) -> board.BoardFilter:
        return board.BoardFilter(
            q=q,
            source=_csv(source),
            status=_csv(status),
            remote=_csv(remote),
            sponsorship=_csv(sponsorship),
            seniority=_csv(seniority),
            employment_type=_csv(employment_type),
            industry=_csv(industry),
            country=_csv(country),
            region=_csv(region),
            city=_csv(city),
            company_size=_csv(company_size),
            skills=_csv(skills),
            min_fit=min_fit,
            max_fit=max_fit,
            min_salary=min_salary,
            stale_days=stale_days,
            stale_min_days=stale_min_days,
            sort=sort,
        )

    return dependency
```

Replace the three endpoints (decorators unchanged):

```python
@router.get("/shortlist", response_model=BoardPage[ShortlistItem])
def get_shortlist(
    board_filter: board.BoardFilter = Depends(board_filter_query("fit")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_board(
        session, "shortlist", board_filter=board_filter, page=page, page_size=page_size
    )
    return to_board_page(result.page, ShortlistItem, result.facets)


@router.get("/pipeline", response_model=BoardPage[PipelineItem])
def get_pipeline(
    board_filter: board.BoardFilter = Depends(board_filter_query("stage")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_board(
        session, "pipeline", board_filter=board_filter, page=page, page_size=page_size
    )
    return to_board_page(result.page, PipelineItem, result.facets)


@router.get("/triage", response_model=BoardPage[TriageItem])
def get_triage(
    archived: bool = False,
    board_filter: board.BoardFilter = Depends(board_filter_query("fit")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    board_filter = replace(board_filter, archived=archived)
    result = board.list_board(
        session, "triage", board_filter=board_filter, page=page, page_size=page_size
    )
    return to_board_page(result.page, TriageItem, result.facets)
```

Add `from dataclasses import replace` to the module imports.

- [ ] **Step 2: Run the boards behavior tests unmodified**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -q`
Expected: PASS with zero test edits.

- [ ] **Step 3: Regenerate the contracts**

Run: `.venv/Scripts/python.exe scripts/export_openapi.py && bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q`
Expected: PASS (the committed contract now matches the regenerated one).

- [ ] **Step 4: Prove the contract diff is order-only**

Run (Bash tool):

```bash
for ep in shortlist pipeline triage; do
  git show HEAD:contracts/openapi.json | jq -S "[.paths[] | objects | .get? | select(. != null) | select(.operationId? // \"\" | test(\"$ep\"; \"i\")) | .parameters[]? | {name, required, in, schema}] | sort_by(.name)" > /tmp/before-$ep.json
  jq -S "[.paths[] | objects | .get? | select(. != null) | select(.operationId? // \"\" | test(\"$ep\"; \"i\")) | .parameters[]? | {name, required, in, schema}] | sort_by(.name)" contracts/openapi.json > /tmp/after-$ep.json
  diff /tmp/before-$ep.json /tmp/after-$ep.json && echo "$ep: identical param sets"
done
```

Expected: `identical param sets` × 3. If any diff shows an added/removed/renamed parameter or a changed schema/default, STOP and fix the dependency until the sets match — only ordering inside the `parameters` array may differ.

- [ ] **Step 5: Full suite, web typecheck, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check src/resume_agent/api/routers/boards.py`
Run: `npm run test:run --prefix web` (the regenerated `api.ts` must still typecheck the web suite)
Expected: PASS / clean / PASS.

```bash
git add src/resume_agent/api/routers/boards.py contracts/openapi.json contracts/ts/api.ts
git commit -m "refactor(api): board filter query surface has one author (order-only contract regen)"
```

---

# Phase 4 — measure the board read path, then fix only what the numbers indict

### Task 8: `scripts/bench_board.py` + recorded baseline

**Files:**

- Create: `scripts/bench_board.py`
- Create: `docs/notes/board-read-baseline.md` (numbers recorded by hand from the run)

**Interfaces:**

- Consumes: `make_engine`, `init_db` (`db.py`), `list_board`, `BoardFilter` (`services/board.py`), `Job` (`tracking/tables.py`).
- Produces: a repeatable timing table; the decision input for Task 9's threshold gate.

- [ ] **Step 1: Write the benchmark**

Create `scripts/bench_board.py`:

```python
"""Benchmark the board read path against synthetic workspaces.

Usage:
    .venv/Scripts/python.exe scripts/bench_board.py
    .venv/Scripts/python.exe scripts/bench_board.py --rows 1000 5000 10000 --repeat 20

Seeds N shortlisted jobs (realistic criteria_json, a ~4.4 KB jd_text) into a
temp file-backed SQLite DB (WAL, same pragmas as production via make_engine),
then times services.board.list_board for the shortlist and triage boards.
Facts/aliases are absent on purpose: their loaders are already mtime-cached,
so this isolates query + row-build + filter/rank cost.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.board import list_board
from resume_agent.tracking.tables import Job


def seed(session: Session, n: int) -> None:
    jd = "Responsibilities include shipping software. " * 100  # ~4.4 KB
    for i in range(n):
        session.add(
            Job(
                source="greenhouse",
                url=f"https://example.com/jobs/{i}",
                company=f"Company {i % 199}",
                title=f"Software Engineer {i % 37}",
                location="Remote, US",
                jd_text=jd,
                status="shortlisted" if i % 2 == 0 else "raw",
                fit_score=i % 100,
                dedup_key=f"company {i % 199}|software engineer {i % 37}::{i}",
                criteria_json={
                    "hard_skills": ["python", "sql", "aws", "docker", "react"],
                    "soft_skills": ["communication", "ownership"],
                    "salary_range": {"min": 120000, "max": 180000},
                    "location_parts": {"country": "US", "region": "CA", "city": "SF"},
                },
            )
        )
        if i % 500 == 499:
            session.commit()
    session.commit()


def bench(engine, board: str, repeat: int) -> tuple[float, float]:
    times: list[float] = []
    with Session(engine) as session:
        for _ in range(repeat):
            start = time.perf_counter()
            list_board(session, board)  # type: ignore[arg-type]
            times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), sorted(times)[max(0, int(len(times) * 0.95) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, nargs="+", default=[1000, 5000, 10000])
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()

    print(f"{'rows':>7} {'board':>10} {'p50 ms':>8} {'p95 ms':>8}")
    for n in args.rows:
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(f"sqlite:///{(Path(tmp) / 'bench.db').as_posix()}")
            init_db(engine)
            with Session(engine) as session:
                seed(session, n)
            for board in ("shortlist", "triage"):
                p50, p95 = bench(engine, board, args.repeat)
                print(f"{n:>7} {board:>10} {p50:>8.1f} {p95:>8.1f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and record the baseline**

Run: `.venv/Scripts/python.exe scripts/bench_board.py`
Expected: a table printing without error (absolute numbers are machine-dependent).

Create `docs/notes/board-read-baseline.md` with the actual printed table plus:

```markdown
# Board read-path baseline — 2026-07-19

Machine: <fill in from the run environment>
Command: `.venv/Scripts/python.exe scripts/bench_board.py`

<paste the printed table>

**Threshold for Task 9 (deferred jd_text):** proceed only if shortlist or
triage p95 at 5,000 rows exceeds 100 ms. Otherwise skip Task 9 Steps 2-4 and
record "within budget" here.

**Post-fix table (fill in after Task 9, or write "skipped — within budget"):**
```

- [ ] **Step 3: Commit**

```bash
git add scripts/bench_board.py docs/notes/board-read-baseline.md
git commit -m "perf(board): benchmark harness + recorded read-path baseline"
```

---

### Task 9: Defer `jd_text` on list queries that never ship it (threshold-gated)

**Gate:** execute Steps 2–4 only if Task 8 recorded shortlist or triage p95 > 100 ms at 5,000 rows. Step 1 (the guard test) is unconditional — it pins the "list rows don't touch jd_text" invariant either way.

**Files:**

- Modify: `src/resume_agent/tracking/queries.py` (`shortlist_rows`, `triage_rows`, `archived_rows` — NOT `pipeline_rows`: `PipelineItem` ships `jdText` on the wire and must keep loading it)
- Test: `tests/test_tracking_queries.py` (append)

**Interfaces:**

- Consumes: `sqlalchemy.orm.defer`.
- Produces: identical row objects (ShortlistRow/TriageRow carry no jd_text field); one fewer hydrated large column per row.

- [ ] **Step 1: Write the guard test (unconditional)**

Append to `tests/test_tracking_queries.py`:

```python
def test_shortlist_and_triage_rows_never_touch_jd_text():
    """Pins the invariant that lets jd_text stay deferred on list queries.

    ShortlistItem and TriageItem never ship jd_text on the wire; if a future
    row field starts reading job.jd_text, the defer() in these queries would
    silently issue one lazy SELECT per row (N+1). Fail here first.
    """
    import inspect

    import resume_agent.tracking.queries as queries_module

    for fn in (queries_module._shortlist_row, queries_module._triage_row):
        assert "jd_text" not in inspect.getsource(fn), (
            f"{fn.__name__} reads jd_text; remove defer() from its query "
            "before shipping this change"
        )
```

(A source-inspection test needs no fixture, no engine, and no rows — it fails the moment someone wires `jd_text` into a list-row builder, in the same file the defer lives in.)

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -q`
Expected: PASS (the invariant already holds today).

- [ ] **Step 2 (gated): Apply the deferral**

In `src/resume_agent/tracking/queries.py`, add `from sqlalchemy.orm import defer` and change the three queries:

`shortlist_rows`:

```python
    jobs = session.exec(
        select(Job)
        .options(defer(cast(Any, Job.jd_text)))
        .where(Job.status == JobStatus.shortlisted.value, archived_col.is_(None))
        .order_by(fit_score_col.desc().nullslast())
    ).all()
```

`triage_rows` and `archived_rows`: add the same `.options(defer(cast(Any, Job.jd_text)))` line immediately after `select(Job)` in each.

Leave `pipeline_rows` and `job_detail_row` untouched (both need `jd_text`).

- [ ] **Step 3 (gated): Run the tracking + boards suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py tests/api/test_boards.py -q`
Expected: PASS unmodified.

- [ ] **Step 4 (gated): Re-run the benchmark and record the delta**

Run: `.venv/Scripts/python.exe scripts/bench_board.py`
Paste the new table into the "Post-fix table" section of `docs/notes/board-read-baseline.md`. The p95 at 5,000 rows must improve; if it does not, revert Step 2 (`git checkout -- src/resume_agent/tracking/queries.py`) and record "no measurable win — deferral reverted" instead.

- [ ] **Step 5: Commit (whichever branch of the gate ran)**

```bash
git add src/resume_agent/tracking/queries.py tests/test_tracking_queries.py docs/notes/board-read-baseline.md
git commit -m "perf(board): defer jd_text on shortlist/triage list queries (measured)"
# or, if the gate said skip:
git add tests/test_tracking_queries.py docs/notes/board-read-baseline.md
git commit -m "perf(board): pin jd-text-free list rows; baseline within budget, deferral skipped"
```

---

# Phase 5 — documentation refresh

### Task 10: ADR index

**Files:**

- Create: `docs/adr/README.md`

- [ ] **Step 1: Write the index**

```markdown
# Architecture Decision Records

Decisions the architecture reviews must not re-litigate. Newest last.

| ADR                                                                   | Decision                             | One-line summary                                                                                                                                                  |
| --------------------------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [0001](0001-dedup-key-plus-location-guard.md)                         | Dedup key + location guard           | `compute_dedup_key` stays `company\|normalized_title`; `find_existing` adds a location-compatibility guard so multi-location same-title reqs become sibling rows. |
| [0002](0002-single-service-sqlite-volume-whole-root-custody.md)       | Single service, whole-root custody   | One Railway service owns one SQLite volume; export/import moves the whole Data root, never a slice.                                                               |
| [0003](0003-contextvar-tenancy-propagation.md)                        | ContextVar tenancy propagation       | The active `UserContext` rides a contextvar set at the API dependency, `RunManager.submit`, and the CLI callback; no second propagation mechanism.                |
| [0004](0004-company-rename-recomputes-dedup-key-skip-on-collision.md) | Company rename recomputes dedup key  | Renames recompute `dedup_key`; collisions skip rather than merge.                                                                                                 |
| [0005](0005-read-only-agent-tools-deterministic-writes.md)            | Read-only agent tools                | Every tool inside an agent loop is read-only; writes happen after the loop through deterministic services behind user approval.                                   |
| [0006](0006-turn-per-run-conversational-sessions.md)                  | Turn-per-run conversational sessions | Durable session JSON per conversation; one user message → one run → one typed turn. The Session substrate (`sessions/store.py`) is its custody implementation.    |
```

- [ ] **Step 2: Commit**

```bash
git add docs/adr/README.md
git commit -m "docs(adr): index the decision records"
```

---

### Task 11: CONTEXT.md terms + CLAUDE.md sync

**Files:**

- Modify: `CONTEXT.md` (two new terms)
- Modify: `CLAUDE.md` (hot paths + design notes)

- [ ] **Step 1: Add the two terms to CONTEXT.md**

Insert a new section between "## Runs & skill classification" and "## Profile corpus":

```markdown
## Sessions

**Session substrate**:
The deep custody seam for every turn-per-run session kind (ADR 0006) —
`sessions/store.py`. One `SessionStore` per kind owns id validation, the
`session-<id>.json` naming, the process-wide mutation lock, validated atomic
read/write, listing/active filtering, delta-under-lock mutation, and the
archive/unarchive/delete lifecycle. The Coach session store and the Mock
Interview store are its two adapters; kind-specific turn schemas and creation
invariants stay in the kind's module.
_Avoid_: session manager (it manages files, not conversations), base store
(it is the seam, not a superclass grab-bag)

**Launch seam**:
`api/runs/launch.py` — the single tail every router uses to start a background
run: submit through RunManager (UserContext-derived), map the three
launch-time errors onto the API envelope (singleton → 409, reset → 409,
quota → 429), return the created record as `RunOut`. `session_work` rides it
and owns the one threading invariant: the worker opens its OWN DB session.
_Avoid_: submit helper (seven routers had one of those; this is the seam),
run starter
```

- [ ] **Step 2: Sync CLAUDE.md**

(Round-3's final step already added the launch-seam and layout-constant lines during Task 1; this step adds only what round 4 created.)

1. In the "Hot paths" table, add after the `services/profile_coach.py` row:

```markdown
| `src/resume_agent/sessions/store.py` | Session substrate: file custody every turn-per-run session kind rides (ADR 0006) |
```

1. In "Known design notes", find the bullet beginning "**Mock interviews are practice artifacts, not progress.**" and append to it:

```markdown
Both the coach and interview stores are adapters of the Session substrate
(`sessions/store.py`); custody bugs are fixed there, once. `TurnRejected` and
`format_with_retry` live in `sessions/turns.py`, shared by both stacks.
```

1. In the API-layer section, append one bullet:

```markdown
- **Board filters are declared once.** `board_filter_query(default_sort)` in
  `api/routers/boards.py` owns the shared query surface for
  shortlist/pipeline/triage; a new board filter is added in exactly one place.
  Triage's extra `archived` flag stays endpoint-local via `dataclasses.replace`.
```

- [ ] **Step 3: Commit**

```bash
git add CONTEXT.md CLAUDE.md
git commit -m "docs: Session substrate + Launch seam vocabulary; CLAUDE.md synced to round 4"
```

---

## Final verification (after all tasks)

- [ ] Full suite: `.venv/Scripts/python.exe -m pytest -q` → PASS
- [ ] Lint: `ruff check` → clean
- [ ] Web unit suite: `npm run test:run --prefix web` → PASS
- [ ] Web build: `npm run build --prefix web` → PASS
- [ ] Contract state: `git status contracts/` → clean (Task 7's regeneration committed; nothing pending)
- [ ] Duplication grep gates:
  - `grep -rn "class TurnRejected" src/resume_agent --include="*.py"` → only `sessions/turns.py`
  - `grep -rn "session-\*.json" src/resume_agent --include="*.py"` → only `sessions/store.py`
  - `grep -rn "data/profile/facts.json" src/resume_agent --include="*.py"` → only `tenancy/paths.py` (+ user-facing help text per round-3 Task 5)
  - `grep -rn "record = mgr.get(run_id)\|record = manager.get(run_id)" src/resume_agent/api/routers` → only `suggestions.py`
- [ ] The unrelated Gmail working-tree changes are still uncommitted and untouched: `git status` shows exactly the same four Gmail-related entries as before execution.
- [ ] `docs/notes/board-read-baseline.md` has both a baseline table and a filled-in post-fix section (numbers or an explicit "skipped — within budget").

---

## Explicitly out of scope (decided during the 2026-07-19 review)

- **CLI decomposition:** `profile_coach_cmd` and peers are mostly genuine terminal
  interaction (prompt loops, echo reporters), not orchestration; the only real
  duplication found (the model-key guard) is extracted in Task 6. A broader CLI
  audit earns its keep only if a service change forces a third copy of something.
- **Pipeline `jd_text` payload:** `PipelineItem` ships the full JD for every row
  by wire contract; slimming it is a contract change, not a refactor, and belongs
  to a product decision.
- **`list_source_views` and the sources router's `_config_paths` threading:**
  per round-3's Background facts 5–6 — genuine variation and a separate seam.
- **`suggestions.py` launch tail:** rides `submit_suggestion_run`'s service seam
  by design (round-3 Task 8).
