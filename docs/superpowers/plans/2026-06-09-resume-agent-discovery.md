# Résumé Tailor Harness — Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Discovery funnel — turn raw job postings into a ranked **shortlist** in SQLite — plus a `resume-tailor-harness discover` command and a `resume-tailor-harness addjob` manual-entry fallback. The live LinkedIn Playwright scraper is intentionally **out of scope** here (its selectors must be calibrated against the live site) and becomes its own follow-up plan; this plan makes the entire pipeline usable today via `addjob`.

**Architecture:** SQLite `jobs` rows flow through statuses `raw → extracted → filtered|rejected → shortlisted`, one stage at a time (resumable). Deterministic stages (ingest/dedupe, hard filter) and the two cheap-LLM stages (extract → `JobCriteria`, fit-score → `FitScore`) are each pure/injected functions, tested with in-memory SQLite + fake agents — no network or API key in tests.

**Tech Stack:** Python 3.13, uv, SQLModel, Pydantic v2, Agno (`Agent` + `Claude`), Typer, pytest. (No new dependencies — Playwright arrives with the scraper plan.)

**Depends on:** Foundation (`tracking.tables`, `models.job`, `models.profile`, `config`, `db`) and Profile (`profile.store.load_facts`, `config.cheap_model`, the Agno extractor pattern) — both merged to `main`, suite green (54 tests).

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec §5.2. Decisions for this plan:

- **Scraper deferred.** This plan delivers the funnel + `addjob`. The LinkedIn Playwright scraper (and `playwright` dependency) is a separate plan calibrated against live HTML.
- **Sponsorship rule** (spec Decision #5): with `sponsorship_required: true`, `denied` → reject, `silent` → **keep** (uncertainty is conveyed by the persisted `sponsorship_signal=silent` in `criteria_json`; the shortlist UI surfaces it), `offered` → keep.
- **Repository lives in `tracking/`** (`tracking/repository.py`) — it's the shared persistence layer; the Tracking component plan will extend it for `applications`/`resume_versions`.
- **Rejected jobs are kept** with a `reject_reason` (auditing / filter calibration), per spec.

## File Structure (created/modified)

```
src/resume_tailor_harness/
  cli.py                       # MODIFY: add `discover` and `addjob` commands
  tracking/
    repository.py              # CREATE: Job persistence (save/query/dedupe/counts)
  discovery/
    __init__.py                # CREATE
    search_config.py           # CREATE: SearchConfig + load_search_config()
    ingest.py                  # CREATE: add_job() (normalize + dedupe + insert raw)
    extract.py                 # CREATE: Agno agent -> JobCriteria + wrapper
    filter.py                  # CREATE: FilterDecision + apply_filters()
    fit.py                     # CREATE: FitScore + agent + compose_fit_input()/score_fit()
    pipeline.py                # CREATE: run_extract/run_filter/run_score + discover()
tests/
  test_repository.py
  test_discovery_search_config.py
  test_discovery_ingest.py
  test_discovery_extract.py
  test_discovery_filter.py
  test_discovery_fit.py
  test_discovery_pipeline.py
  test_cli_discovery.py
```

---

## Task 1: Discovery scaffold + SearchConfig

**Files:**

- Create: `src/resume_tailor_harness/discovery/__init__.py`, `src/resume_tailor_harness/discovery/search_config.py`
- Test: `tests/test_discovery_search_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_search_config.py`:

```python
from resume_tailor_harness.discovery.search_config import SearchConfig, load_search_config


def test_defaults_are_empty():
    cfg = SearchConfig()
    assert cfg.keywords == []
    assert cfg.sponsorship_required is False
    assert cfg.min_salary is None


def test_load_from_yaml(tmp_path):
    f = tmp_path / "search.yaml"
    f.write_text(
        "keywords:\n  - python\ntitles:\n  - Engineer\n"
        "min_salary: 120000\nyoe_max: 5\nsponsorship_required: true\n",
        encoding="utf-8",
    )
    cfg = load_search_config(f)
    assert cfg.keywords == ["python"]
    assert cfg.min_salary == 120000
    assert cfg.yoe_max == 5
    assert cfg.sponsorship_required is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_search_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/__init__.py`:

```python
"""Discovery component: fetch/ingest jobs and funnel them to a shortlist."""
```

Create `src/resume_tailor_harness/discovery/search_config.py`:

```python
from pathlib import Path

from pydantic import Field

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel


class SearchConfig(ExtensibleModel):
    """Discovery criteria + hard-filter thresholds (from config/search.yaml)."""

    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: str | None = None
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False


def load_search_config(path: str | Path) -> SearchConfig:
    return SearchConfig.model_validate(load_yaml(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_search_config.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/__init__.py src/resume_tailor_harness/discovery/search_config.py tests/test_discovery_search_config.py
git commit -m "feat(discovery): SearchConfig + loader" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Jobs repository

**Files:**

- Create: `src/resume_tailor_harness/tracking/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_repository.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.tracking.repository import (
    find_existing,
    jobs_by_status,
    save_job,
    status_counts,
)
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_save_and_query_by_status():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="manual", jd_text="b", status=JobStatus.shortlisted.value))
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert len(raw) == 1
        assert raw[0].jd_text == "a"


