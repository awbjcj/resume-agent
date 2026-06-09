# Resume Agent — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared spine of Resume Agent v1 — dependencies, config loader, the extensible Pydantic domain models, the SQLite (SQLModel) tables, and the DB session — so every later component (profile, discovery, tailor, render, tracking) has typed data structures and persistence to build on.

**Architecture:** A `src/`-layout Python package. Pydantic v2 models define the domain (single source of truth, extensible via `schema_version` + `extra`, provenance via `FactItem.id`). SQLModel tables persist pipeline state with JSON columns so adding fields needs no migration. Config comes from `.env` (secrets) + YAML (behavior).

**Tech Stack:** Python 3.13, uv, Pydantic v2, pydantic-settings, SQLModel (SQLAlchemy), PyYAML, pytest.

> **Commit convention:** every commit in this plan should end its message with the trailer. The commit commands below use a second `-m` paragraph so Git records it as a proper trailer:
> `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Reference

Design spec: `docs/superpowers/specs/2026-06-08-resume-agent-design.md` (see §3 cross-cutting principles, §5.1–5.5 components, §6 layout).

## File Structure (created by this plan)

```
src/resume_agent/
  __init__.py
  config.py                 # Settings (.env) + load_yaml helper
  db.py                     # engine, init_db, get_session
  models/
    __init__.py
    base.py                 # ExtensibleModel, Source, FactItem, new_id
    profile.py              # ProfileFacts + sub-models (the fact-lock)
    job.py                  # JobCriteria + SponsorshipSignal + SalaryRange
    resume.py               # ResumeContent + tailored sub-models (provenance)
    review.py               # ReviewCritique + ReviewIssue + Severity
  tracking/
    __init__.py
    tables.py               # Job, ResumeVersion, Application + status enums
tests/
  test_smoke.py
  test_models_base.py
  test_models_profile.py
  test_models_job.py
  test_models_resume.py
  test_models_review.py
  test_tables.py
  test_db.py
  test_config.py
config/
  search.yaml.example
  review.yaml.example
.env.example
```

Each file has one responsibility. Models are split by domain area (profile / job / resume / review) so each stays small and holdable in context; `base.py` holds shared primitives so the extensibility + provenance rules live in exactly one place.

---

## Task 1: Project setup & dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `src/resume_agent/__init__.py`
- Delete: `main.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Add runtime dependencies**

Run:
```bash
uv add pydantic pydantic-settings sqlmodel pyyaml
```
Expected: `pyproject.toml` `dependencies` now lists pydantic, pydantic-settings, sqlmodel, pyyaml; a `uv.lock` is created.

- [ ] **Step 2: Add the dev dependency**

Run:
```bash
uv add --dev pytest
```
Expected: pytest appears under `[dependency-groups] dev` (or `[tool.uv] dev-dependencies`).

- [ ] **Step 3: Make the project an installable src-layout package**

Edit `pyproject.toml` — update the project metadata and append the build + pytest config blocks. Do not replace or remove the `dependencies` array or dev dependency group that `uv add` wrote; versions may differ from the example below.

```toml
[project]
name = "resume-agent"
version = "0.1.0"
description = "Personal AI job-hunt, resume-tailoring, and application-tracking pipeline"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2",
    "pydantic-settings>=2",
    "pyyaml>=6",
    "sqlmodel>=0.0.27",
]

[dependency-groups]
dev = [
    "pytest>=8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/resume_agent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Create the package and remove the uv stub**

Create `src/resume_agent/__init__.py`:
```python
"""Resume Agent — personal job-hunt automation pipeline."""

__version__ = "0.1.0"
```

Delete the hello-world stub:
```bash
git rm main.py
```

- [ ] **Step 5: Write the smoke test**

Create `tests/test_smoke.py`:
```python
def test_package_imports():
    import resume_agent

    assert resume_agent.__version__ == "0.1.0"
