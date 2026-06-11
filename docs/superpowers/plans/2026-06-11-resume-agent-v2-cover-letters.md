# Resume Agent v2 — Cover-Letter Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a **fact-locked cover letter** per job, reusing the resume pipeline's machinery: an LLM drafts `CoverLetterContent` drawing only on `ProfileFacts`, a **deterministic provenance gate** (every paragraph cites real fact ids) blocks fabrication and drives a revise loop, and a Typst template renders it to PDF. A `cover-letter` CLI command runs draft → gate → render.

**Architecture:** This is **Plan 4 of 6** for v2 (spec `docs/superpowers/specs/2026-06-11-resume-agent-v2-connectors-design.md`), an independent leaf depending only on Plan 1's merge and v1's tailor/render/profile modules. The fact-lock gate is **deterministic and pure** (`unsupported_provenance`) — the design's "partially verifiable in plain code before any LLM runs" (§3.1) applied to cover letters; it is the test surface, and it needs no API key. Generation (LLM) and rendering (Typst) are split into separate functions exactly like the resume `tailor`/`render` split, so each is tested in isolation with an injected fake.

**Tech Stack:** Python 3.13, uv, Agno (`Agent`/`Claude`), Typst (`typst`), SQLModel, Typer, pytest. No new deps.

**Depends on:** **Plan 1 merged.** Reuses `models.profile` (`Contact`, `ProfileFacts`, `FactItem` ids), `models.job.JobCriteria`, `llm_runner` (`Runner`/`AgentRunner`), `render.renderer.output_filename`, `tracking` tables/repository, `profile.store.load_facts`.

> **Commit convention:** every commit ends with `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`.

---

## Architecture notes (the two lenses)

**Deepening:** `unsupported_provenance(content, fact_ids)` is the deep gate — a tiny signature concentrating *all* anti-fabrication logic for cover letters in one pure function (the **interface is the test surface**; the adversarial "fabricated claim is blocked" test lives here). `collect_fact_ids` is the single place that knows the shape of `ProfileFacts` ids, shared by gate and service.

**Restraint (karpathy):** the review is the **deterministic provenance gate only** — no 5-agent panel (cover letters are lower-stakes than the resume; the spec said "light review"). No new `RenderConfig`; cover letters get their own template constant rather than overloading the resume render config. The revise loop is capped at a small `max_rounds` (default 2) — enough to fix a fabrication, not an open-ended spend.

---

## File Structure

```
src/resume_agent/models/cover_letter.py        # CREATE — CoverLetterContent + paragraph
src/resume_agent/cover_letter/
  __init__.py                                   # CREATE
  provenance.py                                 # CREATE — collect_fact_ids + unsupported_provenance
  agents.py                                     # CREATE — build draft/reviser agents
  drafting.py                                   # CREATE — compose/draft/revise (pure composition)
  service.py                                    # CREATE — generate_cover_letter (loop + persist)
  render.py                                     # CREATE — render_cover_letter_pdf + render_cover_letter
src/resume_agent/tracking/tables.py             # MODIFY — CoverLetter table
src/resume_agent/tracking/repository.py         # MODIFY — save/get cover letter
templates/cover_letter.typ                      # CREATE
src/resume_agent/cli.py                         # MODIFY — cover-letter command
tests/test_cover_letter_models.py               # CREATE
tests/test_cover_letter_table.py                # CREATE
tests/test_cover_letter_provenance.py           # CREATE
tests/test_cover_letter_drafting.py             # CREATE
tests/test_cover_letter_service.py              # CREATE
tests/test_cover_letter_render.py               # CREATE
tests/test_cli_cover_letter.py                  # CREATE
```

---

## Task 1: `CoverLetterContent` model