def test_find_existing_by_url_then_jd_text():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="hello", url="http://x/1"))
        assert find_existing(s, "http://x/1", "different") is not None  # url match
        assert find_existing(s, None, "hello") is not None             # jd_text match
        assert find_existing(s, "http://x/2", "nope") is None


def test_status_counts():
    with _session() as s:
        save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="c", status=JobStatus.shortlisted.value))
        counts = status_counts(s)
        assert counts[JobStatus.raw.value] == 2
        assert counts[JobStatus.shortlisted.value] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_repository.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.tracking.repository'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/tracking/repository.py`:

```python
from sqlalchemy import func
from sqlmodel import Session, select

from resume_tailor_harness.tracking.tables import Job


def save_job(session: Session, job: Job) -> Job:
    """Insert or update a job (SQLModel ``add`` handles both)."""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def jobs_by_status(session: Session, status: str) -> list[Job]:
    return list(session.exec(select(Job).where(Job.status == status)).all())


def find_existing(session: Session, url: str | None, jd_text: str) -> Job | None:
    """Return a matching job by URL (if given) else by identical JD text, for dedupe."""
    if url:
        by_url = session.exec(select(Job).where(Job.url == url)).first()
        if by_url is not None:
            return by_url
    return session.exec(select(Job).where(Job.jd_text == jd_text)).first()


def status_counts(session: Session) -> dict[str, int]:
    rows = session.exec(select(Job.status, func.count()).group_by(Job.status)).all()
    return {status: count for status, count in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_repository.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/repository.py tests/test_repository.py
git commit -m "feat(tracking): jobs repository (save/query/dedupe/counts)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Ingest (normalize + dedupe + insert raw)

**Files:**

- Create: `src/resume_tailor_harness/discovery/ingest.py`
- Test: `tests/test_discovery_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_ingest.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_add_job_inserts_raw_and_strips_fields():
    with _session() as s:
        job = add_job(s, source="manual", jd_text="  hello  ", company="  Acme ", title=" Eng ")
        assert job is not None
        assert job.status == JobStatus.raw.value
        assert job.jd_text == "hello"
        assert job.company == "Acme"
        assert job.title == "Eng"


def test_add_job_dedupes_identical_jd():
    with _session() as s:
        first = add_job(s, source="manual", jd_text="same text")
        dup = add_job(s, source="manual", jd_text="same text")
        assert first is not None
        assert dup is None


def test_add_job_dedupes_by_url():
    with _session() as s:
        add_job(s, source="manual", jd_text="a", url="http://x/1")
        dup = add_job(s, source="manual", jd_text="b", url="http://x/1")
        assert dup is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_ingest.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.ingest'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/ingest.py`:

```python
from sqlmodel import Session

from resume_tailor_harness.tracking.repository import find_existing, save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def add_job(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
) -> Job | None:
    """Normalize, dedupe, and insert a raw job. Returns None if a duplicate exists."""
    jd_text = jd_text.strip()
    url = _clean(url)
    if find_existing(session, url, jd_text) is not None:
        return None
    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=_clean(company),
        title=_clean(title),
        location=_clean(location),
        status=JobStatus.raw.value,
    )
    return save_job(session, job)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_ingest.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/ingest.py tests/test_discovery_ingest.py
git commit -m "feat(discovery): add_job ingest with normalize + dedupe" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Extract (Agno agent → JobCriteria)

**Files:**

- Create: `src/resume_tailor_harness/discovery/extract.py`
- Test: `tests/test_discovery_extract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_extract.py`:

```python
import pytest

