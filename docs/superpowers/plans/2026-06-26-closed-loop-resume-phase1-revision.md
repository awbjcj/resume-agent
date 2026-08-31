# Closed-Loop Resume — Phase 1: Prompt-Driven Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user type a free-text instruction to revise a tailored resume or cover letter and get a new, fact-locked version persisted with full lineage, then choose which version their application uses.

**Architecture:** A new dedicated revision agent (separate prompt from the critique-driven reviser) consumes the current `ResumeContent`/`CoverLetterContent` plus the user instruction, emits a new content object, which is gated by the existing provenance fact-check and persisted as a new `ResumeVersion`/`CoverLetter` row carrying `origin="revision"`, the `instruction`, and a `parent` pointer. New synchronous API endpoints expose this; the `JobModal` Versions tab gains a revise box and a "Use for application" control, and a new Cover Letters tab mirrors it.

**Tech Stack:** Python 3 / FastAPI / SQLModel / SQLite, agno LLM agents, Typst rendering; React + Vite + TanStack Query + shadcn/ui frontend; pytest (offline, agents faked) + vitest.

## Global Constraints

- **Fact-lock is a hard gate.** Every resume bullet / cover-letter paragraph must keep a `provenance` id pointing at a real `ProfileFacts` fact. A revision that fails the provenance gate is **persisted and flagged `fact_check_passed=false`**, never silently dropped.
- **Tests are offline.** No API key, no network. All LLM agents are faked/monkeypatched; assert against fixture content. Run: `.venv/Scripts/python.exe -m pytest`.
- **Wire format is camelCase.** API schemas subclass `CamelModel` (`alias_generator=to_camel`, `from_attributes=True`); Python stays snake_case.
- **Contracts are generated.** After any endpoint/schema change, regenerate `contracts/openapi.json` + `contracts/ts/api.ts` via `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is a drift gate.
- **Migrations are idempotent SQLite helpers.** New columns on existing tables use `ensure_*_column(engine)` helpers (PRAGMA check + `ALTER TABLE`) registered in `init_db` (`src/resume_tailor_harness/db.py`); new tables come from `SQLModel.metadata.create_all`.
- **Revision is synchronous.** These endpoints return `200` with the new version directly (a deliberate exception to "long ops = Run + SSE", which is reserved for multi-job batches).
- **Lint clean:** `ruff check` must pass.

---

### Task 1: `ResumeVersion` revision columns + migration

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py:61-73` (`ResumeVersion`)
- Modify: `src/resume_tailor_harness/tracking/migrate.py` (add helper at end)
- Modify: `src/resume_tailor_harness/db.py:8-14,51-57` (import + call helper)
- Test: `tests/test_tracking_migrate.py` (create if absent)

**Interfaces:**

- Produces: `ResumeVersion.origin: str` (default `"tailor"`), `ResumeVersion.instruction: str | None`, `ResumeVersion.parent_version_id: int | None`; `ensure_resume_version_revision_columns(engine: Engine) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_migrate.py
from sqlalchemy import text
from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.repository import save_resume_version
from resume_tailor_harness.tracking.tables import Job, ResumeVersion
from resume_tailor_harness.tracking.repository import save_job


def test_resume_version_has_revision_columns():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        v = save_resume_version(
            s,
            ResumeVersion(
                job_id=job.id, round=1, content_json={},
                origin="revision", instruction="be concise", parent_version_id=None,
            ),
        )
        assert v.origin == "revision"
        assert v.instruction == "be concise"


def test_ensure_resume_version_revision_columns_backfills_origin():
    engine = make_engine("sqlite://")
    # Simulate a legacy table without the columns, then migrate.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE resume_versions (id INTEGER PRIMARY KEY, job_id INTEGER, "
            "round INTEGER, content_json JSON, pdf_path VARCHAR, review_score INTEGER, "
            "fact_check_passed BOOLEAN, critique_json JSON, schema_version INTEGER, created_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 0)"))
    from resume_tailor_harness.tracking.migrate import ensure_resume_version_revision_columns
    ensure_resume_version_revision_columns(engine)
    with engine.begin() as conn:
        origin = conn.execute(text("SELECT origin FROM resume_versions WHERE id = 1")).scalar()
    assert origin == "tailor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py -v`
Expected: FAIL (`TypeError: 'origin' is an invalid keyword argument` / `ImportError`).

- [ ] **Step 3: Add the model columns**

In `src/resume_tailor_harness/tracking/tables.py`, inside `class ResumeVersion`, after `critique_json` (line ~71):

```python
    origin: str = Field(default="tailor", index=True)  # "tailor" | "revision"
    instruction: str | None = None
    parent_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
```

- [ ] **Step 4: Add the migration helper**

Append to `src/resume_tailor_harness/tracking/migrate.py`:

```python
def ensure_resume_version_revision_columns(engine: Engine) -> None:
    """Idempotently add origin/instruction/parent_version_id to resume_versions."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))]
        if not cols:
            return
        if "origin" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN origin VARCHAR"))
            conn.execute(text("UPDATE resume_versions SET origin = 'tailor' WHERE origin IS NULL"))
        if "instruction" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN instruction VARCHAR"))
        if "parent_version_id" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN parent_version_id INTEGER"))
```

- [ ] **Step 5: Register it in `init_db`**

In `src/resume_tailor_harness/db.py`, add to the import block (line 8-14) and call it in `init_db` after `ensure_content_fingerprint_column(engine)`:

```python
from resume_tailor_harness.tracking.migrate import (
    ensure_archived_at_column,
    ensure_content_fingerprint_column,
    ensure_dedup_key_column,
    ensure_posted_at_column,
    ensure_reject_category_column,
    ensure_resume_version_revision_columns,
)
```

```python
    ensure_resume_version_revision_columns(engine)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py src/resume_tailor_harness/tracking/migrate.py src/resume_tailor_harness/db.py tests/test_tracking_migrate.py
git commit -m "feat: add revision lineage columns to resume_versions"
```

---