**Files:**
- Create: `src/resume_agent/models/cover_letter.py`
- Test: `tests/test_cover_letter_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_models.py`:
```python
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact


def test_cover_letter_content_roundtrips():
    content = CoverLetterContent(
        contact=Contact(name="Ada Lovelace", email="ada@x.io"),
        recipient="Hiring Team at Acme",
        greeting="Dear Hiring Team,",
        paragraphs=[CoverLetterParagraph(text="I build payment systems.", provenance=["exp1"])],
        closing="Sincerely,\nAda Lovelace",
    )
    dumped = content.model_dump(mode="json")
    again = CoverLetterContent.model_validate(dumped)
    assert again.paragraphs[0].provenance == ["exp1"]
    assert again.contact.name == "Ada Lovelace"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models.cover_letter'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/models/cover_letter.py`:
```python
from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import Contact


class CoverLetterParagraph(ExtensibleModel):
    """A body paragraph. ``provenance`` lists the ProfileFacts fact ids it draws on."""

    text: str
    provenance: list[str] = Field(default_factory=list)


class CoverLetterContent(ExtensibleModel):
    """Structured, fact-locked cover letter. The renderer turns this into a PDF."""

    contact: Contact  # carried verbatim from ProfileFacts
    recipient: str | None = None
    greeting: str
    paragraphs: list[CoverLetterParagraph] = Field(default_factory=list)
    closing: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_models.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/cover_letter.py tests/test_cover_letter_models.py
git commit -m "feat(cover-letter): CoverLetterContent model" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `CoverLetter` table + repository

**Files:**
- Modify: `src/resume_agent/tracking/tables.py`, `src/resume_agent/tracking/repository.py`
- Test: `tests/test_cover_letter_table.py`

> A *new table* is created automatically by `SQLModel.metadata.create_all` on the next `init_db` — no migration needed (unlike Plan 1's new *column*).

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_table.py`:
```python
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.tracking.repository import get_cover_letter, save_cover_letter
from resume_agent.tracking.tables import CoverLetter


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_save_and_get_cover_letter():
    with _session() as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        saved = save_cover_letter(
            s, CoverLetter(job_id=job.id, content_json={"greeting": "Hi"}, fact_check_passed=True)
        )
        assert saved.id is not None
        fetched = get_cover_letter(s, saved.id)
        assert fetched.job_id == job.id
        assert fetched.fact_check_passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_table.py -v`
Expected: FAIL — `ImportError: cannot import name 'CoverLetter' from 'resume_agent.tracking.tables'`.

- [ ] **Step 3: Add the table**

In `src/resume_agent/tracking/tables.py`, add after the `Application` class:
```python
class CoverLetter(SQLModel, table=True):
    __tablename__ = cast(Any, "cover_letters")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    pdf_path: str | None = None
    fact_check_passed: bool = False
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
```

- [ ] **Step 4: Add repository functions**

In `src/resume_agent/tracking/repository.py`, update the import line to include `CoverLetter`:
```python
from resume_agent.tracking.tables import Application, ApplicationStatus, CoverLetter, Job, ResumeVersion, utcnow
```
Add at the end of the file:
```python
def save_cover_letter(session: Session, cover_letter: CoverLetter) -> CoverLetter:
    session.add(cover_letter)
    session.commit()
    session.refresh(cover_letter)
    return cover_letter


def get_cover_letter(session: Session, cover_letter_id: int) -> CoverLetter | None:
    return session.get(CoverLetter, cover_letter_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_table.py -v`
Expected: PASS (1 test).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tracking/tables.py src/resume_agent/tracking/repository.py tests/test_cover_letter_table.py
git commit -m "feat(cover-letter): cover_letters table + repository" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: deterministic provenance gate