```

- [ ] **Step 6: Run it (it should pass once the package installs)**

Run:
```bash
uv run pytest tests/test_smoke.py -v
```
Expected: PASS. (`uv run` syncs the project into the venv in editable mode, making `resume_agent` importable.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/resume_agent/__init__.py tests/test_smoke.py
git commit -m "chore: src-layout package scaffold + foundation deps" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Base model primitives

**Files:**
- Create: `src/resume_agent/models/__init__.py`
- Create: `src/resume_agent/models/base.py`
- Test: `tests/test_models_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_base.py`:
```python
from resume_agent.models.base import ExtensibleModel, FactItem, Source, new_id


def test_new_id_is_unique_and_short():
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12


def test_extensible_model_defaults():
    m = ExtensibleModel()
    assert m.schema_version == 1
    assert m.extra == {}


def test_extensible_model_preserves_unknown_keys():
    # Forward-compat: unknown keys are preserved (not dropped) so a load->save
    # round-trip of newer JSON doesn't lose data the model doesn't model yet.
    m = ExtensibleModel.model_validate({"future_field": 123})
    assert m.model_dump()["future_field"] == 123
    restored = ExtensibleModel.model_validate_json(m.model_dump_json())
    assert restored.model_dump()["future_field"] == 123


def test_fact_item_has_auto_id_and_default_source():
    f1, f2 = FactItem(), FactItem()
    assert f1.id != f2.id
    assert f1.source == Source.resume


def test_fact_item_source_round_trips():
    f = FactItem(source="github")
    assert f.source == Source.github
    assert f.model_dump(mode="json")["source"] == "github"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_models_base.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/models/__init__.py`:
```python
"""Domain models for Resume Agent."""
```

Create `src/resume_agent/models/base.py`:
```python
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Source(str, Enum):
    """Where an atomic fact originated."""

    resume = "resume"
    github = "github"
    manual = "manual"


def new_id() -> str:
    """Stable, short identifier used for provenance pointers."""
    return uuid.uuid4().hex[:12]