### Task 2: `CoverLetter` revision columns + `Application.cover_letter_id` migration

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py:90-100` (`CoverLetter`), `:76-87` (`Application`)
- Modify: `src/resume_tailor_harness/tracking/migrate.py`
- Modify: `src/resume_tailor_harness/db.py` (call new helpers)
- Test: `tests/test_tracking_migrate.py`

**Interfaces:**

- Produces: `CoverLetter.origin: str` (default `"draft"`), `CoverLetter.instruction: str | None`, `CoverLetter.parent_id: int | None`; `Application.cover_letter_id: int | None`; `ensure_cover_letter_revision_columns(engine)`, `ensure_application_cover_letter_id_column(engine)`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tracking_migrate.py
def test_cover_letter_and_application_revision_columns():
    engine = make_engine("sqlite://")
    init_db(engine)
    from resume_tailor_harness.tracking.tables import Application, CoverLetter
    from resume_tailor_harness.tracking.repository import save_cover_letter, save_application
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        cl = save_cover_letter(
            s, CoverLetter(job_id=job.id, content_json={}, origin="revision",
                           instruction="warmer tone", parent_id=None),
        )
        app = save_application(s, Application(job_id=job.id, cover_letter_id=cl.id))
        assert cl.origin == "revision"
        assert app.cover_letter_id == cl.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py::test_cover_letter_and_application_revision_columns -v`
Expected: FAIL (`TypeError: invalid keyword argument 'origin'`).

- [ ] **Step 3: Add the model columns**

In `class CoverLetter`, after `fact_check_passed` (line ~98):

```python
    origin: str = Field(default="draft", index=True)  # "draft" | "revision"
    instruction: str | None = None
    parent_id: int | None = Field(default=None, foreign_key="cover_letters.id")
```

In `class Application`, after `resume_version_id` (line ~81):

```python
    cover_letter_id: int | None = Field(default=None, foreign_key="cover_letters.id")
```

- [ ] **Step 4: Add the migration helpers**

Append to `migrate.py`:

```python
def ensure_cover_letter_revision_columns(engine: Engine) -> None:
    """Idempotently add origin/instruction/parent_id to cover_letters."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(cover_letters)"))]
        if not cols:
            return
        if "origin" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN origin VARCHAR"))
            conn.execute(text("UPDATE cover_letters SET origin = 'draft' WHERE origin IS NULL"))
        if "instruction" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN instruction VARCHAR"))
        if "parent_id" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN parent_id INTEGER"))


def ensure_application_cover_letter_id_column(engine: Engine) -> None:
    """Idempotently add applications.cover_letter_id."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))]
        if not cols:
            return
        if "cover_letter_id" not in cols:
            conn.execute(text("ALTER TABLE applications ADD COLUMN cover_letter_id INTEGER"))
```

- [ ] **Step 5: Register both in `init_db`**

Add the two names to the `migrate` import in `db.py` and call them in `init_db`:

```python
    ensure_cover_letter_revision_columns(engine)
    ensure_application_cover_letter_id_column(engine)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py src/resume_tailor_harness/tracking/migrate.py src/resume_tailor_harness/db.py tests/test_tracking_migrate.py
git commit -m "feat: add revision columns to cover_letters and application.cover_letter_id"
```

---

### Task 3: Resume revision agent + composer

**Files:**

- Modify: `src/resume_tailor_harness/tailor/agents.py` (add `build_revision_agent`)
- Create: `src/resume_tailor_harness/tailor/revision.py` (composer + run helper)
- Test: `tests/test_tailor_revision.py`

**Interfaces:**

- Consumes: `Runner` (`agent.run(text).content -> ResumeContent`), `ResumeContent`, `ProfileFacts`.
- Produces: `build_revision_agent(model_id=None, style_guide=None) -> Runner`; `compose_user_revision_input(content: ResumeContent, instruction: str, profile_facts: ProfileFacts) -> str`; `apply_revision(input_text: str, agent: Runner) -> ResumeContent`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_revision.py
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.tailor.revision import apply_revision, compose_user_revision_input


class _FakeResult:
    def __init__(self, content): self.content = content

class _FakeAgent:
    def __init__(self, content): self._c = content
    def run(self, text): self.seen = text; return _FakeResult(self._c)


def _facts():
    return ProfileFacts(contact=Contact(name="Jane Dev"))


def test_compose_includes_instruction_and_current_content():
    content = ResumeContent(contact=Contact(name="Jane Dev"), summary="old")
    text = compose_user_revision_input(content, "make it punchier", _facts())
    assert "make it punchier" in text
    assert "old" in text
    assert "CANDIDATE PROFILE" in text


def test_apply_revision_returns_content():
    revised = ResumeContent(contact=Contact(name="Jane Dev"), summary="new")
    out = apply_revision("x", _FakeAgent(revised))
    assert out.summary == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_revision.py -v`
Expected: FAIL (`ModuleNotFoundError: resume_tailor_harness.tailor.revision`).

- [ ] **Step 3: Create the composer + run helper**

```python
# src/resume_tailor_harness/tailor/revision.py
from resume_tailor_harness.llm_runner import Runner
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent


def compose_user_revision_input(
    content: ResumeContent, instruction: str, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "USER INSTRUCTION (apply exactly; change only what is asked):\n"
        f"{instruction}"
    )


def apply_revision(input_text: str, agent: Runner) -> ResumeContent:
    content = agent.run(input_text).content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from revision agent, got {type(content).__name__}")
    return content
```

- [ ] **Step 4: Add the agent builder**

Append to `src/resume_tailor_harness/tailor/agents.py`:

```python
_REVISION_INSTRUCTIONS = [
    "Apply the user's instruction to the resume content. Change ONLY what the instruction asks; keep everything else intact.",
    "Use ONLY facts present in the candidate profile. Never invent anything to satisfy an instruction.",
    "Preserve fact-lock: every bullet, experience, project, and selected skill MUST keep a 'provenance' id pointing at a real profile fact.",
    "If the instruction cannot be satisfied without inventing an unsupported claim, make the closest truthful change and leave provenance valid.",
]