from agno.agent import Agent

from resume_tailor_harness.models.job import JobCriteria, SponsorshipSignal
from resume_tailor_harness.discovery.extract import build_extract_agent, extract_job_criteria


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _FakeResult(self._content)


def test_extract_returns_criteria_and_passes_text():
    criteria = JobCriteria(sponsorship_signal=SponsorshipSignal.offered)
    agent = _FakeAgent(criteria)
    out = extract_job_criteria("jd text", agent)
    assert out is criteria
    assert agent.received == "jd text"


def test_extract_rejects_wrong_type():
    with pytest.raises(TypeError):
        extract_job_criteria("x", _FakeAgent("nope"))


def test_build_extract_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_extract_agent(model_id="claude-haiku-4-5-20251001"), Agent)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_extract.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.extract'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/extract.py`:

```python
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.models.job import JobCriteria


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Extract structured hiring criteria from the job description text.",
    "Infer the sponsorship signal: 'offered', 'denied', or 'silent' when the text says nothing.",
    "Use only what the text supports; leave unknown fields null.",
]


def build_extract_agent(model_id: str | None = None) -> Agent:
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You extract structured hiring criteria from job descriptions.",
        instructions=_INSTRUCTIONS,
        output_schema=JobCriteria,
    )


def extract_job_criteria(jd_text: str, agent: Runner) -> JobCriteria:
    result = agent.run(jd_text)
    criteria = result.content
    if not isinstance(criteria, JobCriteria):
        raise TypeError(f"Expected JobCriteria from agent, got {type(criteria).__name__}")
    return criteria
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_extract.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/extract.py tests/test_discovery_extract.py
git commit -m "feat(discovery): Agno extractor -> JobCriteria" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Hard filter

**Files:**

- Create: `src/resume_tailor_harness/discovery/filter.py`
- Test: `tests/test_discovery_filter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_filter.py`:

```python
from resume_tailor_harness.discovery.filter import FilterDecision, apply_filters
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.models.job import JobCriteria, SalaryRange, SponsorshipSignal


def test_sponsorship_denied_is_rejected():
    cfg = SearchConfig(sponsorship_required=True)
    decision = apply_filters(JobCriteria(sponsorship_signal=SponsorshipSignal.denied), cfg)
    assert decision.keep is False
    assert "sponsorship" in decision.reject_reason


def test_sponsorship_silent_is_kept_and_flagged():
    cfg = SearchConfig(sponsorship_required=True)
    decision = apply_filters(JobCriteria(sponsorship_signal=SponsorshipSignal.silent), cfg)
    assert decision.keep is True
    assert "sponsorship_uncertain" in decision.flags


def test_salary_below_minimum_is_rejected():
    cfg = SearchConfig(min_salary=120000)
    criteria = JobCriteria(salary_range=SalaryRange(minimum=80000, maximum=100000))
    decision = apply_filters(criteria, cfg)
    assert decision.keep is False
    assert "salary" in decision.reject_reason


def test_too_much_experience_required_is_rejected():
    cfg = SearchConfig(yoe_max=5)
    decision = apply_filters(JobCriteria(yoe_min=8), cfg)
    assert decision.keep is False
    assert "experience" in decision.reject_reason


def test_clean_match_is_kept():
    cfg = SearchConfig(sponsorship_required=True, min_salary=100000, yoe_max=5)
    criteria = JobCriteria(
        sponsorship_signal=SponsorshipSignal.offered,
        salary_range=SalaryRange(minimum=120000, maximum=160000),
        yoe_min=3,
    )
    decision = apply_filters(criteria, cfg)
    assert decision.keep is True
    assert decision.reject_reason is None
    assert decision.flags == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_filter.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.filter'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/filter.py`:

```python
from pydantic import Field

from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.job import JobCriteria, SponsorshipSignal


class FilterDecision(ExtensibleModel):
    keep: bool
    reject_reason: str | None = None
    flags: list[str] = Field(default_factory=list)


def apply_filters(criteria: JobCriteria, config: SearchConfig) -> FilterDecision:
    """Deterministic hard filter. Sponsorship 'silent' is kept but flagged."""
    flags: list[str] = []

    if config.sponsorship_required:
        if criteria.sponsorship_signal == SponsorshipSignal.denied:
            return FilterDecision(keep=False, reject_reason="sponsorship not available")
        if criteria.sponsorship_signal == SponsorshipSignal.silent:
            flags.append("sponsorship_uncertain")

    if (
        config.min_salary is not None
        and criteria.salary_range is not None
        and criteria.salary_range.maximum is not None
        and criteria.salary_range.maximum < config.min_salary
    ):
        return FilterDecision(keep=False, reject_reason="salary below minimum")

    if (
        config.yoe_max is not None
        and criteria.yoe_min is not None
        and criteria.yoe_min > config.yoe_max
    ):
        return FilterDecision(keep=False, reject_reason="requires more experience than yoe_max")

    return FilterDecision(keep=True, flags=flags)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_filter.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/filter.py tests/test_discovery_filter.py
git commit -m "feat(discovery): deterministic hard filter" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Fit-score (Agno agent → FitScore)

**Files:**

- Create: `src/resume_tailor_harness/discovery/fit.py`
- Test: `tests/test_discovery_fit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_fit.py`:

```python
import pytest
from pydantic import ValidationError

from agno.agent import Agent

from resume_tailor_harness.discovery.fit import FitScore, build_fit_agent, compose_fit_input, score_fit
from resume_tailor_harness.models.profile import Contact, ProfileFacts


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)


def test_compose_includes_profile_and_jd():
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    text = compose_fit_input("Backend role", facts)
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_score_fit_returns_fitscore():
    fit = FitScore(score=82, rationale="strong overlap")
    out = score_fit("input", _FakeAgent(fit))
    assert out.score == 82


def test_fit_score_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        FitScore(score=101, rationale="too high")


def test_score_fit_rejects_wrong_type():
    with pytest.raises(TypeError):
        score_fit("x", _FakeAgent("nope"))


def test_build_fit_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_fit_agent(model_id="claude-haiku-4-5-20251001"), Agent)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_fit.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.fit'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/fit.py`:

```python
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude
from pydantic import Field

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.profile import ProfileFacts


class FitScore(ExtensibleModel):
    score: int = Field(ge=0, le=100)
    rationale: str


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Score how well the candidate fits the job, from 0 to 100.",
    "Base the score only on the candidate facts and job description provided.",
    "Give a one or two sentence rationale.",
]


def build_fit_agent(model_id: str | None = None) -> Agent:
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You rate how well a candidate fits a job.",
        instructions=_INSTRUCTIONS,
        output_schema=FitScore,
    )


def compose_fit_input(jd_text: str, profile_facts: ProfileFacts) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def score_fit(input_text: str, agent: Runner) -> FitScore:
    result = agent.run(input_text)
    fit = result.content
    if not isinstance(fit, FitScore):
        raise TypeError(f"Expected FitScore from agent, got {type(fit).__name__}")
    return fit
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_fit.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/fit.py tests/test_discovery_fit.py
git commit -m "feat(discovery): Agno fit-scorer -> FitScore" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Pipeline orchestration

**Files:**

- Create: `src/resume_tailor_harness/discovery/pipeline.py`
- Test: `tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_pipeline.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.discovery.pipeline import discover
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.models.job import JobCriteria, SponsorshipSignal
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.discovery.fit import FitScore
from resume_tailor_harness.tracking.repository import jobs_by_status
from resume_tailor_harness.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Result:
    def __init__(self, content):
        self.content = content


class _ExtractAgent:
    """Returns denied criteria when the JD mentions 'nosponsor', else offered."""

    def run(self, prompt):
        if "nosponsor" in prompt:
            return _Result(JobCriteria(sponsorship_signal=SponsorshipSignal.denied))
        return _Result(JobCriteria(sponsorship_signal=SponsorshipSignal.offered))


class _FitAgent:
    def run(self, prompt):
        return _Result(FitScore(score=90, rationale="great fit"))