**Files:**
- Create: `src/resume_agent/cover_letter/__init__.py`, `src/resume_agent/cover_letter/provenance.py`
- Test: `tests/test_cover_letter_provenance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_provenance.py`:
```python
from resume_agent.cover_letter.provenance import collect_fact_ids, unsupported_provenance
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact, Experience, ProfileFacts, Skill


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer")],
        skills={"languages": [Skill(id="sk1", name="Python")]},
    )


def _letter(*provenances):
    return CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi,",
        paragraphs=[CoverLetterParagraph(text="p", provenance=list(p)) for p in provenances],
        closing="Bye",
    )


def test_collect_fact_ids_includes_experiences_and_skills():
    ids = collect_fact_ids(_facts())
    assert "exp1" in ids and "sk1" in ids


def test_supported_letter_has_no_unsupported_ids():
    assert unsupported_provenance(_letter(["exp1"], ["sk1"]), collect_fact_ids(_facts())) == []


def test_fabricated_provenance_is_flagged():
    bad = unsupported_provenance(_letter(["exp1"], ["GHOST"]), collect_fact_ids(_facts()))
    assert bad == ["GHOST"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.cover_letter'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/cover_letter/__init__.py`:
```python
"""Fact-locked cover-letter generation: draft → deterministic provenance gate → render."""
```

Create `src/resume_agent/cover_letter/provenance.py`:
```python
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.profile import ProfileFacts


def collect_fact_ids(facts: ProfileFacts) -> set[str]:
    """Every provenance-eligible fact id in the profile (the cover letter may cite only these)."""
    ids: set[str] = set()
    for exp in facts.experience:
        ids.add(exp.id)
        for bullet in exp.bullets:
            ids.add(bullet.id)
    for project in facts.projects:
        ids.add(project.id)
    for skills in facts.skills.values():
        for skill in skills:
            ids.add(skill.id)
    for group in (
        facts.education, facts.certifications, facts.publications,
        facts.awards, facts.languages, facts.volunteer,
    ):
        for item in group:
            ids.add(item.id)
    if facts.github_profile is not None:
        ids.add(facts.github_profile.id)
    return ids


def unsupported_provenance(content: CoverLetterContent, fact_ids: set[str]) -> list[str]:
    """Provenance ids cited by the letter that do not exist in the profile (fabrication signal)."""
    return [
        pid
        for paragraph in content.paragraphs
        for pid in paragraph.provenance
        if pid not in fact_ids
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_provenance.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cover_letter/__init__.py src/resume_agent/cover_letter/provenance.py tests/test_cover_letter_provenance.py
git commit -m "feat(cover-letter): deterministic provenance gate" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: draft/reviser agents + pure composition

**Files:**
- Create: `src/resume_agent/cover_letter/agents.py`, `src/resume_agent/cover_letter/drafting.py`
- Test: `tests/test_cover_letter_drafting.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_drafting.py`:
```python
from resume_agent.cover_letter.drafting import (
    compose_cover_letter_input,
    compose_revise_input,
    draft_cover_letter,
)
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, Experience, ProfileFacts


class _Result:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        self.prompt = prompt
        return _Result(self._content)


def _facts():
    return ProfileFacts(contact=Contact(name="Ada"), experience=[Experience(id="exp1", company="Acme", title="Eng")])


def test_compose_input_includes_profile_and_jd():
    text = compose_cover_letter_input("Build APIs", JobCriteria(), _facts())
    assert "Acme" in text and "Build APIs" in text


def test_draft_returns_typed_content():
    letter = CoverLetterContent(contact=Contact(name="Ada"), greeting="Hi", paragraphs=[], closing="Bye")
    agent = _FakeAgent(letter)
    out = draft_cover_letter("input", agent)
    assert isinstance(out, CoverLetterContent)


def test_revise_input_names_unsupported_ids():
    letter = CoverLetterContent(
        contact=Contact(name="Ada"), greeting="Hi",
        paragraphs=[CoverLetterParagraph(text="p", provenance=["GHOST"])], closing="Bye",
    )
    text = compose_revise_input(letter, ["GHOST"], _facts(), "Build APIs")
    assert "GHOST" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_drafting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.cover_letter.drafting'`.

- [ ] **Step 3: Implement the agents**