def build_revision_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise resume content per a user's instruction, strictly fact-locked.",
            instructions=compose_instructions(_REVISION_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_revision.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/tailor/revision.py src/resume_tailor_harness/tailor/agents.py tests/test_tailor_revision.py
git commit -m "feat: add resume revision agent and instruction composer"
```

---

### Task 4: Add revision agent to `TailorBundle`

**Files:**

- Modify: `src/resume_tailor_harness/services/agents.py:38-43` (`TailorBundle`), `:60-71` (`build_tailor_bundle`), `:81-90` (`__all__`)
- Test: `tests/test_services_agents.py` (create if absent)

**Interfaces:**

- Consumes: `build_revision_agent` (Task 3).
- Produces: `TailorBundle.revision: Runner`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_agents.py
from resume_tailor_harness.services import agents as A


def test_tailor_bundle_includes_revision(monkeypatch):
    monkeypatch.setattr(A, "build_tailor_agent", lambda **k: "tailor")
    monkeypatch.setattr(A, "build_reviser_agent", lambda **k: "reviser")
    monkeypatch.setattr(A, "build_revision_agent", lambda **k: "revision")
    monkeypatch.setattr(A, "build_reviewer_agent", lambda *a, **k: "rev")

    class Cfg:
        reviewers = []
    bundle = A.build_tailor_bundle(Cfg())
    assert bundle.revision == "revision"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py -v`
Expected: FAIL (`AttributeError: 'TailorBundle' object has no attribute 'revision'`).

- [ ] **Step 3: Wire the bundle**

In `services/agents.py`: import `build_revision_agent` alongside the other tailor builders; add `revision: Runner` to `TailorBundle`; set it in `build_tailor_bundle`:

```python
from resume_tailor_harness.tailor.agents import (
    build_reviewer_agent,
    build_reviser_agent,
    build_revision_agent,
    build_tailor_agent,
    model_for_tier,
)
```

```python
@dataclass
class TailorBundle:
    tailor: Runner
    reviser: Runner
    reviewers: Mapping[str, Runner]
    revision: Runner
```

```python
    return TailorBundle(
        tailor=build_tailor_agent(style_guide=style_guide),
        reviser=build_reviser_agent(style_guide=style_guide),
        reviewers=reviewers,
        revision=build_revision_agent(style_guide=style_guide),
    )
```

Add `"build_revision_agent"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/agents.py tests/test_services_agents.py
git commit -m "feat: expose revision agent on TailorBundle"
```

---

### Task 5: Resume revision service (`revise_resume_version`)

**Files:**

- Create: `src/resume_tailor_harness/services/revision.py`
- Test: `tests/test_services_revision.py`

**Interfaces:**

- Consumes: `get_resume_version`, `get_job`, `save_resume_version`, `load_facts`, `build_tailor_bundle`, `compose_user_revision_input`/`apply_revision` (Task 3), `provenance_critique` (`resume_tailor_harness.tailor.provenance`), `run_panel`/`aggregate` for the optional re-review.
- Produces: `revise_resume_version(session, version_id: int, instruction: str, *, re_review: bool = False, review_path: str = DEFAULT_REVIEW, facts_path: str = DEFAULT_FACTS, bundle: TailorBundle | None = None) -> ResumeVersion | None`. Returns the new version, or `None` if `version_id` does not exist.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_revision.py
from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent, TailoredExperience, TailoredBullet
from resume_tailor_harness.services.agents import TailorBundle
from resume_tailor_harness.services.revision import revise_resume_version
from resume_tailor_harness.tracking.repository import save_job, save_resume_version
from resume_tailor_harness.tracking.tables import Job, ResumeVersion


class _Result:
    def __init__(self, c): self.content = c

class _Agent:
    def __init__(self, c): self._c = c
    def run(self, text): return _Result(self._c)


def _facts():
    return ProfileFacts(contact=Contact(name="Jane Dev"))

def _supported_content():
    return ResumeContent(contact=Contact(name="Jane Dev"), summary="s")

def _unsupported_content():
    return ResumeContent(
        contact=Contact(name="Jane Dev"),
        experience=[TailoredExperience(company="X", title="Y", provenance="exp.real",
            bullets=[TailoredBullet(text="led 10", provenance="NOT_A_FACT")])],
    )

def _bundle(revised):
    return TailorBundle(tailor=_Agent(revised), reviser=_Agent(revised),
                        reviewers={}, revision=_Agent(revised))

def _seed(session):
    job = save_job(session, Job(source="url", company="Acme", title="Eng"))
    v = save_resume_version(session, ResumeVersion(
        job_id=job.id, round=2, content_json=_supported_content().model_dump(mode="json"),
        origin="tailor", fact_check_passed=True))
    return v


def test_revision_creates_child_version_with_lineage(monkeypatch, tmp_path):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(_facts().model_dump_json(), encoding="utf-8")
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        parent = _seed(s)
        new = revise_resume_version(
            s, parent.id, "be concise",
            facts_path=str(facts_file), bundle=_bundle(_supported_content()))
        assert new.origin == "revision"
        assert new.instruction == "be concise"
        assert new.parent_version_id == parent.id
        assert new.round == parent.round
        assert new.fact_check_passed is True
        assert new.review_score is None  # not panel-scored by default


def test_revision_persists_and_flags_unsupported(monkeypatch, tmp_path):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(_facts().model_dump_json(), encoding="utf-8")
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        parent = _seed(s)
        new = revise_resume_version(
            s, parent.id, "add team of 10",
            facts_path=str(facts_file), bundle=_bundle(_unsupported_content()))
        assert new.id is not None             # persisted, not dropped
        assert new.fact_check_passed is False  # flagged


def test_revision_missing_version_returns_none(tmp_path):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(_facts().model_dump_json(), encoding="utf-8")
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        assert revise_resume_version(
            s, 999, "x", facts_path=str(facts_file),
            bundle=_bundle(_supported_content())) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_revision.py -v`
Expected: FAIL (`ModuleNotFoundError: resume_tailor_harness.services.revision`).

- [ ] **Step 3: Implement the service**

```python
# src/resume_tailor_harness/services/revision.py
"""Use-case: apply a user instruction to a resume version, producing a new one."""

from __future__ import annotations

from sqlmodel import Session

from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.services.agents import TailorBundle, build_tailor_bundle
from resume_tailor_harness.tailor.provenance import provenance_critique
from resume_tailor_harness.tailor.review_config import load_review_config
from resume_tailor_harness.tailor.revision import apply_revision, compose_user_revision_input
from resume_tailor_harness.tailor.style_guide import load_style_guide
from resume_tailor_harness.tracking.repository import get_resume_version, save_resume_version
from resume_tailor_harness.tracking.tables import ResumeVersion

DEFAULT_REVIEW = "config/review.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


def revise_resume_version(
    session: Session,
    version_id: int,
    instruction: str,
    *,
    re_review: bool = False,
    review_path: str = DEFAULT_REVIEW,
    facts_path: str = DEFAULT_FACTS,
    bundle: TailorBundle | None = None,
) -> ResumeVersion | None:
    parent = get_resume_version(session, version_id)
    if parent is None:
        return None

    config = load_review_config(review_path)
    facts = load_facts(facts_path)
    if bundle is None:
        style_guide = load_style_guide(config.style_guide_path)
        bundle = build_tailor_bundle(config, style_guide=style_guide)

    current = ResumeContent.model_validate(parent.content_json or {})
    revised = apply_revision(
        compose_user_revision_input(current, instruction, facts), bundle.revision
    )

    provenance = provenance_critique(revised, facts)
    review_score: int | None = None
    if re_review and provenance.passed:
        from resume_tailor_harness.tailor.panel import run_panel
        from resume_tailor_harness.tailor.verdict import aggregate
        job = None  # jd_text not needed for scoring-only; pass parent's job text
        from resume_tailor_harness.tracking.repository import get_job
        job = get_job(session, parent.job_id)
        panel = run_panel(revised, facts, job.jd_text if job else "", config, bundle.reviewers)
        review_score = aggregate([provenance, *panel], config).aggregate_score

    child = ResumeVersion(
        job_id=parent.job_id,
        round=parent.round,
        content_json=revised.model_dump(mode="json"),
        origin="revision",
        instruction=instruction,
        parent_version_id=parent.id,
        fact_check_passed=provenance.passed,
        review_score=review_score,
    )
    return save_resume_version(session, child)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_revision.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/revision.py tests/test_services_revision.py
git commit -m "feat: resume version revision service with fact-gate flagging"
```

---

### Task 6: Cover-letter revision agent, composer, and service

**Files:**

- Modify: `src/resume_tailor_harness/cover_letter/agents.py` (add `build_cover_letter_revision_agent`)
- Modify: `src/resume_tailor_harness/cover_letter/drafting.py` (add `compose_user_revision_input` + run helper)
- Modify: `src/resume_tailor_harness/services/agents.py` (`CoverLetterBundle.revision`)
- Create: `src/resume_tailor_harness/services/cover_letter_revision.py`
- Test: `tests/test_services_cover_letter_revision.py`

**Interfaces:**

- Produces: `build_cover_letter_revision_agent(model_id=None) -> Runner`; `compose_cl_user_revision_input(content: CoverLetterContent, instruction: str, profile_facts: ProfileFacts) -> str`; `apply_cl_revision(text, agent) -> CoverLetterContent`; `CoverLetterBundle.revision: Runner`; `revise_cover_letter_version(session, cover_letter_id: int, instruction: str, *, facts_path=DEFAULT_FACTS, bundle: CoverLetterBundle | None = None) -> CoverLetter | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_cover_letter_revision.py
from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.services.agents import CoverLetterBundle
from resume_tailor_harness.services.cover_letter_revision import revise_cover_letter_version
from resume_tailor_harness.tracking.repository import save_cover_letter, save_job
from resume_tailor_harness.tracking.tables import CoverLetter, Job


class _Result:
    def __init__(self, c): self.content = c

class _Agent:
    def __init__(self, c): self._c = c
    def run(self, text): return _Result(self._c)


def _facts():
    return ProfileFacts(contact=Contact(name="Jane Dev"))

def _content():
    return CoverLetterContent(contact=Contact(name="Jane Dev"), greeting="Hi", closing="Best")


def test_cover_letter_revision_creates_child(tmp_path):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(_facts().model_dump_json(), encoding="utf-8")
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        parent = save_cover_letter(s, CoverLetter(
            job_id=job.id, content_json=_content().model_dump(mode="json"),
            origin="draft", fact_check_passed=True))
        bundle = CoverLetterBundle(draft=_Agent(_content()), reviser=_Agent(_content()),
                                   revision=_Agent(_content()))
        new = revise_cover_letter_version(
            s, parent.id, "warmer tone", facts_path=str(facts_file), bundle=bundle)
        assert new.origin == "revision"
        assert new.instruction == "warmer tone"
        assert new.parent_id == parent.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_cover_letter_revision.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Add agent builder**

Append to `src/resume_tailor_harness/cover_letter/agents.py`:

```python
_CL_REVISION_INSTRUCTIONS = [
    "Apply the user's instruction to the cover letter. Change ONLY what is asked; keep the rest intact.",
    "Use ONLY facts present in the candidate profile; never invent employers, projects, or metrics.",
    "Every paragraph's 'provenance' must list only ids that exist in the candidate profile.",
]


def build_cover_letter_revision_agent(model_id: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise cover letters per a user's instruction, strictly fact-locked.",
            instructions=_CL_REVISION_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
```

- [ ] **Step 4: Add composer + run helper**

Append to `src/resume_tailor_harness/cover_letter/drafting.py`:

```python
def compose_cl_user_revision_input(
    content: CoverLetterContent, instruction: str, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT COVER LETTER (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "USER INSTRUCTION (apply exactly; change only what is asked):\n"
        f"{instruction}"
    )


def apply_cl_revision(input_text: str, agent: Runner) -> CoverLetterContent:
    content = agent.run(input_text).content
    if not isinstance(content, CoverLetterContent):
        raise TypeError(f"Expected CoverLetterContent from revision agent, got {type(content).__name__}")
    return content
```

- [ ] **Step 5: Wire `CoverLetterBundle.revision`**

In `services/agents.py`: import `build_cover_letter_revision_agent`; add `revision: Runner` to `CoverLetterBundle`; set it in `build_cover_letter_bundle`; add the name to `__all__`.

```python
from resume_tailor_harness.cover_letter.agents import (
    build_cover_letter_agent,
    build_cover_letter_reviser_agent,
    build_cover_letter_revision_agent,
)
```

```python
@dataclass
class CoverLetterBundle:
    draft: Runner
    reviser: Runner
    revision: Runner
```

```python
def build_cover_letter_bundle() -> CoverLetterBundle:
    return CoverLetterBundle(
        draft=build_cover_letter_agent(),
        reviser=build_cover_letter_reviser_agent(),
        revision=build_cover_letter_revision_agent(),
    )
```

- [ ] **Step 6: Implement the service**

```python
# src/resume_tailor_harness/services/cover_letter_revision.py
"""Use-case: apply a user instruction to a cover letter, producing a new one."""

from __future__ import annotations

from sqlmodel import Session

from resume_tailor_harness.cover_letter.drafting import apply_cl_revision, compose_cl_user_revision_input
from resume_tailor_harness.cover_letter.provenance import collect_fact_ids, unsupported_provenance
from resume_tailor_harness.models.cover_letter import CoverLetterContent
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.services.agents import CoverLetterBundle, build_cover_letter_bundle
from resume_tailor_harness.tracking.repository import get_cover_letter, save_cover_letter
from resume_tailor_harness.tracking.tables import CoverLetter

DEFAULT_FACTS = "data/profile/facts.json"


def revise_cover_letter_version(
    session: Session,
    cover_letter_id: int,
    instruction: str,
    *,
    facts_path: str = DEFAULT_FACTS,
    bundle: CoverLetterBundle | None = None,
) -> CoverLetter | None:
    parent = get_cover_letter(session, cover_letter_id)
    if parent is None:
        return None
    facts = load_facts(facts_path)
    if bundle is None:
        bundle = build_cover_letter_bundle()

    current = CoverLetterContent.model_validate(parent.content_json or {})
    revised = apply_cl_revision(
        compose_cl_user_revision_input(current, instruction, facts), bundle.revision
    )
    passed = not unsupported_provenance(revised, collect_fact_ids(facts))
    child = CoverLetter(
        job_id=parent.job_id,
        content_json=revised.model_dump(mode="json"),
        origin="revision",
        instruction=instruction,
        parent_id=parent.id,
        fact_check_passed=passed,
    )
    return save_cover_letter(session, child)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_cover_letter_revision.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/resume_tailor_harness/cover_letter/agents.py src/resume_tailor_harness/cover_letter/drafting.py src/resume_tailor_harness/services/agents.py src/resume_tailor_harness/services/cover_letter_revision.py tests/test_services_cover_letter_revision.py
git commit -m "feat: cover-letter revision agent, composer, and service"
```

---

### Task 7: Version-selection service (set chosen resume/cover letter on the Application)

**Files:**

- Modify: `src/resume_tailor_harness/services/board.py:438-446` (after `upsert_application`)
- Test: `tests/test_services_board.py`

**Interfaces:**

- Consumes: `application_for_job`, `save_application`, `Application`.
- Produces: `select_resume_version(session, job_id: int, version_id: int) -> Application`; `select_cover_letter(session, job_id: int, cover_letter_id: int) -> Application`. Both create the Application if missing.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_services_board.py
from resume_tailor_harness.services.board import select_resume_version, select_cover_letter
from resume_tailor_harness.tracking.repository import save_job, save_resume_version
from resume_tailor_harness.tracking.tables import Job, ResumeVersion


def test_select_resume_version_sets_application_link(session):
    job = save_job(session, Job(source="url", company="Acme", title="Eng"))
    v = save_resume_version(session, ResumeVersion(job_id=job.id, round=1, content_json={}))
    app = select_resume_version(session, job.id, v.id)
    assert app.resume_version_id == v.id
```

(Use the existing `session` fixture in that test module; if none, build one with `make_engine("sqlite://")` + `init_db`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py::test_select_resume_version_sets_application_link -v`
Expected: FAIL (`ImportError: cannot import name 'select_resume_version'`).

- [ ] **Step 3: Implement the selectors**

Append to `src/resume_tailor_harness/services/board.py`:

```python
def select_resume_version(session: Session, job_id: int, version_id: int) -> Application:
    app = application_for_job(session, job_id)
    if app is None:
        app = Application(job_id=job_id, status="ready")
    app.resume_version_id = version_id
    return save_application(session, app)


def select_cover_letter(session: Session, job_id: int, cover_letter_id: int) -> Application:
    app = application_for_job(session, job_id)
    if app is None:
        app = Application(job_id=job_id, status="ready")
    app.cover_letter_id = cover_letter_id
    return save_application(session, app)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py::test_select_resume_version_sets_application_link -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/board.py tests/test_services_board.py
git commit -m "feat: application resume/cover-letter selection services"
```

---

### Task 8: API — resume revise + select endpoints and schema fields

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/jobs.py:73-81` (`ResumeVersionOut`), add `ReviseRequest`
- Modify: `src/resume_tailor_harness/api/routers/resumes.py` (add endpoints)
- Test: `tests/api/test_resumes_revise.py`

**Interfaces:**

- Consumes: `revise_resume_version` (Task 5), `select_resume_version` (Task 7).
- Produces: `POST /api/resume-versions/{id}/revise` body `ReviseRequest{instruction: str, reReview: bool=False}` → `ResumeVersionOut`; `POST /api/jobs/{job_id}/select-resume/{version_id}` → `ApplicationOut`. `ResumeVersionOut` gains `origin`, `instruction`, `parent_version_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_resumes_revise.py
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.profile import Contact
# Reuse the app/client + monkeypatch fixtures the other api tests use.
# This test asserts the endpoint shape; the revision service is faked.

def test_revise_endpoint_returns_new_version(client, seed_resume_version, monkeypatch):
    from resume_tailor_harness.api.routers import resumes as R
    new = seed_resume_version  # a persisted parent ResumeVersion id

    def fake_revise(session, version_id, instruction, **k):
        from resume_tailor_harness.tracking.tables import ResumeVersion
        from resume_tailor_harness.tracking.repository import save_resume_version
        return save_resume_version(session, ResumeVersion(
            job_id=1, round=1, content_json={}, origin="revision", instruction=instruction))
    monkeypatch.setattr(R, "revise_resume_version", fake_revise)

    resp = client.post(f"/api/resume-versions/{new}/revise", json={"instruction": "be concise"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["origin"] == "revision"
    assert body["instruction"] == "be concise"
```

(Model this on the existing api test harness — see `tests/api/` for the `client`/seed fixtures and the in-memory engine wiring. Add a `seed_resume_version` fixture that inserts a `Job` + parent `ResumeVersion` and returns the version id.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_resumes_revise.py -v`
Expected: FAIL (404 / missing route).

- [ ] **Step 3: Extend the schema**

In `src/resume_tailor_harness/api/schemas/jobs.py`, add to `ResumeVersionOut`:

```python
    origin: str = "tailor"
    instruction: str | None = None
    parent_version_id: int | None = None
```

Add a request model:

```python
class ReviseRequest(CamelModel):
    instruction: str
    re_review: bool = False
```

- [ ] **Step 4: Add the endpoints**

In `src/resume_tailor_harness/api/routers/resumes.py`:

```python
from resume_tailor_harness.api.schemas.jobs import ApplicationOut, ResumeVersionOut, ReviseRequest
from resume_tailor_harness.services.revision import revise_resume_version
from resume_tailor_harness.services.board import select_resume_version


@router.post("/resume-versions/{version_id}/revise", response_model=ResumeVersionOut)
def revise_endpoint(version_id: int, body: ReviseRequest, session: Session = Depends(get_session)):
    new = revise_resume_version(session, version_id, body.instruction, re_review=body.re_review)
    if new is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    return ResumeVersionOut.model_validate(new)


@router.post("/jobs/{job_id}/select-resume/{version_id}", response_model=ApplicationOut)
def select_resume_endpoint(job_id: int, version_id: int, session: Session = Depends(get_session)):
    app = select_resume_version(session, job_id, version_id)
    return ApplicationOut.model_validate(app)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_resumes_revise.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/jobs.py src/resume_tailor_harness/api/routers/resumes.py tests/api/test_resumes_revise.py
git commit -m "feat: resume revise + select-resume API endpoints"
```

---

### Task 9: API — cover letters in JobDetail + revise/select endpoints

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/jobs.py` (add `CoverLetterOut`; add `cover_letters` + `application` already present)
- Modify: `src/resume_tailor_harness/tracking/queries.py` (`job_detail_row` to include cover letters — locate the DTO it returns)
- Create: `src/resume_tailor_harness/api/routers/cover_letters.py`
- Modify: `src/resume_tailor_harness/api/app.py:16-22,83-91` (register router)
- Test: `tests/api/test_cover_letters_revise.py`

**Interfaces:**

- Consumes: `revise_cover_letter_version` (Task 6), `select_cover_letter` (Task 7), `get_cover_letter`.
- Produces: `CoverLetterOut{id, job_id, origin, instruction, parent_id, fact_check_passed, pdf_path, created_at}`; `JobDetail.cover_letters: list[CoverLetterOut]`; `POST /api/cover-letters/{id}/revise` → `CoverLetterOut`; `POST /api/jobs/{job_id}/select-cover-letter/{cover_letter_id}` → `ApplicationOut`; `GET /api/cover-letters/{id}/pdf`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_cover_letters_revise.py
def test_cover_letter_revise_endpoint(client, seed_cover_letter, monkeypatch):
    from resume_tailor_harness.api.routers import cover_letters as C
    cid = seed_cover_letter

    def fake_revise(session, cover_letter_id, instruction, **k):
        from resume_tailor_harness.tracking.tables import CoverLetter
        from resume_tailor_harness.tracking.repository import save_cover_letter
        return save_cover_letter(session, CoverLetter(
            job_id=1, content_json={}, origin="revision", instruction=instruction))
    monkeypatch.setattr(C, "revise_cover_letter_version", fake_revise)

    resp = client.post(f"/api/cover-letters/{cid}/revise", json={"instruction": "warmer"})
    assert resp.status_code == 200
    assert resp.json()["origin"] == "revision"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_cover_letters_revise.py -v`
Expected: FAIL (404 / no module).

- [ ] **Step 3: Add `CoverLetterOut` and extend `JobDetail`**

In `src/resume_tailor_harness/api/schemas/jobs.py`:

```python
class CoverLetterOut(CamelModel):
    id: int
    job_id: int
    origin: str = "draft"
    instruction: str | None = None
    parent_id: int | None = None
    fact_check_passed: bool
    pdf_path: str | None
    created_at: datetime
```

Add to `JobDetail`: `cover_letters: list[CoverLetterOut] = []` and `cover_letter_id: int | None = None` (the applied selection, mirrored onto `ApplicationOut` too: add `resume_version_id: int | None = None` and `cover_letter_id: int | None = None` to `ApplicationOut`).

- [ ] **Step 4: Include cover letters in the detail query**

In `src/resume_tailor_harness/tracking/queries.py`, locate `job_detail_row` and the DTO it builds; add a `cover_letters` field populated via `select(CoverLetter).where(CoverLetter.job_id == job_id)` ordered by `created_at`, parallel to how `resume_versions` is loaded. (Read the function first; mirror the existing resume-version loading exactly.)

- [ ] **Step 5: Create the router**

```python
# src/resume_tailor_harness/api/routers/cover_letters.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.jobs import ApplicationOut, CoverLetterOut, ReviseRequest
from resume_tailor_harness.services.board import select_cover_letter
from resume_tailor_harness.services.cover_letter_revision import revise_cover_letter_version
from resume_tailor_harness.tracking.repository import get_cover_letter

router = APIRouter()


@router.post("/cover-letters/{cover_letter_id}/revise", response_model=CoverLetterOut)
def revise_cover_letter_endpoint(
    cover_letter_id: int, body: ReviseRequest, session: Session = Depends(get_session)
):
    new = revise_cover_letter_version(session, cover_letter_id, body.instruction)
    if new is None:
        raise ApiException(404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found")
    return CoverLetterOut.model_validate(new)


@router.post("/jobs/{job_id}/select-cover-letter/{cover_letter_id}", response_model=ApplicationOut)
def select_cover_letter_endpoint(
    job_id: int, cover_letter_id: int, session: Session = Depends(get_session)
):
    return ApplicationOut.model_validate(select_cover_letter(session, job_id, cover_letter_id))


@router.get("/cover-letters/{cover_letter_id}/pdf")
def download_cover_letter_pdf(
    cover_letter_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    cover = get_cover_letter(session, cover_letter_id)
    if cover is None or not cover.pdf_path or not Path(cover.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this cover letter")
    return FileResponse(cover.pdf_path, media_type="application/pdf",
                        filename=Path(cover.pdf_path).name)
```

- [ ] **Step 6: Register the router**

In `src/resume_tailor_harness/api/app.py`, import `from resume_tailor_harness.api.routers import cover_letters as cover_letters_router` and add `app.include_router(cover_letters_router.router, prefix="/api", dependencies=guarded)`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_cover_letters_revise.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/resume_tailor_harness/api/ src/resume_tailor_harness/tracking/queries.py tests/api/test_cover_letters_revise.py
git commit -m "feat: cover-letter revise/select/pdf endpoints and JobDetail.cover_letters"
```

---

### Task 10: Regenerate API contracts

**Files:**

- Modify: `contracts/openapi.json`, `contracts/ts/api.ts` (generated)
- Verify: `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Regenerate**

Run: `bash scripts/gen_ts_client.sh`

- [ ] **Step 2: Verify the drift gate passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS. Then `ruff check` → clean.

- [ ] **Step 4: Commit**

```bash
git add contracts/
git commit -m "chore: regenerate API contracts for revision endpoints"
```

---

### Task 11: Frontend — revise + select mutations

**Files:**

- Modify: `web/src/features/job/use-job-mutations.ts` (add hooks)
- Test: `web/src/features/job/use-job-mutations.test.tsx` (create if absent; mirror an existing mutation test)

**Interfaces:**

- Produces: `useReviseVersion(jobId)`, `useReviseCoverLetter(jobId)`, `useSelectResume(jobId)`, `useSelectCoverLetter(jobId)` — each a TanStack mutation that POSTs and invalidates the job-detail query key.

- [ ] **Step 1: Write the failing test**

Mirror the existing `useRenderVersion` test (find it in the same folder). Assert the mutation calls `POST /api/resume-versions/{id}/revise` with `{instruction}` and invalidates the job-detail query. (Use the project's existing MSW/fetch-mock setup — read a neighboring `*.test.tsx` first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/job/use-job-mutations.test.tsx`
Expected: FAIL (hook not exported).

- [ ] **Step 3: Implement the hooks**

In `web/src/features/job/use-job-mutations.ts`, mirror `useRenderVersion`:

```ts
export function useReviseVersion(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      versionId,
      instruction,
      reReview,
    }: {
      versionId: number;
      instruction: string;
      reReview?: boolean;
    }) =>
      apiPost(`/api/resume-versions/${versionId}/revise`, {
        instruction,
        reReview: reReview ?? false,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}

export function useSelectResume(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      apiPost(`/api/jobs/${jobId}/select-resume/${versionId}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}

export function useReviseCoverLetter(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      coverLetterId,
      instruction,
    }: {
      coverLetterId: number;
      instruction: string;
    }) =>
      apiPost(`/api/cover-letters/${coverLetterId}/revise`, { instruction }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}

export function useSelectCoverLetter(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (coverLetterId: number) =>
      apiPost(`/api/jobs/${jobId}/select-cover-letter/${coverLetterId}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}
```

(Match the existing query-key shape and the `apiPost` helper name actually used in this file — read it first; adapt names if they differ, e.g. `client.post`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/job/use-job-mutations.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/job/use-job-mutations.ts web/src/features/job/use-job-mutations.test.tsx
git commit -m "feat: revise + select mutation hooks"
```

---

### Task 12: Frontend — Versions tab revise UI + lineage + selection

**Files:**

- Create: `web/src/features/job/VersionRow.tsx` (one version row with revise box + use-for-application)
- Modify: `web/src/components/JobModal.tsx:100-140` (Versions tab body → render `VersionRow`)
- Test: `web/src/features/job/VersionRow.test.tsx`

**Interfaces:**

- Consumes: `useReviseVersion`, `useSelectResume` (Task 11); `ResumeVersionOut` (now with `origin`/`instruction`/`parentVersionId`).
- Produces: `VersionRow` — renders round/score/fact-check, a red badge when `!factCheckPassed`, origin + instruction text on revisions, an instruction `<input>` + Revise button + reReview checkbox, a "Use for application" button (highlighted when this id equals the application's `resumeVersionId`), and the existing Download/Render affordance.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/VersionRow.test.tsx
import { render, screen } from "@testing-library/react";
import { VersionRow } from "./VersionRow";
// wrap in the project's QueryClientProvider test helper (see neighboring tests)

it("shows the instruction and a fact-check-failed badge on a flagged revision", () => {
  const v = {
    id: 5,
    jobId: 1,
    round: 2,
    reviewScore: null,
    factCheckPassed: false,
    pdfPath: null,
    origin: "revision",
    instruction: "add team of 10",
    parentVersionId: 3,
    createdAt: "2026-06-26T00:00:00Z",
    critiqueJson: null,
  };
  renderWithClient(
    <VersionRow jobId={1} version={v as any} appliedVersionId={null} />,
  );
  expect(screen.getByText(/add team of 10/)).toBeInTheDocument();
  expect(screen.getByText(/fact-check ✗/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/job/VersionRow.test.tsx`
Expected: FAIL (no `VersionRow`).

- [ ] **Step 3: Implement `VersionRow`**

```tsx
// web/src/features/job/VersionRow.tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { withTokenParam } from "@/lib/api/client";
import { useReviseVersion, useSelectResume } from "./use-job-mutations";
import type { components } from "@/lib/api/schema";

type V = components["schemas"]["ResumeVersionOut"];

export function VersionRow({
  jobId,
  version,
  appliedVersionId,
}: {
  jobId: number;
  version: V;
  appliedVersionId: number | null;
}) {
  const [instruction, setInstruction] = useState("");
  const [reReview, setReReview] = useState(false);
  const revise = useReviseVersion(jobId);
  const select = useSelectResume(jobId);
  const applied = appliedVersionId === version.id;

  return (
    <li className="space-y-2 rounded-xl border bg-background/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>
          {version.origin === "revision"
            ? "Revision"
            : `Round ${version.round}`}{" "}
          · score {version.reviewScore ?? "—"} ·{" "}
          <span className={version.factCheckPassed ? "" : "text-destructive"}>
            {version.factCheckPassed ? "fact-check ✓" : "fact-check ✗"}
          </span>
          {version.parentVersionId && (
            <span className="ml-1 opacity-60">
              (from #{version.parentVersionId})
            </span>
          )}
        </span>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={applied ? "default" : "outline"}
            onClick={() => select.mutate(version.id)}
          >
            {applied ? "Applied ✓" : "Use for application"}
          </Button>
          {version.pdfPath && (
            <a
              className="text-sm underline"
              target="_blank"
              rel="noreferrer"
              href={withTokenParam(`/api/resume-versions/${version.id}/pdf`)}
            >
              Download PDF
            </a>
          )}
        </div>
      </div>
      {version.instruction && (
        <p className="text-xs italic text-muted-foreground">
          “{version.instruction}”
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="Revise: e.g. lead with Python, drop volunteering"
          className="flex-1"
        />
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <Checkbox
            checked={reReview}
            onCheckedChange={(v) => setReReview(Boolean(v))}
          />{" "}
          re-review
        </label>
        <Button
          size="sm"
          disabled={!instruction.trim() || revise.isPending}
          onClick={() =>
            revise.mutate(
              { versionId: version.id, instruction, reReview },
              { onSuccess: () => setInstruction("") },
            )
          }
        >
          {revise.isPending ? "Revising…" : "Revise"}
        </Button>
      </div>
    </li>
  );
}
```

- [ ] **Step 4: Render `VersionRow` in the Versions tab**

In `JobModal.tsx`, replace the `<li>` map body (lines ~110-138) with:

```tsx
<ul className="mt-2 space-y-2">
  {job.resumeVersions.map((v) => (
    <VersionRow
      key={v.id}
      jobId={jobId}
      version={v}
      appliedVersionId={job.application?.resumeVersionId ?? null}
    />
  ))}
</ul>
```

Add `import { VersionRow } from "@/features/job/VersionRow";`.

- [ ] **Step 5: Run test + typecheck**

Run: `cd web && npx vitest run src/features/job/VersionRow.test.tsx && npx tsc --noEmit`
Expected: PASS / no type errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/job/VersionRow.tsx web/src/components/JobModal.tsx web/src/features/job/VersionRow.test.tsx
git commit -m "feat: Versions tab revise box, lineage, and apply-selection"
```

---

### Task 13: Frontend — Cover Letters tab

**Files:**

- Create: `web/src/features/job/CoverLetterRow.tsx`
- Create: `web/src/features/job/CoverLettersTab.tsx`
- Modify: `web/src/components/JobModal.tsx:72-85` (add `<TabsTrigger value="coverLetters">`), `:142-148` (add `<TabsContent>`)
- Test: `web/src/features/job/CoverLettersTab.test.tsx`

**Interfaces:**

- Consumes: `useReviseCoverLetter`, `useSelectCoverLetter` (Task 11); `JobDetail.coverLetters: CoverLetterOut[]`, `application.coverLetterId`.
- Produces: a tab listing each cover letter with the same revise + use-for-application affordances as `VersionRow`, PDF link to `/api/cover-letters/{id}/pdf`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/CoverLettersTab.test.tsx
import { render, screen } from "@testing-library/react";
import { CoverLettersTab } from "./CoverLettersTab";

it("renders an empty state when there are no cover letters", () => {
  renderWithClient(
    <CoverLettersTab jobId={1} coverLetters={[]} appliedId={null} />,
  );
  expect(screen.getByText(/no cover letter/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/job/CoverLettersTab.test.tsx`
Expected: FAIL (no module).

- [ ] **Step 3: Implement `CoverLetterRow` and `CoverLettersTab`**

`CoverLetterRow.tsx` mirrors `VersionRow` but uses `useReviseCoverLetter`/`useSelectCoverLetter`, the `CoverLetterOut` type, and the `/api/cover-letters/${id}/pdf` link (no round/score line — show `origin`, fact-check, instruction, parent). `CoverLettersTab.tsx`:

```tsx
// web/src/features/job/CoverLettersTab.tsx
import { CoverLetterRow } from "./CoverLetterRow";
import type { components } from "@/lib/api/schema";

type CL = components["schemas"]["CoverLetterOut"];

export function CoverLettersTab({
  jobId,
  coverLetters,
  appliedId,
}: {
  jobId: number;
  coverLetters: CL[];
  appliedId: number | null;
}) {
  if (coverLetters.length === 0) {
    return (
      <p className="mt-2 text-sm text-muted-foreground">No cover letter yet.</p>
    );
  }
  return (
    <ul className="mt-2 space-y-2">
      {coverLetters.map((cl) => (
        <CoverLetterRow
          key={cl.id}
          jobId={jobId}
          coverLetter={cl}
          appliedId={appliedId}
        />
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Wire the tab into `JobModal`**

Add a trigger `<TabsTrigger value="coverLetters" className="text-sm">Cover letters</TabsTrigger>` and a content block:

```tsx
<TabsContent value="coverLetters" className="mt-0">
  <CoverLettersTab
    jobId={jobId}
    coverLetters={job.coverLetters ?? []}
    appliedId={job.application?.coverLetterId ?? null}
  />
</TabsContent>
```

Add the import.

- [ ] **Step 5: Run test + typecheck**

Run: `cd web && npx vitest run src/features/job/CoverLettersTab.test.tsx && npx tsc --noEmit`
Expected: PASS / no type errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/job/CoverLetterRow.tsx web/src/features/job/CoverLettersTab.tsx web/src/components/JobModal.tsx web/src/features/job/CoverLettersTab.test.tsx
git commit -m "feat: Cover Letters tab with revise and apply-selection"
```

---

### Task 14: Full verification pass

- [ ] **Step 1: Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest` then `ruff check`
Expected: all PASS, lint clean.

- [ ] **Step 2: Frontend suite + typecheck + build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all PASS, build succeeds.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Start `resume-tailor-harness serve`, open the web app, open a tailored job → Versions tab → type "make the summary more concise" → Revise → confirm a new revision row appears with the instruction shown and a fact-check badge; click "Use for application"; check the Cover Letters tab revise flow.

- [ ] **Step 4: Final commit (if any docs/cleanup)**

```bash
git add -A
git commit -m "chore: phase-1 revision verification"
```

---

## Self-Review

**Spec coverage (Phase 1 only):**

- Single-shot instructed revision → Tasks 3–6, 8–9. ✓
- Dedicated revision agent + composer (resume + CL) → Tasks 3, 6. ✓
- Persist-and-flag failing fact-check → Task 5 (`test_revision_persists_and_flags_unsupported`), Task 6. ✓
- Fact-gate-only default, `reReview` opt-in panel → Task 5 (`re_review` param), Task 8 (`ReviseRequest.re_review`), Task 12 (checkbox). ✓
- `ResumeVersion`/`CoverLetter` revision columns + `Application.cover_letter_id` → Tasks 1, 2. ✓
- Synchronous `POST …/revise` endpoints → Tasks 8, 9. ✓
- Explicit version selection (`Application.resume_version_id`/`cover_letter_id`) → Tasks 7–9, 12, 13. ✓
- Frontend Versions tab extension + new Cover Letters tab → Tasks 12, 13. ✓
- Contract regen + drift gate → Task 10. ✓

**Deferred to later plans (Phases 2 & 3 — explicitly out of this plan):** per-job folder export/manifest projection; Gmail `Notification` table, sync Run, and notifications surface. These depend only on the columns added here, not on each other.

**Placeholder scan:** No TBD/TODO. Two tasks (8 step-1 fixtures, 11/12 test harness) instruct the implementer to mirror an existing neighboring test for the project's fixture/mock setup rather than inventing one — this is deliberate (the harness already exists and must be matched), not a placeholder for missing logic.

**Type consistency:** `revise_resume_version(session, version_id, instruction, *, re_review=...)` is called identically in Task 8. `revise_cover_letter_version(session, cover_letter_id, instruction, ...)` matches Task 9. `select_resume_version`/`select_cover_letter` signatures match between Tasks 7 and 8/9. `TailorBundle.revision` / `CoverLetterBundle.revision` defined in Tasks 4/6 and consumed in Task 5/6. Schema field `parent_version_id` (snake) ↔ `parentVersionId` (camel wire) is consistent with the `CamelModel` convention. `CoverLetter.parent_id` ↔ `parentId` likewise.