class ExtensibleModel(BaseModel):
    """Base for all domain models.

    - ``schema_version`` enables explicit future migrations.
    - ``extra`` is the escape hatch for experimental fields before they are
      promoted to first-class.
    - ``extra="allow"`` preserves unknown keys so a load->save round-trip of
      newer JSON doesn't silently drop fields the model doesn't know yet.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    extra: dict[str, Any] = Field(default_factory=dict)


class FactItem(ExtensibleModel):
    """An atomic fact carrying provenance: a stable id + where it came from."""

    id: str = Field(default_factory=new_id)
    source: Source = Source.resume
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_models_base.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/__init__.py src/resume_agent/models/base.py tests/test_models_base.py
git commit -m "feat(models): extensible base model + provenance fact item" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Profile models (the fact-lock)

**Files:**
- Create: `src/resume_agent/models/profile.py`
- Test: `tests/test_models_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_profile.py`:
```python
from resume_agent.models.profile import (
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Project,
    Skill,
)


def make_minimal_profile() -> ProfileFacts:
    return ProfileFacts(contact=Contact(name="Ada Lovelace"))


def test_minimal_profile_only_needs_contact_name():
    p = make_minimal_profile()
    assert p.contact.name == "Ada Lovelace"
    assert p.experience == []
    assert p.skills == {}


def test_experience_bullets_get_provenance_ids():
    exp = Experience(
        company="Analytical Engines Ltd",
        title="Engineer",
        bullets=[{"text": "Wrote the first algorithm"}],
    )
    assert exp.id  # experience itself has an id
    assert exp.bullets[0].id  # each bullet has an id
    assert exp.bullets[0].text == "Wrote the first algorithm"


def test_skills_is_an_open_ended_category_map():
    p = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "languages": [{"name": "Python"}],
            "cloud": [Skill(name="AWS"), {"name": "GCP", "source": "manual"}],
        },
    )
    assert [skill.name for skill in p.skills["cloud"]] == ["AWS", "GCP"]
    assert p.skills["cloud"][0].id
    assert p.skills["cloud"][1].source.value == "manual"


def test_github_project_and_profile_signals_are_modeled():
    proj = Project(
        name="repo",
        source="github",
        repo_url="https://github.com/x/repo",
        stars=10,
        languages=["Python"],
        topics=["llm"],
        is_fork=False,
    )
    profile = GitHubProfile(
        username="ada",
        followers=42,
        top_languages=["Python"],
        total_stars=10,
    )
    assert proj.source.value == "github"
    assert proj.stars == 10
    assert profile.source.value == "github"
    assert profile.total_stars == 10


def test_profile_round_trips_through_json():
    p = make_minimal_profile()
    restored = ProfileFacts.model_validate_json(p.model_dump_json())
    assert restored.contact.name == "Ada Lovelace"
    assert restored.schema_version == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_models_profile.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models.profile'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/models/profile.py`:
```python
from pydantic import Field

from resume_agent.models.base import ExtensibleModel, FactItem, Source


class Link(ExtensibleModel):
    label: str
    url: str


class Contact(ExtensibleModel):
    name: str
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    willing_to_relocate: bool = False
    work_authorization: str | None = None  # e.g. "needs H-1B sponsorship"
    links: list[Link] = Field(default_factory=list)


class Bullet(FactItem):
    text: str


class Skill(FactItem):
    name: str
    aliases: list[str] = Field(default_factory=list)
    context: str | None = None


class Experience(FactItem):
    company: str
    title: str
    employment_type: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None  # None = current role
    current: bool = False
    bullets: list[Bullet] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)


class Education(FactItem):
    institution: str
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    gpa: str | None = None
    honors: list[str] = Field(default_factory=list)
    relevant_coursework: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)


class Project(FactItem):
    name: str
    description: str | None = None
    role: str | None = None
    tech: list[str] = Field(default_factory=list)
    url: str | None = None
    repo_url: str | None = None
    highlights: list[str] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    stars: int | None = None
    forks: int | None = None
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    homepage_url: str | None = None
    last_updated: str | None = None
    is_fork: bool | None = None


class Certification(FactItem):
    name: str
    issuer: str | None = None
    date: str | None = None
    credential_id: str | None = None
    url: str | None = None


class Publication(FactItem):
    title: str
    venue: str | None = None
    date: str | None = None
    authors: list[str] = Field(default_factory=list)
    url: str | None = None


class Award(FactItem):
    name: str
    issuer: str | None = None
    date: str | None = None
    description: str | None = None


class Language(FactItem):
    language: str
    proficiency: str | None = None


class Volunteer(FactItem):
    organization: str
    role: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None


class GitHubProfile(FactItem):
    source: Source = Source.github
    username: str | None = None
    bio: str | None = None
    followers: int | None = None
    public_repos: int | None = None
    account_created_at: str | None = None
    top_languages: list[str] = Field(default_factory=list)
    total_stars: int | None = None


class ProfileFacts(ExtensibleModel):
    """The fact-lock: the ONLY facts any tailoring is allowed to draw from."""

    contact: Contact
    summary: str | None = None
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: dict[str, list[Skill]] = Field(default_factory=dict)
    certifications: list[Certification] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    volunteer: list[Volunteer] = Field(default_factory=list)
    github_profile: GitHubProfile | None = None
    interests: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_models_profile.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/profile.py tests/test_models_profile.py
git commit -m "feat(models): comprehensive ProfileFacts fact-lock schema" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Job model

**Files:**
- Create: `src/resume_agent/models/job.py`
- Test: `tests/test_models_job.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_job.py`:
```python
from resume_agent.models.job import JobCriteria, SalaryRange, SponsorshipSignal


def test_sponsorship_defaults_to_silent():
    c = JobCriteria()
    assert c.sponsorship_signal == SponsorshipSignal.silent


def test_full_criteria_round_trips():
    c = JobCriteria(
        sponsorship_signal="offered",
        yoe_min=3,
        salary_range=SalaryRange(minimum=120000, maximum=160000),
        remote_policy="hybrid",
        location="Seattle, WA",
        must_have_skills=["Python", "AWS"],
    )
    dumped = c.model_dump(mode="json")
    restored = JobCriteria.model_validate(dumped)
    assert restored.sponsorship_signal == SponsorshipSignal.offered
    assert restored.salary_range.minimum == 120000
    assert restored.must_have_skills == ["Python", "AWS"]


def test_salary_range_defaults():
    s = SalaryRange(minimum=100000)
    assert s.currency == "USD"
    assert s.period == "year"
    assert s.maximum is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_models_job.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models.job'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/models/job.py`:
```python
from enum import Enum

from pydantic import Field

from resume_agent.models.base import ExtensibleModel


class SponsorshipSignal(str, Enum):
    """What the JD says about visa sponsorship. ``silent`` => uncertain (keep + flag)."""

    offered = "offered"
    denied = "denied"
    silent = "silent"


class SalaryRange(ExtensibleModel):
    minimum: int | None = None
    maximum: int | None = None
    currency: str = "USD"
    period: str = "year"  # year | month | hour


class JobCriteria(ExtensibleModel):
    """Structured fields extracted from a raw job description."""

    sponsorship_signal: SponsorshipSignal = SponsorshipSignal.silent
    yoe_min: int | None = None
    salary_range: SalaryRange | None = None
    remote_policy: str | None = None  # remote | hybrid | onsite
    location: str | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_models_job.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/job.py tests/test_models_job.py
git commit -m "feat(models): JobCriteria extraction schema" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Resume content model (tailored output with provenance)

**Files:**
- Create: `src/resume_agent/models/resume.py`
- Test: `tests/test_models_resume.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_resume.py`:
```python
import pytest
from pydantic import ValidationError

from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)


def test_tailored_bullet_requires_provenance():
    b = TailoredBullet(text="Built X", provenance="abc123def456")
    assert b.provenance == "abc123def456"


def test_tailored_bullet_provenance_is_mandatory():
    with pytest.raises(ValidationError):
        TailoredBullet(text="Built X")  # no provenance -> fabrication risk


def test_tailored_skill_requires_provenance():
    skill = TailoredSkill(name="Python", provenance="skill0000001")
    assert skill.name == "Python"
    assert skill.provenance == "skill0000001"


def test_resume_content_assembles_from_facts_contact():
    rc = ResumeContent(
        contact=Contact(name="Ada Lovelace"),
        summary="Engineer",
        experience=[
            TailoredExperience(
                company="Analytical Engines Ltd",
                title="Engineer",
                provenance="exp000000001",
                bullets=[TailoredBullet(text="Wrote the first algorithm", provenance="bul000000001")],
            )
        ],
    )
    assert rc.contact.name == "Ada Lovelace"
    assert rc.experience[0].bullets[0].provenance == "bul000000001"


def test_resume_content_round_trips_json():
    rc = ResumeContent(contact=Contact(name="Ada"))
    restored = ResumeContent.model_validate_json(rc.model_dump_json())
    assert restored.contact.name == "Ada"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_models_resume.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models.resume'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/models/resume.py`:
```python
from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import Contact, Education


class TailoredBullet(ExtensibleModel):
    """A resume bullet. ``provenance`` MUST point to a ProfileFacts fact id."""

    text: str
    provenance: str  # id of the source Bullet/Experience/Project in ProfileFacts


class TailoredSkill(ExtensibleModel):
    """A selected skill. ``provenance`` MUST point to a ProfileFacts Skill id."""

    name: str
    provenance: str
    context: str | None = None


class TailoredExperience(ExtensibleModel):
    company: str
    title: str
    location: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Experience


class TailoredProject(ExtensibleModel):
    name: str
    description: str | None = None
    tech: list[str] = Field(default_factory=list)
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Project


class ResumeContent(ExtensibleModel):
    """Structured, fact-locked resume content. The renderer turns this into a PDF;
    the LLM never emits markup."""

    contact: Contact  # carried verbatim from ProfileFacts (no invention)
    summary: str | None = None
    experience: list[TailoredExperience] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    skills: dict[str, list[TailoredSkill]] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list)  # carried verbatim
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_models_resume.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/resume.py tests/test_models_resume.py
git commit -m "feat(models): ResumeContent with mandatory provenance" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Review model

**Files:**
- Create: `src/resume_agent/models/review.py`
- Test: `tests/test_models_review.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_review.py`:
```python
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity


def test_blocking_issue_severity():
    issue = ReviewIssue(severity="blocking", message="Claim X not in ProfileFacts")
    assert issue.severity == Severity.blocking


def test_critique_defaults_to_no_issues():
    c = ReviewCritique(reviewer="fact-check", score=100, passed=True)
    assert c.issues == []
    assert c.passed is True


def test_critique_round_trips():
    c = ReviewCritique(
        reviewer="ats-keyword",
        score=70,
        passed=False,
        issues=[ReviewIssue(severity="major", message="Missing keyword: Kubernetes",
                            suggestion="Add it if truthfully supported")],
        suggestions=[
            "Only add Kubernetes if a ProfileFacts skill or project supports it",
        ],
    )
    restored = ReviewCritique.model_validate(c.model_dump(mode="json"))
    assert restored.issues[0].severity == Severity.major
    assert restored.score == 70
    assert restored.suggestions == [
        "Only add Kubernetes if a ProfileFacts skill or project supports it",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_models_review.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.models.review'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/models/review.py`:
```python
from enum import Enum

from pydantic import Field

from resume_agent.models.base import ExtensibleModel


class Severity(str, Enum):
    blocking = "blocking"  # fact-check failures use this; gates the whole round
    major = "major"
    minor = "minor"


class ReviewIssue(ExtensibleModel):
    severity: Severity
    message: str
    suggestion: str | None = None
    location: str | None = None  # which section/bullet the issue refers to


class ReviewCritique(ExtensibleModel):
    """One reviewer agent's structured verdict on a ResumeContent draft."""

    reviewer: str  # the reviewing agent's name
    score: int = Field(ge=0, le=100)
    passed: bool  # the reviewer's pass/fail; fact-check's value is the hard gate
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_models_review.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/review.py tests/test_models_review.py
git commit -m "feat(models): ReviewCritique schema for the Agno review panel" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: SQLModel tables