Create `src/resume_agent/cover_letter/agents.py`:
```python
from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.tailor.agents import model_for_tier

_DRAFT_INSTRUCTIONS = [
    "Write a concise, specific cover letter for the candidate targeting the given job.",
    "Use ONLY facts present in the candidate profile. Never invent employers, projects, skills, or metrics.",
    "Each paragraph MUST list in 'provenance' the ids of the profile facts it draws on.",
    "Use 3-4 short paragraphs: open with genuine fit, give evidence from real experience, close with intent.",
]

_REVISE_INSTRUCTIONS = [
    "Revise the cover letter to remove any claim whose provenance id is not a real profile fact.",
    "Every paragraph's 'provenance' must list only ids that exist in the candidate profile.",
    "Keep it concise and truthful; introduce no new unsupported claims.",
]


def build_cover_letter_agent(model_id: str | None = None) -> Runner:
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("premium")),
            description="You are an expert cover-letter writer who never fabricates.",
            instructions=_DRAFT_INSTRUCTIONS,
            output_schema=CoverLetterContent,
        )
    )


def build_cover_letter_reviser_agent(model_id: str | None = None) -> Runner:
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("mid")),
            description="You revise cover letters to keep every claim fact-locked.",
            instructions=_REVISE_INSTRUCTIONS,
            output_schema=CoverLetterContent,
        )
    )
```

- [ ] **Step 4: Implement the composition**

Create `src/resume_agent/cover_letter/drafting.py`:
```python
from resume_agent.llm_runner import Runner
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts


def compose_cover_letter_input(jd_text: str, criteria: JobCriteria, profile_facts: ProfileFacts) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def draft_cover_letter(input_text: str, agent: Runner) -> CoverLetterContent:
    content = agent.run(input_text).content
    if not isinstance(content, CoverLetterContent):
        raise TypeError(f"Expected CoverLetterContent from draft agent, got {type(content).__name__}")
    return content


def compose_revise_input(
    content: CoverLetterContent, unsupported_ids: list[str], profile_facts: ProfileFacts, jd_text: str
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT COVER LETTER (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "UNSUPPORTED PROVENANCE IDS (remove or re-ground these claims):\n"
        f"{', '.join(unsupported_ids)}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def revise_cover_letter(input_text: str, agent: Runner) -> CoverLetterContent:
    content = agent.run(input_text).content
    if not isinstance(content, CoverLetterContent):
        raise TypeError(f"Expected CoverLetterContent from reviser agent, got {type(content).__name__}")
    return content
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_drafting.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cover_letter/agents.py src/resume_agent/cover_letter/drafting.py tests/test_cover_letter_drafting.py
git commit -m "feat(cover-letter): draft/reviser agents + composition" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `generate_cover_letter` service (gate + revise loop + persist)

**Files:**
- Create: `src/resume_agent/cover_letter/service.py`
- Test: `tests/test_cover_letter_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_service.py`:
```python
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.cover_letter.service import generate_cover_letter
from resume_agent.discovery.ingest import add_job
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact, Experience, ProfileFacts


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _facts():
    return ProfileFacts(contact=Contact(name="Ada"), experience=[Experience(id="exp1", company="Acme", title="Eng")])


def _letter(prov):
    return CoverLetterContent(
        contact=Contact(name="Ada"), greeting="Hi",
        paragraphs=[CoverLetterParagraph(text="p", provenance=[prov])], closing="Bye",
    )


class _Result:
    def __init__(self, c):
        self.content = c


class _Agent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _Result(self._content)


def test_generate_revises_until_provenance_clean_then_persists():
    # First draft fabricates ("GHOST"); reviser produces a supported letter ("exp1").
    draft_agent = _Agent(_letter("GHOST"))
    reviser_agent = _Agent(_letter("exp1"))
    with _session() as s:
        job = add_job(s, source="manual", jd_text="Build APIs", company="Acme", title="Eng")
        cover = generate_cover_letter(s, job, _facts(), draft_agent, reviser_agent, max_rounds=2)
        assert cover.id is not None
        assert cover.fact_check_passed is True
        assert cover.content_json["paragraphs"][0]["provenance"] == ["exp1"]