def test_discover_extracts_filters_scores_and_shortlists():
    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role, will sponsor")
        add_job(s, source="manual", jd_text="bad role, nosponsor here")

        counts = discover(s, cfg, facts, _ExtractAgent(), _FitAgent())

        shortlisted = jobs_by_status(s, JobStatus.shortlisted.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert len(shortlisted) == 1
        assert shortlisted[0].fit_score == 90
        assert shortlisted[0].criteria_json["sponsorship_signal"] == "offered"
        assert len(rejected) == 1
        assert rejected[0].reject_reason == "sponsorship not available"
        assert counts[JobStatus.shortlisted.value] == 1
        assert counts[JobStatus.rejected.value] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_discovery_pipeline.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.pipeline'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/discovery/pipeline.py`:

```python
from sqlmodel import Session

from resume_tailor_harness.discovery.extract import Runner, extract_job_criteria
from resume_tailor_harness.discovery.filter import apply_filters
from resume_tailor_harness.discovery.fit import compose_fit_input, score_fit
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.tracking.repository import jobs_by_status, save_job, status_counts
from resume_tailor_harness.tracking.tables import JobStatus


def run_extract(session: Session, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.raw.value):
        criteria = extract_job_criteria(job.jd_text, agent)
        job.criteria_json = criteria.model_dump(mode="json")
        job.status = JobStatus.extracted.value
        save_job(session, job)


def run_filter(session: Session, config: SearchConfig) -> None:
    for job in jobs_by_status(session, JobStatus.extracted.value):
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        decision = apply_filters(criteria, config)
        if decision.keep:
            job.status = JobStatus.filtered.value
        else:
            job.status = JobStatus.rejected.value
            job.reject_reason = decision.reject_reason
        save_job(session, job)


def run_score(session: Session, profile_facts: ProfileFacts, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.filtered.value):
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts), agent)
        job.fit_score = fit.score
        job.fit_rationale = fit.rationale
        job.status = JobStatus.shortlisted.value
        save_job(session, job)


def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
) -> dict[str, int]:
    """Run the full funnel over current rows and return final status counts."""
    run_extract(session, extract_agent)
    run_filter(session, config)
    run_score(session, profile_facts, fit_agent)
    return status_counts(session)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_discovery_pipeline.py -v
```

Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "feat(discovery): funnel pipeline (extract/filter/score/shortlist)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: CLI — `discover` and `addjob`

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_discovery.py`:

```python
from sqlmodel import select

from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.tables import Job, JobStatus

runner = CliRunner()


def test_addjob_inserts_via_stdin(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    result = runner.invoke(
        cli.app,
        ["addjob", "--db-url", db_url, "--company", "Acme", "--title", "Engineer"],
        input="A job description from stdin",
    )
    assert result.exit_code == 0, result.output
    assert "Added job" in result.output

    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        jobs = s.exec(select(Job)).all()
        assert len(jobs) == 1
        assert jobs[0].company == "Acme"
        assert jobs[0].status == JobStatus.raw.value


def test_addjob_reports_duplicate(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    runner.invoke(cli.app, ["addjob", "--db-url", db_url], input="same jd")
    result = runner.invoke(cli.app, ["addjob", "--db-url", db_url], input="same jd")
    assert result.exit_code == 0
    assert "Duplicate" in result.output


def test_discover_runs_and_reports_counts(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    # Seed one raw job directly.
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        s.add(Job(source="manual", jd_text="jd", status=JobStatus.raw.value))
        s.commit()

    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "build_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "build_fit_agent", lambda: object())
    monkeypatch.setattr(
        cli, "discover", lambda session, config, facts, extract_agent, fit_agent: {"shortlisted": 1}
    )

    result = runner.invoke(cli.app, ["discover", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "shortlisted" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_cli_discovery.py -v
```

Expected: FAIL — `AttributeError`/`SystemExit`: the `addjob` and `discover` commands don't exist yet.

- [ ] **Step 3: Write the implementation**

Add these imports near the top of `src/resume_tailor_harness/cli.py` (below the existing imports):

```python
from resume_tailor_harness.config import get_settings
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.discovery.extract import build_extract_agent
from resume_tailor_harness.discovery.fit import build_fit_agent
from resume_tailor_harness.discovery.pipeline import discover
from resume_tailor_harness.discovery.search_config import load_search_config
from resume_tailor_harness.profile.store import load_facts
```

Then append these two commands to the END of `src/resume_tailor_harness/cli.py` (before the `if __name__ == "__main__":` block — move that block to the very end if needed):

```python
DEFAULT_SEARCH = "config/search.yaml"


def _engine(db_url: str | None):
    engine = make_engine(db_url or get_settings().db_url)
    init_db(engine)
    return engine


@app.command("addjob")
def addjob(
    url: str = typer.Option(None, help="Posting URL (used for dedupe)."),
    company: str = typer.Option(None, help="Company name."),
    title: str = typer.Option(None, help="Job title."),
    location: str = typer.Option(None, help="Location."),
    jd_file: str = typer.Option(None, help="Read the JD from this file instead of stdin."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Manually add a job (paste the JD on stdin, or pass --jd-file)."""
    jd_text = Path(jd_file).read_text(encoding="utf-8") if jd_file else typer.get_text_stream("stdin").read()
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = add_job(
            session, source="manual", jd_text=jd_text, url=url, company=company, title=title, location=location
        )
    if job is None:
        typer.echo("Duplicate job (same URL or JD already present); not added.")
        raise typer.Exit(code=0)
    typer.echo(f"Added job #{job.id} (status={job.status}).")


@app.command("discover")
def discover_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the discovery funnel over current jobs and report status counts."""
    config = load_search_config(search)
    profile_facts = load_facts(facts)
    extract_agent = build_extract_agent()
    fit_agent = build_fit_agent()
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover(session, config, profile_facts, extract_agent, fit_agent)
    typer.echo(f"Discovery complete. Status counts: {counts}")
```

(`DEFAULT_FACTS` already exists in `cli.py` from the Profile plan. Ensure the `if __name__ == "__main__": app()` block is the last thing in the file.)

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_cli_discovery.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Verify the commands are wired**

Run:

```bash
uv run resume-tailor-harness addjob --help
uv run resume-tailor-harness discover --help
```

Expected: help text for each (exit 0).

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass (Profile total + Discovery additions).

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_discovery.py
git commit -m "feat(discovery): discover + addjob CLI commands" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.2):** ingest + dedupe (Task 3); cheap-LLM extract → `JobCriteria` (Task 4); deterministic hard filter incl. sponsorship `denied`→reject / `silent`→keep+flag / salary / YoE, rejected rows kept with reason (Task 5); cheap-LLM fit-score + rank-by-score (Task 6); status-driven funnel to `shortlisted` (Task 7); `discover` + manual-assist `addjob` (Task 8); `search.yaml` → `SearchConfig` (Task 1). **Deferred (documented):** live LinkedIn Playwright scraper → its own plan.
- **Placeholder scan:** none — every step has complete code and exact commands.
- **Type consistency:** `extract_job_criteria(jd_text, agent) -> JobCriteria`; `apply_filters(criteria, config) -> FilterDecision`; `score_fit(input_text, agent) -> FitScore` with `compose_fit_input(jd_text, facts) -> str`; pipeline reads/writes `JobStatus` values consistent with `tracking.tables`; `criteria_json` round-trips via `model_dump(mode="json")` ↔ `JobCriteria.model_validate`. Repository `save_job`/`jobs_by_status`/`find_existing`/`status_counts` names match all call sites and tests. CLI patches target module-level names imported into `cli`.

---

## Notes to carry into later plans

- **Tracking plan:** extend `tracking/repository.py` for `applications`/`resume_versions`; add `updated_at` `onupdate` + decide tz-aware vs naive datetime (deferred from Foundation review). Shortlist UI surfaces `sponsorship_signal=silent` as "uncertain".
- **Scraper plan (next after Discovery):** LinkedIn Playwright source implementing a `JobSource` that calls `add_job(...)`; calibrate selectors against live HTML with saved fixtures; add `playwright` dep + `playwright install chromium`.

## Execution Handoff

After this plan is executed and green, the next plan is the **LinkedIn scraper** (calibrated against live HTML), then **Tailor + Review** (the Agno panel).