**Files:**
- Create: `src/resume_agent/tracking/__init__.py`
- Create: `src/resume_agent/tracking/tables.py`
- Test: `tests/test_tables.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tables.py`:
```python
from sqlmodel import Session, SQLModel, create_engine, select

from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    ResumeVersion,
)


def _memory_engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_table_names_match_design_spec():
    assert Job.__tablename__ == "jobs"
    assert ResumeVersion.__tablename__ == "resume_versions"
    assert Application.__tablename__ == "applications"


def test_job_defaults_and_json_column_round_trip():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(
            source="linkedin",
            jd_text="We need a Python engineer",
            criteria_json={"sponsorship_signal": "silent", "must_have_skills": ["Python"]},
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.id is not None
        assert job.status == JobStatus.raw.value
        assert job.criteria_json["must_have_skills"] == ["Python"]
        assert job.created_at is not None


def test_resume_version_links_to_job_and_stores_critiques():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(source="linkedin", jd_text="jd")
        s.add(job)
        s.commit()
        s.refresh(job)
        rv = ResumeVersion(
            job_id=job.id,
            round=1,
            content_json={"contact": {"name": "Ada"}},
            critique_json=[{"reviewer": "fact-check", "score": 100, "passed": True}],
            fact_check_passed=True,
            review_score=88,
        )
        s.add(rv)
        s.commit()
        s.refresh(rv)
        assert rv.job_id == job.id
        assert rv.critique_json[0]["reviewer"] == "fact-check"


def test_application_status_default_is_ready():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(source="linkedin", jd_text="jd")
        s.add(job)
        s.commit()
        s.refresh(job)
        app = Application(job_id=job.id)
        s.add(app)
        s.commit()
        s.refresh(app)
        assert app.status == ApplicationStatus.ready.value

        rows = s.exec(select(Application).where(Application.job_id == job.id)).all()
        assert len(rows) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_tables.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/tracking/__init__.py`:
```python
"""Persistence layer for Resume Agent."""
```

Create `src/resume_agent/tracking/tables.py`:
```python
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    """Our processing pipeline status for a job."""

    raw = "raw"
    extracted = "extracted"
    filtered = "filtered"
    rejected = "rejected"
    shortlisted = "shortlisted"
    approved = "approved"
    tailored = "tailored"
    rendered = "rendered"


class ApplicationStatus(str, Enum):
    """The employer-side funnel status for a submitted application."""

    ready = "ready"
    submitted = "submitted"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    closed = "closed"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    source: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    jd_text: str = ""
    criteria_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str = Field(default=JobStatus.raw.value, index=True)
    reject_reason: str | None = None
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class ResumeVersion(SQLModel, table=True):
    __tablename__ = "resume_versions"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    round: int = 0
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    pdf_path: str | None = None
    review_score: int | None = None
    fact_check_passed: bool = False
    critique_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    __tablename__ = "applications"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    status: str = Field(default=ApplicationStatus.ready.value, index=True)
    submitted_at: datetime | None = None
    notes: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_tables.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/__init__.py src/resume_agent/tracking/tables.py tests/test_tables.py
git commit -m "feat(tracking): SQLModel tables with JSON columns + status enums" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Config loader

**Files:**
- Create: `src/resume_agent/config.py`
- Create: `.env.example`
- Create: `config/search.yaml.example`
- Create: `config/review.yaml.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:
```python
import pytest

from resume_agent.config import Settings, load_yaml


def clear_settings_env(monkeypatch):
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "LINKEDIN_EMAIL",
        "LINKEDIN_PASSWORD",
        "DB_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_reads_env_file(tmp_path, monkeypatch):
    clear_settings_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-test\nGITHUB_TOKEN=ghp-test\n", encoding="utf-8")
    settings = Settings(_env_file=str(env))
    assert settings.anthropic_api_key == "sk-test"
    assert settings.github_token == "ghp-test"


def test_settings_have_safe_defaults(monkeypatch):
    clear_settings_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key == ""
    assert settings.db_url.startswith("sqlite:///")


def test_load_yaml_parses_mapping(tmp_path):
    f = tmp_path / "search.yaml"
    f.write_text("keywords:\n  - python\n  - backend\nsponsorship_required: true\n", encoding="utf-8")
    data = load_yaml(f)
    assert data["keywords"] == ["python", "backend"]
    assert data["sponsorship_required"] is True


def test_load_yaml_rejects_non_mapping(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_yaml(f)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.config'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/config.py`:
```python
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and environment-level config, loaded from ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    github_token: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    db_url: str = "sqlite:///data/resume_agent.db"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor used across the app."""
    return Settings()


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file, requiring a mapping at the top level."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at the top of {p}, got {type(data).__name__}")
    return data
```