def test_generate_marks_unfixed_fabrication_as_failed():
    draft_agent = _Agent(_letter("GHOST"))
    reviser_agent = _Agent(_letter("STILL_BAD"))
    with _session() as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        cover = generate_cover_letter(s, job, _facts(), draft_agent, reviser_agent, max_rounds=2)
        assert cover.fact_check_passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.cover_letter.service'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/cover_letter/service.py`:
```python
from sqlmodel import Session

from resume_agent.cover_letter.drafting import (
    compose_cover_letter_input,
    compose_revise_input,
    draft_cover_letter,
    revise_cover_letter,
)
from resume_agent.cover_letter.provenance import collect_fact_ids, unsupported_provenance
from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.repository import save_cover_letter
from resume_agent.tracking.tables import CoverLetter, Job


def generate_cover_letter(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    draft_agent: Runner,
    reviser_agent: Runner,
    max_rounds: int = 2,
) -> CoverLetter:
    """Draft a fact-locked cover letter, revise until provenance is clean (or max_rounds), persist."""
    if job.id is None:
        raise ValueError("Cannot write a cover letter for a job that has not been persisted")
    fact_ids = collect_fact_ids(profile_facts)
    criteria = JobCriteria.model_validate(job.criteria_json or {})

    content = draft_cover_letter(
        compose_cover_letter_input(job.jd_text, criteria, profile_facts), draft_agent
    )
    for _ in range(max_rounds - 1):
        bad = unsupported_provenance(content, fact_ids)
        if not bad:
            break
        content = revise_cover_letter(
            compose_revise_input(content, bad, profile_facts, job.jd_text), reviser_agent
        )

    passed = not unsupported_provenance(content, fact_ids)
    cover = CoverLetter(
        job_id=job.id,
        content_json=content.model_dump(mode="json"),
        fact_check_passed=passed,
    )
    return save_cover_letter(session, cover)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cover_letter/service.py tests/test_cover_letter_service.py
git commit -m "feat(cover-letter): generate_cover_letter gate+revise loop" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Typst template + render

**Files:**
- Create: `templates/cover_letter.typ`, `src/resume_agent/cover_letter/render.py`
- Test: `tests/test_cover_letter_render.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cover_letter_render.py`:
```python
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.cover_letter.render import render_cover_letter
from resume_agent.discovery.ingest import add_job
from resume_agent.tracking.repository import get_cover_letter, save_cover_letter
from resume_agent.tracking.tables import CoverLetter


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_render_cover_letter_writes_pdf_path(tmp_path):
    calls = {}

    def fake_render(content, output_path, template_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        calls["path"] = Path(output_path)
        return Path(output_path)

    with _session() as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme Corp", title="Backend Engineer")
        cover = save_cover_letter(
            s, CoverLetter(job_id=job.id, content_json={"contact": {"name": "Ada"}, "greeting": "Hi",
                                                        "paragraphs": [], "closing": "Bye"})
        )
        out = render_cover_letter(s, cover.id, output_dir=str(tmp_path), render_fn=fake_render)
        assert out == calls["path"]
        assert get_cover_letter(s, cover.id).pdf_path == str(out)
        assert "acme_corp" in out.name and "cl" in out.name


def test_render_missing_cover_letter_returns_none(tmp_path):
    with _session() as s:
        assert render_cover_letter(s, 999, output_dir=str(tmp_path), render_fn=lambda *a: None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cover_letter_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.cover_letter.render'`.

- [ ] **Step 3: Create the template**

Create `templates/cover_letter.typ`:
```typst
// Cover letter. Data arrives as a JSON string in `sys.inputs.data`.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: "Cover Letter — " + contact.name)
#set page(margin: (x: 2cm, y: 2cm))
#set text(size: 11pt)
#set par(justify: true, leading: 0.62em)

#align(right)[
  #text(weight: "bold", size: 13pt)[#contact.name] \
  #let bits = (
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none)
  #if bits.len() > 0 [ #bits.join("  •  ") ]
]
#v(1.2em)

#let recipient = data.at("recipient", default: none)
#if recipient != none [ #recipient \ #v(0.6em) ]

#data.greeting
#v(0.6em)

#for p in data.at("paragraphs", default: ()) [
  #p.text
  #v(0.6em)
]

#data.closing
```

- [ ] **Step 4: Implement the render module**

Create `src/resume_agent/cover_letter/render.py`:
```python
from pathlib import Path
from typing import Callable

import typst
from sqlmodel import Session

from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.render.renderer import output_filename
from resume_agent.tracking.repository import get_cover_letter, get_job, save_cover_letter
from resume_agent.tracking.tables import utcnow

TEMPLATE = "templates/cover_letter.typ"
RenderFn = Callable[[CoverLetterContent, str | Path, str | Path], Path]


def render_cover_letter_pdf(
    content: CoverLetterContent,
    output_path: str | Path,
    template_path: str | Path = TEMPLATE,
) -> Path:
    """Compile the cover-letter Typst template with the JSON content into a PDF."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(str(template_path), output=str(out), sys_inputs={"data": content.model_dump_json()})
    return out


def render_cover_letter(
    session: Session,
    cover_letter_id: int,
    output_dir: str | Path = "output",
    template_path: str | Path = TEMPLATE,
    render_fn: RenderFn = render_cover_letter_pdf,
) -> Path | None:
    """Render a stored cover letter to PDF and persist its path."""
    cover = get_cover_letter(session, cover_letter_id)
    if cover is None:
        return None
    job = get_job(session, cover.job_id)
    content = CoverLetterContent.model_validate(cover.content_json or {})
    company = (job.company if job else None) or "company"
    title = (job.title if job else None) or "role"
    filename = output_filename(company, title, utcnow().strftime("%Y%m%d"), f"cl{cover.id or cover_letter_id}")
    out_path = Path(output_dir) / filename

    render_fn(content, out_path, template_path)

    cover.pdf_path = str(out_path)
    save_cover_letter(session, cover)
    return out_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cover_letter_render.py -v`
Expected: PASS (2 tests — the injected `fake_render` means no Typst binary is exercised).

- [ ] **Step 6: Commit**

```bash
git add templates/cover_letter.typ src/resume_agent/cover_letter/render.py tests/test_cover_letter_render.py
git commit -m "feat(cover-letter): Typst template + render" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `cover-letter` CLI command

**Files:**
- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_cli_cover_letter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_cover_letter.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, make_engine, init_db
from resume_agent.discovery.ingest import add_job
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import CoverLetter, JobStatus

runner = CliRunner()


def test_cover_letter_command_generates_and_renders(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        job.status = JobStatus.approved.value
        save_job(s, job)

    monkeypatch.setattr(cli, "load_facts", lambda path: ProfileFacts(contact=Contact(name="Ada")))
    monkeypatch.setattr(cli, "build_cover_letter_agent", lambda: object())
    monkeypatch.setattr(cli, "build_cover_letter_reviser_agent", lambda: object())
    monkeypatch.setattr(
        cli, "generate_cover_letter",
        lambda session, job, facts, d, r: CoverLetter(id=1, job_id=job.id, fact_check_passed=True),
    )
    monkeypatch.setattr(cli, "render_cover_letter", lambda session, cl_id: Path("output/x.pdf"))

    result = runner.invoke(cli.app, ["cover-letter", "--approved", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "cover letter" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_cover_letter.py -v`
Expected: FAIL — `AttributeError: module 'resume_agent.cli' has no attribute 'generate_cover_letter'`.

- [ ] **Step 3: Add imports**

In `src/resume_agent/cli.py`, add near the tailor imports:
```python
from resume_agent.cover_letter.agents import build_cover_letter_agent, build_cover_letter_reviser_agent
from resume_agent.cover_letter.render import render_cover_letter
from resume_agent.cover_letter.service import generate_cover_letter
```

- [ ] **Step 4: Add the command**

Add after `tailor_cmd` in `src/resume_agent/cli.py`:
```python
@app.command("cover-letter")
def cover_letter_cmd(
    job_id: int = typer.Option(None, help="Write a cover letter for a single job by id."),
    approved: bool = typer.Option(False, "--approved", help="Write cover letters for all approved jobs."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Draft a fact-locked cover letter per job and render it to PDF."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if job_id is not None:
            job = get_job(session, job_id)
            if job is None:
                typer.echo(f"Job #{job_id} not found.")
                raise typer.Exit(code=1)
            targets = [job]
        elif approved:
            targets = jobs_by_status(session, JobStatus.approved.value)
        else:
            typer.echo("Specify --job-id <id> or --approved.")
            raise typer.Exit(code=1)

        profile_facts = load_facts(facts)
        draft_agent = build_cover_letter_agent()
        reviser_agent = build_cover_letter_reviser_agent()

        for job in targets:
            cover = generate_cover_letter(session, job, profile_facts, draft_agent, reviser_agent)
            path = render_cover_letter(session, cover.id)
            typer.echo(
                f"Job #{job.id}: cover letter #{cover.id} "
                f"(fact_check_passed={cover.fact_check_passed}) -> {path}"
            )
```

- [ ] **Step 5: Run test, then the full suite**

Run: `uv run pytest tests/test_cli_cover_letter.py -v`
Expected: PASS (1 test).

Run: `uv run pytest -q`
Expected: ALL pass.

Run: `uv run resume-agent cover-letter --help`
Expected: help text, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_cover_letter.py
git commit -m "feat(cover-letter): cover-letter CLI command" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.4, Decision #6):** `CoverLetterContent` with provenance — Task 1; `cover_letters` table — Task 2; fact-lock via deterministic provenance gate + adversarial "fabricated id blocked" test — Task 3; draft reusing the tailor-agent pattern + reviser — Task 4; light review (gate-only) revise loop + persistence — Task 5; `cover_letter.typ` render — Task 6; `cover-letter` command (`--job-id`/`--approved`) — Task 7.

**Placeholder scan:** none — every model, function, template, and command is complete. The render test injects `fake_render`, so no Typst binary is needed in CI (mirrors the v1 render-service test pattern).

**Type consistency:** `CoverLetterContent`/`CoverLetterParagraph` fields are constructed identically across Tasks 1/3/4/5/6. `collect_fact_ids(facts) -> set[str]` + `unsupported_provenance(content, ids) -> list[str]` match service usage. `draft_cover_letter`/`revise_cover_letter(input, agent) -> CoverLetterContent` match the service. `generate_cover_letter(session, job, facts, draft_agent, reviser_agent, max_rounds=2)` and `render_cover_letter(session, id, ...)` match the CLI calls (patched in the CLI test). `save_cover_letter`/`get_cover_letter` defined in Task 2, used in Tasks 5/6.

**Note:** the gate is intentionally deterministic (provenance existence), not an LLM faithfulness judge — faithfulness of *wording* to the cited fact can be added later as an optional cheap-LLM reviewer, exactly like the resume `fact-check` agent. Flagged, not built (YAGNI).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-agent-v2-cover-letters.md`. Execute via **superpowers:subagent-driven-development** or **superpowers:executing-plans**. Independent of Plans 5/6. Remaining leaves: **Plan 5 (Gmail auto-status)**, **Plan 6 (analytics)**.