Create `.env.example`:
```bash
# Copy to .env and fill in. .env is git-ignored.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GITHUB_TOKEN=
# Burner LinkedIn account used for scraping (see design spec §5.2)
LINKEDIN_EMAIL=
LINKEDIN_PASSWORD=
DB_URL=sqlite:///data/resume_agent.db
```

Create `config/search.yaml.example`:
```yaml
# Discovery criteria + hard-filter rules (see design spec §5.2).
keywords:
  - python
  - backend engineer
titles:
  - Software Engineer
  - Backend Engineer
locations:
  - Remote
  - Seattle, WA
remote_policy: remote        # remote | hybrid | onsite | any
min_salary: 120000
yoe_min: 0
yoe_max: 5
sponsorship_required: true   # silent postings are kept + flagged, not rejected
```

Create `config/review.yaml.example`:
```yaml
# Reviewer roster, weights, and loop controls (see design spec §5.3).
max_rounds: 3
score_threshold: 85
reviewers:
  - name: fact-check
    gate: true            # blocking: any unsupported claim fails the round
    weight: 0
    model_tier: premium
  - name: ats-keyword
    gate: false
    weight: 1
    model_tier: mid
  - name: recruiter
    gate: false
    weight: 1
    model_tier: mid
  - name: hiring-manager
    gate: false
    weight: 1
    model_tier: premium
  - name: concision
    gate: false
    weight: 1
    model_tier: mid
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_config.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py .env.example config/search.yaml.example config/review.yaml.example tests/test_config.py
git commit -m "feat(config): settings loader + example env/yaml configs" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: DB engine & session

**Files:**
- Create: `src/resume_agent/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:
```python
from sqlmodel import select

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.tables import Job


def test_make_engine_creates_sqlite_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    assert db_path.parent.exists()


def test_init_db_creates_tables_and_session_round_trips(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)

    with get_session(engine) as session:
        session.add(Job(source="linkedin", jd_text="hello"))
        session.commit()

    with get_session(engine) as session:
        jobs = session.exec(select(Job)).all()
        assert len(jobs) == 1
        assert jobs[0].source == "linkedin"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_db.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.db'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/db.py`:
```python
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.config import get_settings

# Import tables so their metadata is registered before create_all().
from resume_agent.tracking import tables  # noqa: F401


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a sqlite file URL if needed."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = url[len(prefix):]
        if db_path and db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str | None = None) -> Engine:
    resolved = url or get_settings().db_url
    _ensure_sqlite_dir(resolved)
    return create_engine(resolved, echo=False)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session(engine: Engine) -> Session:
    return Session(engine)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_db.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite**

Run:
```bash
uv run pytest -v
```
Expected: PASS — all tests across Tasks 1–9 green.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/db.py tests/test_db.py
git commit -m "feat(db): engine factory, init_db, and session helper" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage:** §3.1 fact-lock/provenance → `FactItem.id` (Task 2), provenance-bearing `Skill` facts (Task 3), mandatory `TailoredBullet.provenance` and `TailoredSkill.provenance` (Task 5). §3.2 extensibility → `ExtensibleModel` (`schema_version` + `extra` + `extra="allow"`, Task 2), JSON columns (Task 7). §5.1 ProfileFacts + GitHub repository/profile fields (Task 3). §5.2 `JobCriteria` + `SponsorshipSignal.silent` default (Task 4) and `config/search.yaml` (Task 8). §5.3 `ReviewCritique` with `issues[]` and `suggestions[]` (Task 6) + `config/review.yaml` roster/weights/`max_rounds` (Task 8). §5.5 three explicit plural tables + two status lifecycles (Task 7). §6 layout + config (Tasks 1, 8). Components profile/discovery/tailor/render/dashboard logic are **out of scope for Foundation** and covered by their own forthcoming plans.
- **Placeholder scan:** none — every step has complete code and exact commands.
- **Type consistency:** `ResumeContent` reuses `Contact`/`Education` from `profile.py`; `ResumeContent.skills` stores provenance-bearing `TailoredSkill` items that point back to `ProfileFacts.skills`; `ResumeVersion.critique_json` stores a list of `ReviewCritique`-shaped dicts (Task 6 ↔ Task 7); FKs use the explicit plural table names from the design spec (`jobs.id`, `resume_versions.id`); `JobStatus.raw`/`ApplicationStatus.ready` defaults used consistently in tables and tests.

---

## Execution Handoff

Foundation plan complete. After this plan is executed and green, the next plan to write is **Profile** (resume parse + GitHub ingest → `facts.json`).
