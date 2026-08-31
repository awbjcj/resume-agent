# Job Metadata Extraction, Visualization & Filtering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend job metadata extraction (seniority, employment type, tech stack, industry, company size, posting date) and turn the dashboard Shortlist into an interactive decision surface with metadata filters, a profile-aware skill-tag cloud, and a named-preset composite sort.

**Architecture:** Five layers, each independently testable. New JD fields ride inside the existing `criteria_json` blob (no migration); `posted_at` is the single new `Job` column, threaded from API connectors. All filtering/sorting/ranking is pure Python in a new `dashboard/filtering.py`. The Shortlist gets a full-width "control desk" (Layout B); the Pipeline board gets one lean meta line.

**Tech Stack:** Python 3.13, Pydantic v2 (`ExtensibleModel`, `extra="allow"`), SQLModel/SQLAlchemy (SQLite), Typer (CLI), Streamlit (dashboard), pytest (offline, agents/browser faked).

**Spec:** `docs/superpowers/specs/2026-06-16-job-metadata-filtering-design.md`

**Test command:** `cd D:/Fun/resume-tailor-harness && .venv/Scripts/python -m pytest tests/ -q`
**Lint:** `cd D:/Fun/resume-tailor-harness && .venv/Scripts/python -m ruff check`

---

## File Structure

| File                                                                    | Responsibility                                                    | Action        |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------- | ------------- |
| `src/resume_tailor_harness/models/job.py`                                        | `JobCriteria` + new `Seniority`/`EmploymentType` enums + 5 fields | Modify        |
| `src/resume_tailor_harness/discovery/extract.py`                                 | Extract-agent instructions cover new fields                       | Modify        |
| `src/resume_tailor_harness/tracking/tables.py`                                   | `Job.posted_at` column                                            | Modify        |
| `src/resume_tailor_harness/tracking/migrate.py`                                  | `ensure_posted_at_column` (idempotent ALTER)                      | Modify        |
| `src/resume_tailor_harness/db.py`                                                | Call the new migration in `init_db`                               | Modify        |
| `src/resume_tailor_harness/discovery/connectors/base.py`                         | `RawJob.posted_at`                                                | Modify        |
| `src/resume_tailor_harness/discovery/connectors/dates.py`                        | `parse_iso_datetime` pure helper                                  | Create        |
| `src/resume_tailor_harness/discovery/connectors/{greenhouse,remoteok,adzuna}.py` | Populate `RawJob.posted_at`                                       | Modify        |
| `src/resume_tailor_harness/discovery/ingest.py`                                  | Thread `posted_at` into `Job`                                     | Modify        |
| `src/resume_tailor_harness/discovery/pipeline.py`                                | `reextract` over post-raw jobs                                    | Modify        |
| `src/resume_tailor_harness/cli.py`                                               | `discover --reextract` flag                                       | Modify        |
| `src/resume_tailor_harness/tracking/queries.py`                                  | Widen `ShortlistRow`/`PipelineRow`, `SkillTag`, coverage tagging  | Modify        |
| `src/resume_tailor_harness/dashboard/filtering.py`                               | `FilterState`, filter/sort/composite/cloud — pure                 | Create        |
| `src/resume_tailor_harness/dashboard/ui.py`                                      | `skill_chip`, `meta_line`, control-desk + chip CSS                | Modify        |
| `src/resume_tailor_harness/dashboard/pages.py`                                   | Shortlist control desk + rich cards; Pipeline meta line           | Modify        |
| `tests/...`                                                             | One test file per module above                                    | Create/Modify |

---

## Task 1: Extend `JobCriteria` with new metadata fields

**Files:**

- Modify: `src/resume_tailor_harness/models/job.py`
- Test: `tests/test_models_job.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models_job.py`:

```python
from resume_tailor_harness.models.job import (
    EmploymentType,
    JobCriteria,
    Seniority,
)


def test_job_criteria_new_fields_default_empty():
    c = JobCriteria()
    assert c.seniority is None
    assert c.employment_type is None
    assert c.tech_stack == []
    assert c.industry is None
    assert c.company_size is None


def test_job_criteria_new_fields_roundtrip():
    c = JobCriteria(
        seniority=Seniority.senior,
        employment_type=EmploymentType.full_time,
        tech_stack=["python", "aws"],
        industry="fintech",
        company_size="scaleup",
    )
    dumped = c.model_dump(mode="json")
    restored = JobCriteria.model_validate(dumped)
    assert restored.seniority == Seniority.senior
    assert restored.employment_type == EmploymentType.full_time
    assert restored.tech_stack == ["python", "aws"]
    assert restored.industry == "fintech"
    assert restored.company_size == "scaleup"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models_job.py -q`
Expected: FAIL — `ImportError: cannot import name 'Seniority'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/models/job.py`, add two enums and five fields. Full file after edit:

```python
from enum import Enum

from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel


class SponsorshipSignal(str, Enum):
    """What the JD says about visa sponsorship. ``silent`` => uncertain (keep + flag)."""

    offered = "offered"
    denied = "denied"
    silent = "silent"


class Seniority(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    principal = "principal"


class EmploymentType(str, Enum):
    full_time = "full_time"
    contract = "contract"
    internship = "internship"
    part_time = "part_time"


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
    seniority: Seniority | None = None
    employment_type: EmploymentType | None = None
    tech_stack: list[str] = Field(default_factory=list)
    industry: str | None = None  # fintech, healthcare, …
    company_size: str | None = None  # startup | scaleup | enterprise
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models_job.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/models/job.py tests/test_models_job.py
git commit -m "feat(models): add seniority, employment type, tech stack, industry, company size to JobCriteria"
```

---

## Task 2: Teach the extract agent the new fields

**Files:**

- Modify: `src/resume_tailor_harness/discovery/extract.py`
- Test: `tests/test_discovery_extract.py`

The agent's output schema is already `JobCriteria`, so new fields are auto-included. We only extend the natural-language instructions so the model populates them, and assert the instructions mention them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_extract.py`:

```python
from resume_tailor_harness.discovery.extract import _INSTRUCTIONS


def test_instructions_mention_new_fields():
    joined = " ".join(_INSTRUCTIONS).lower()
    for needle in ["seniority", "employment type", "tech stack", "industry", "company size"]:
        assert needle in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_extract.py::test_instructions_mention_new_fields -q`
Expected: FAIL — assertion error on "seniority".

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/discovery/extract.py`, replace `_INSTRUCTIONS`:

```python
_INSTRUCTIONS = [
    "Extract structured hiring criteria from the job description text.",
    "Infer the sponsorship signal: 'offered', 'denied', or 'silent' when the text says nothing.",
    "Infer seniority as one of: junior, mid, senior, staff, principal — leave null if unclear.",
    "Infer employment type as one of: full_time, contract, internship, part_time — leave null if unclear.",
    "List the concrete tech stack (languages, frameworks, tools) named in the post.",
    "Capture the industry or domain (e.g. fintech, healthcare) when stated.",
    "Capture company size or stage (startup, scaleup, enterprise) when stated.",
    "Use only what the text supports; leave unknown fields null.",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_extract.py -q`
Expected: PASS (all extract tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/extract.py tests/test_discovery_extract.py
git commit -m "feat(discovery): extend extract-agent instructions for new metadata fields"
```

---

## Task 3: Add `Job.posted_at` column + idempotent migration

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py:37-54` (the `Job` model)
- Modify: `src/resume_tailor_harness/tracking/migrate.py`
- Modify: `src/resume_tailor_harness/db.py:28-30` (`init_db`)
- Test: `tests/test_migrate.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migrate.py`:

```python
from sqlalchemy import text
from sqlmodel import create_engine

from resume_tailor_harness.tracking.migrate import ensure_posted_at_column


def test_ensure_posted_at_column_adds_missing_column():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    ensure_posted_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert "posted_at" in cols


def test_ensure_posted_at_column_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    ensure_posted_at_column(engine)
    ensure_posted_at_column(engine)  # second call must not raise
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert cols.count("posted_at") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_migrate.py -q`
Expected: FAIL — `ImportError: cannot import name 'ensure_posted_at_column'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/resume_tailor_harness/tracking/migrate.py`:

```python
def ensure_posted_at_column(engine: Engine) -> None:
    """Idempotently add the ``jobs.posted_at`` column (source-derived posting date)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "posted_at" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN posted_at DATETIME"))
```

In `src/resume_tailor_harness/tracking/tables.py`, add the field to `Job` (right after `created_at` line 54). The class becomes:

```python
class Job(SQLModel, table=True):
    __tablename__ = cast(Any, "jobs")

    id: int | None = Field(default=None, primary_key=True)
    source: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    dedup_key: str | None = Field(default=None, index=True)
    jd_text: str = ""
    criteria_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str = Field(default=JobStatus.raw.value, index=True)
    reject_reason: str | None = None
    posted_at: datetime | None = None
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
```

In `src/resume_tailor_harness/db.py`, wire the migration into `init_db`:

```python
from resume_tailor_harness.tracking.migrate import ensure_dedup_key_column, ensure_posted_at_column

# ...

def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
    ensure_posted_at_column(engine)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_migrate.py tests/test_db.py tests/test_tables.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py src/resume_tailor_harness/tracking/migrate.py src/resume_tailor_harness/db.py tests/test_migrate.py
git commit -m "feat(db): add Job.posted_at column with idempotent migration"
```

---

## Task 4: Add `RawJob.posted_at` + thread it through ingest

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/base.py:7-16` (`RawJob`)
- Modify: `src/resume_tailor_harness/discovery/ingest.py:19-67`
- Test: `tests/test_ingest_jobs.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest_jobs.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.ingest import ingest_jobs
from resume_tailor_harness.tracking.repository import jobs_by_status
from resume_tailor_harness.tracking.tables import JobStatus


def test_ingest_threads_posted_at(session_factory):
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with session_factory() as s:
        ingest_jobs(s, [RawJob(source="greenhouse", url="u1", company="Acme",
                               title="Eng", location="Remote", jd_text="hello",
                               posted_at=when)])
        jobs = jobs_by_status(s, JobStatus.raw.value)
        assert len(jobs) == 1
        assert jobs[0].posted_at == when
```

If `tests/test_ingest_jobs.py` has no `session_factory` fixture, use the in-file pattern already present there (an in-memory engine + `SQLModel.metadata.create_all`). Match the existing test's setup helper instead of the fixture name if they differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ingest_jobs.py::test_ingest_threads_posted_at -q`
Expected: FAIL — `TypeError: RawJob.__init__() got an unexpected keyword argument 'posted_at'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/discovery/connectors/base.py`, add the field (and the import):

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from resume_tailor_harness.discovery.search_config import SearchConfig


@dataclass
class RawJob:
    """A single job as a connector emits it, ready for ingest."""

    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str
    posted_at: datetime | None = None
```

In `src/resume_tailor_harness/discovery/ingest.py`, thread `posted_at` through `add_job` and `ingest_jobs`:

```python
from datetime import datetime

# add_job signature gains the keyword:
def add_job(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    posted_at: datetime | None = None,
) -> Job | None:
    """Normalize, dedupe, and insert a raw job. Returns None if a duplicate exists."""
    jd_text = jd_text.strip()
    url = _clean(url)
    company = _clean(company)
    title = _clean(title)
    dedup_key = compute_dedup_key(company, title)
    if find_existing(session, url, jd_text, dedup_key) is not None:
        return None
    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=_clean(location),
        dedup_key=dedup_key,
        posted_at=posted_at,
        status=JobStatus.raw.value,
    )
    return save_job(session, job)
```

And in `ingest_jobs`, pass it from the `RawJob`:

```python
        job = add_job(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            posted_at=raw.posted_at,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ingest_jobs.py tests/test_connectors_base.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/base.py src/resume_tailor_harness/discovery/ingest.py tests/test_ingest_jobs.py
git commit -m "feat(ingest): thread RawJob.posted_at into Job"
```

---

## Task 5: ISO date helper + populate `posted_at` in API connectors

**Files:**

- Create: `src/resume_tailor_harness/discovery/connectors/dates.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/greenhouse.py:11-26`
- Modify: `src/resume_tailor_harness/discovery/connectors/remoteok.py:10-26`
- Modify: `src/resume_tailor_harness/discovery/connectors/adzuna.py:10-24`
- Test: `tests/test_connector_dates.py` (create), and the three existing connector tests

LinkedIn `posted_at` stays `None` (no date element is scraped today — deferred, absorbed by the neutral null rule).

- [ ] **Step 1: Write the failing test (the date helper)**

Create `tests/test_connector_dates.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime


def test_parses_iso_with_z():
    assert parse_iso_datetime("2026-06-01T12:00:00Z") == datetime(
        2026, 6, 1, 12, 0, tzinfo=timezone.utc
    )


def test_parses_iso_with_offset():
    out = parse_iso_datetime("2026-06-01T12:00:00+00:00")
    assert out == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_returns_none_on_garbage_or_empty():
    assert parse_iso_datetime("not a date") is None
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_connector_dates.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the date helper**

Create `src/resume_tailor_harness/discovery/connectors/dates.py`:

```python
from datetime import datetime, timezone


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string to an aware UTC datetime, or None on failure.

    Accepts a trailing 'Z'. Naive results are assumed UTC.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_connector_dates.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing tests for connector parsers**

Add to `tests/test_connector_greenhouse.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.greenhouse import parse_greenhouse


def test_parse_greenhouse_sets_posted_at_from_updated_at():
    payload = {"jobs": [{"title": "Eng", "absolute_url": "u",
                         "location": {"name": "Remote"}, "content": "hi",
                         "updated_at": "2026-06-01T00:00:00Z"}]}
    jobs = parse_greenhouse(payload, "Acme")
    assert jobs[0].posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_parse_greenhouse_posted_at_none_when_absent():
    payload = {"jobs": [{"title": "Eng", "absolute_url": "u", "content": "hi"}]}
    assert parse_greenhouse(payload, "Acme")[0].posted_at is None
```

Add to `tests/test_connector_remoteok.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.remoteok import parse_remoteok


def test_parse_remoteok_sets_posted_at_from_date():
    payload = [{"position": "Eng", "company": "Acme", "url": "u",
                "description": "hi", "date": "2026-06-01T00:00:00+00:00"}]
    assert parse_remoteok(payload)[0].posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
```

Add to `tests/test_connector_adzuna.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.discovery.connectors.adzuna import parse_adzuna


def test_parse_adzuna_sets_posted_at_from_created():
    payload = {"results": [{"title": "Eng", "redirect_url": "u",
                            "company": {"display_name": "Acme"},
                            "location": {"display_name": "Remote"},
                            "description": "hi", "created": "2026-06-01T00:00:00Z"}]}
    assert parse_adzuna(payload)[0].posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
```

- [ ] **Step 6: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_connector_greenhouse.py tests/test_connector_remoteok.py tests/test_connector_adzuna.py -q`
Expected: FAIL — `posted_at` is `None` (field defaults), assertions fail.

- [ ] **Step 7: Populate `posted_at` in each parser**

`greenhouse.py` — update `parse_greenhouse`'s `RawJob(...)` to add the import and field:

```python
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
# ...
        jobs.append(
            RawJob(
                source="greenhouse",
                url=item.get("absolute_url"),
                company=company,
                title=item.get("title"),
                location=location,
                jd_text=html_to_text(item.get("content", "")),
                posted_at=parse_iso_datetime(item.get("updated_at")),
            )
        )
```

`remoteok.py` — add import + field:

```python
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
# ...
        jobs.append(
            RawJob(
                source="remoteok",
                url=item.get("url"),
                company=item.get("company"),
                title=item.get("position"),
                location=item.get("location") or "Remote",
                jd_text=html_to_text(item.get("description", "")),
                posted_at=parse_iso_datetime(item.get("date")),
            )
        )
```

`adzuna.py` — add import + field:

```python
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
# ...
        jobs.append(
            RawJob(
                source="adzuna",
                url=item.get("redirect_url"),
                company=(item.get("company") or {}).get("display_name"),
                title=item.get("title"),
                location=(item.get("location") or {}).get("display_name"),
                jd_text=item.get("description") or "",
                posted_at=parse_iso_datetime(item.get("created")),
            )
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_connector_greenhouse.py tests/test_connector_remoteok.py tests/test_connector_adzuna.py tests/test_connector_dates.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/dates.py src/resume_tailor_harness/discovery/connectors/greenhouse.py src/resume_tailor_harness/discovery/connectors/remoteok.py src/resume_tailor_harness/discovery/connectors/adzuna.py tests/test_connector_dates.py tests/test_connector_greenhouse.py tests/test_connector_remoteok.py tests/test_connector_adzuna.py
git commit -m "feat(connectors): capture posting date into RawJob.posted_at for API connectors"
```

---

## Task 6: `discover --reextract` backfill path

**Files:**

- Modify: `src/resume_tailor_harness/discovery/pipeline.py`
- Modify: `src/resume_tailor_harness/cli.py:164-178`
- Test: `tests/test_discovery_pipeline.py`, `tests/test_cli_discovery.py`

Re-extract re-runs the extract agent over jobs that already moved past `raw`, rewriting `criteria_json` in place. It does **not** change status or re-score fit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_pipeline.py` (match the file's existing fake-agent + session helpers; the snippet below shows the assertions):

```python
from resume_tailor_harness.discovery.pipeline import reextract
from resume_tailor_harness.models.job import JobCriteria, Seniority
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


class _FakeResult:
    def __init__(self, content): self.content = content


class _FakeAgent:
    def __init__(self, content): self._content = content
    def run(self, prompt): return _FakeResult(self._content)


def test_reextract_rewrites_criteria_without_changing_status(session_factory):
    agent = _FakeAgent(JobCriteria(seniority=Seniority.staff))
    with session_factory() as s:
        save_job(s, Job(source="manual", jd_text="jd", status=JobStatus.shortlisted.value,
                        criteria_json={"seniority": None}, fit_score=70))
        save_job(s, Job(source="manual", jd_text="raw-jd", status=JobStatus.raw.value))

        reextract(s, agent)

        shortlisted = [j for j in s.query(Job).all() if j.status == JobStatus.shortlisted.value]
        raw = [j for j in s.query(Job).all() if j.status == JobStatus.raw.value]
        assert shortlisted[0].criteria_json["seniority"] == "staff"
        assert shortlisted[0].status == JobStatus.shortlisted.value  # unchanged
        assert shortlisted[0].fit_score == 70  # untouched
        assert raw and raw[0].criteria_json is None  # raw rows skipped
```

If `session_factory` is not a fixture in that file, reuse the file's existing session-construction helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_pipeline.py::test_reextract_rewrites_criteria_without_changing_status -q`
Expected: FAIL — `ImportError: cannot import name 'reextract'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/resume_tailor_harness/discovery/pipeline.py`:

```python
_REEXTRACT_STATUSES = (
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.shortlisted.value,
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
)


def reextract(session: Session, agent: Runner) -> int:
    """Re-run extraction over already-processed jobs, rewriting criteria_json in place.

    Does not change status or fit. Returns the number of jobs updated.
    """
    updated = 0
    for status in _REEXTRACT_STATUSES:
        for job in jobs_by_status(session, status):
            if not job.jd_text.strip():
                continue
            criteria = extract_job_criteria(job.jd_text, agent)
            job.criteria_json = criteria.model_dump(mode="json")
            session.add(job)
            updated += 1
    session.commit()
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the CLI flag — write the failing CLI test**

Add to `tests/test_cli_discovery.py` (match the file's existing CliRunner + monkeypatch style; assertions shown):

```python
def test_discover_reextract_invokes_reextract(monkeypatch, tmp_path):
    called = {}

    def fake_reextract(session, agent):
        called["hit"] = True
        return 3

    monkeypatch.setattr("resume_tailor_harness.cli.reextract", fake_reextract)
    # ... build search.yaml + facts.json via the file's existing helpers ...
    result = runner.invoke(app, ["discover", "--reextract", "--search", str(search_path),
                                 "--facts", str(facts_path), "--db-url", "sqlite://"])
    assert result.exit_code == 0
    assert called.get("hit") is True
```

- [ ] **Step 6: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cli_discovery.py::test_discover_reextract_invokes_reextract -q`
Expected: FAIL — `--reextract` is not a known option.

- [ ] **Step 7: Add the flag to the CLI**

In `src/resume_tailor_harness/cli.py`, import `reextract` alongside `discover`, and update `discover_cmd`:

```python
from resume_tailor_harness.discovery.pipeline import discover, reextract  # adjust existing import


@app.command("discover")
def discover_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    reextract_existing: bool = typer.Option(
        False, "--reextract",
        help="Re-extract metadata for already-processed jobs (backfill new fields). "
             "Does not change status or fit.",
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the discovery funnel over current jobs and report status counts."""
    config = load_search_config(search)
    profile_facts = load_facts(facts)
    extract_agent = build_extract_agent()
    fit_agent = build_fit_agent()
    engine = _engine(db_url)
    with get_session(engine) as session:
        if reextract_existing:
            n = reextract(session, extract_agent)
            typer.echo(f"Re-extracted metadata for {n} job(s).")
            return
        counts = discover(session, config, profile_facts, extract_agent, fit_agent)
    typer.echo(f"Discovery complete. Status counts: {counts}")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli_discovery.py tests/test_discovery_pipeline.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/resume_tailor_harness/discovery/pipeline.py src/resume_tailor_harness/cli.py tests/test_discovery_pipeline.py tests/test_cli_discovery.py
git commit -m "feat(discovery): add 'discover --reextract' backfill path"
```

---

## Task 7: Widen `ShortlistRow`/`PipelineRow` with metadata + skill coverage

**Files:**

- Modify: `src/resume_tailor_harness/tracking/queries.py`
- Test: `tests/test_tracking_queries.py`

`shortlist_rows` flattens `criteria_json` into typed fields and builds `SkillTag`s (must + nice), tagging each by profile coverage via `match_gap.profile_skill_tokens`. `pipeline_rows` gains only the three lean fields (salary string parts + remote + seniority). Profile facts are loaded once and passed in (testable), defaulting to no coverage when absent.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tracking_queries.py`:

```python
from datetime import datetime, timezone

from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.models.base import Source
from resume_tailor_harness.models.profile import Skill
from resume_tailor_harness.tracking.queries import shortlist_rows


def _facts_with_python() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"lang": [Skill(name="Python", source=Source.resume)]},
    )


def test_shortlist_row_flattens_metadata_and_tags_coverage():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=80,
                        posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                        criteria_json={
                            "salary_range": {"minimum": 150000, "maximum": 190000, "currency": "USD"},
                            "remote_policy": "remote",
                            "seniority": "senior",
                            "employment_type": "full_time",
                            "industry": "fintech",
                            "company_size": "scaleup",
                            "must_have_skills": ["Python", "Go"],
                            "nice_to_have_skills": ["Docker"],
                        }))
        rows = shortlist_rows(s, facts=_facts_with_python())
        row = rows[0]
        assert row.salary_min == 150000 and row.salary_max == 190000
        assert row.remote_policy == "remote"
        assert row.seniority == "senior" and row.employment_type == "full_time"
        assert row.industry == "fintech" and row.company_size == "scaleup"
        assert row.posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
        names = {t.name: t for t in row.skills}
        assert names["Python"].covered is True and names["Python"].required is True
        assert names["Go"].covered is False and names["Go"].required is True
        assert names["Docker"].required is False


def test_shortlist_row_without_facts_marks_all_uncovered():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", status=JobStatus.shortlisted.value,
                        criteria_json={"must_have_skills": ["Python"]}))
        rows = shortlist_rows(s, facts=None)
        assert rows[0].skills[0].covered is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_tracking_queries.py -q`
Expected: FAIL — `shortlist_rows()` takes 1 positional arg / `ShortlistRow` has no `salary_min`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/tracking/queries.py`, add imports and replace `ShortlistRow` + `shortlist_rows`, and widen `PipelineRow`/`pipeline_rows`:

```python
from datetime import datetime

from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.tracking.match_gap import normalize_skill, profile_skill_tokens


@dataclass
class SkillTag:
    name: str
    covered: bool
    required: bool  # True = must-have, False = nice-to-have


@dataclass
class ShortlistRow:
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]


def _skill_tags(criteria: dict, tokens: set[str]) -> list[SkillTag]:
    tags: list[SkillTag] = []
    for key, required in (("must_have_skills", True), ("nice_to_have_skills", False)):
        for name in criteria.get(key) or []:
            name = str(name).strip()
            if not name:
                continue
            tags.append(SkillTag(name=name, covered=normalize_skill(name) in tokens, required=required))
    return tags


def shortlist_rows(session: Session, facts: ProfileFacts | None = None) -> list[ShortlistRow]:
    fit_score_col = cast(Any, Job.fit_score)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value)
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        rows.append(
            ShortlistRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                location=job.location,
                fit_score=job.fit_score,
                fit_rationale=job.fit_rationale,
                sponsorship_signal=criteria.get("sponsorship_signal"),
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                salary_currency=salary.get("currency"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                employment_type=criteria.get("employment_type"),
                industry=criteria.get("industry"),
                company_size=criteria.get("company_size"),
                posted_at=job.posted_at,
                skills=_skill_tags(criteria, tokens),
            )
        )
    return rows
```

For the Pipeline lean line, add three fields to `PipelineRow` and populate them in `pipeline_rows`:

```python
@dataclass
class PipelineRow:
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: int | None
    salary_max: int | None
    remote_policy: str | None
    seniority: str | None
```

In `pipeline_rows`, inside the loop add before constructing the row:

```python
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
```

and pass `salary_min=salary.get("minimum"), salary_max=salary.get("maximum"), remote_policy=criteria.get("remote_policy"), seniority=criteria.get("seniority")` to `PipelineRow(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_tracking_queries.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/queries.py tests/test_tracking_queries.py
git commit -m "feat(queries): flatten metadata + profile-coverage skill tags into shortlist/pipeline rows"
```

---

## Task 8: Pure filtering / sorting / composite module

**Files:**

- Create: `src/resume_tailor_harness/dashboard/filtering.py`
- Test: `tests/test_dashboard_filtering.py` (create)

Pure module — no Streamlit. Operates on the `ShortlistRow`/`SkillTag` from Task 7. `now` is injected for deterministic recency tests.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_filtering.py`:

```python
from datetime import datetime, timedelta, timezone

from resume_tailor_harness.dashboard.filtering import (
    FilterState,
    apply_filters,
    available_skill_cloud,
    composite_score,
    sort_rows,
)
from resume_tailor_harness.tracking.queries import ShortlistRow, SkillTag

NOW = datetime(2026, 6, 16, tzinfo=timezone.utc)


def _row(job_id=1, fit=80, salary_min=None, salary_max=None, remote=None,
         seniority=None, emp=None, industry=None, sponsorship=None,
         posted=None, skills=None):
    return ShortlistRow(
        job_id=job_id, company="C", title="T", location="L", fit_score=fit,
        fit_rationale="r", sponsorship_signal=sponsorship, salary_min=salary_min,
        salary_max=salary_max, salary_currency="USD", remote_policy=remote,
        seniority=seniority, employment_type=emp, industry=industry,
        company_size=None, posted_at=posted, skills=skills or [],
    )


def test_salary_floor_excludes_only_known_below():
    rows = [_row(job_id=1, salary_max=100000), _row(job_id=2, salary_max=200000),
            _row(job_id=3, salary_max=None)]
    out = apply_filters(rows, FilterState(salary_min=150000))
    ids = {r.job_id for r in out}
    assert ids == {2, 3}  # unknown salary passes; known-below excluded


def test_remote_and_seniority_and_together():
    rows = [_row(job_id=1, remote="remote", seniority="senior"),
            _row(job_id=2, remote="onsite", seniority="senior")]
    out = apply_filters(rows, FilterState(remote={"remote"}, seniority={"senior"}))
    assert {r.job_id for r in out} == {1}


def test_skills_use_or_semantics():
    rows = [_row(job_id=1, skills=[SkillTag("python", True, True)]),
            _row(job_id=2, skills=[SkillTag("go", False, True)]),
            _row(job_id=3, skills=[SkillTag("rust", False, True)])]
    out = apply_filters(rows, FilterState(skills={"python", "go"}))
    assert {r.job_id for r in out} == {1, 2}


def test_fit_min_filter():
    rows = [_row(job_id=1, fit=60), _row(job_id=2, fit=90)]
    out = apply_filters(rows, FilterState(fit_min=80))
    assert {r.job_id for r in out} == {2}


def test_sort_by_salary_desc_nulls_last():
    rows = [_row(job_id=1, salary_max=100000), _row(job_id=2, salary_max=None),
            _row(job_id=3, salary_max=200000)]
    out = sort_rows(rows, FilterState(sort="salary"), now=NOW)
    assert [r.job_id for r in out] == [3, 1, 2]


def test_sort_by_recency_desc_nulls_last():
    rows = [_row(job_id=1, posted=NOW - timedelta(days=10)),
            _row(job_id=2, posted=None),
            _row(job_id=3, posted=NOW - timedelta(days=1))]
    out = sort_rows(rows, FilterState(sort="recency"), now=NOW)
    assert [r.job_id for r in out] == [3, 1, 2]


def test_composite_neutral_for_missing_factors():
    # all factors missing -> pure neutral 50 on every channel -> 50.0
    score = composite_score(_row(fit=None, salary_max=None, posted=None), "balanced", now=NOW)
    assert score == 50.0


def test_composite_pay_first_prefers_salary():
    high_pay = _row(job_id=1, fit=50, salary_max=250000, posted=None)
    high_fit = _row(job_id=2, fit=100, salary_max=0, posted=None)
    s_pay = composite_score(high_pay, "pay_first", now=NOW)
    s_fit = composite_score(high_fit, "pay_first", now=NOW)
    assert s_pay > s_fit


def test_composite_salary_capped_at_ceiling():
    capped = _row(salary_max=250000)
    over = _row(salary_max=900000)
    assert composite_score(capped, "pay_first", now=NOW) == composite_score(over, "pay_first", now=NOW)


def test_available_skill_cloud_is_deduped_union():
    rows = [_row(job_id=1, skills=[SkillTag("python", True, True), SkillTag("go", False, True)]),
            _row(job_id=2, skills=[SkillTag("python", True, False)])]
    cloud = available_skill_cloud(rows)
    names = {t.name for t in cloud}
    assert names == {"python", "go"}
    # covered flag preserved; a skill required by ANY job stays required=True
    py = next(t for t in cloud if t.name == "python")
    assert py.covered is True and py.required is True


def test_empty_result_returns_empty_list():
    assert apply_filters([], FilterState(fit_min=90)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_filtering.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the implementation**

Create `src/resume_tailor_harness/dashboard/filtering.py`:

```python
"""Pure filtering, sorting, and composite ranking over ShortlistRows.

No Streamlit imports — every function is deterministic and unit-testable.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from resume_tailor_harness.tracking.match_gap import normalize_skill
from resume_tailor_harness.tracking.queries import ShortlistRow, SkillTag

SALARY_CEILING = 250_000
RECENCY_WINDOW_DAYS = 30
NEUTRAL = 50.0

# weights sum to 1.0: (fit, salary, recency)
PRESETS: dict[str, tuple[float, float, float]] = {
    "balanced": (0.50, 0.30, 0.20),
    "pay_first": (0.30, 0.55, 0.15),
    "freshest": (0.35, 0.20, 0.45),
}


@dataclass
class FilterState:
    salary_min: int | None = None
    remote: set[str] = field(default_factory=set)
    sponsorship: set[str] = field(default_factory=set)
    seniority: set[str] = field(default_factory=set)
    employment_type: set[str] = field(default_factory=set)
    industry: set[str] = field(default_factory=set)
    fit_min: int | None = None
    skills: set[str] = field(default_factory=set)  # normalized, OR semantics
    sort: str = "fit"  # fit | salary | recency | composite
    preset: str = "balanced"  # balanced | pay_first | freshest


def _passes(row: ShortlistRow, state: FilterState) -> bool:
    # salary floor: exclude only when a known max is below the floor
    if state.salary_min is not None and row.salary_max is not None:
        if row.salary_max < state.salary_min:
            return False
    if state.fit_min is not None and row.fit_score is not None:
        if row.fit_score < state.fit_min:
            return False
    # categorical AND filters; an unknown (None) value is NOT excluded
    for selected, value in (
        (state.remote, row.remote_policy),
        (state.sponsorship, row.sponsorship_signal),
        (state.seniority, row.seniority),
        (state.employment_type, row.employment_type),
        (state.industry, row.industry),
    ):
        if selected and value is not None and value not in selected:
            return False
    # skills: OR — pass if the row requires/lists ANY selected skill
    if state.skills:
        row_tokens = {normalize_skill(t.name) for t in row.skills}
        if not (row_tokens & state.skills):
            return False
    return True


def apply_filters(rows: list[ShortlistRow], state: FilterState) -> list[ShortlistRow]:
    return [r for r in rows if _passes(r, state)]


def _salary_value(row: ShortlistRow) -> int | None:
    return row.salary_max if row.salary_max is not None else row.salary_min


def _age_days(row: ShortlistRow, now: datetime) -> float | None:
    if row.posted_at is None:
        return None
    posted = row.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return (now - posted).total_seconds() / 86400.0


def composite_score(row: ShortlistRow, preset: str, now: datetime) -> float:
    w_fit, w_sal, w_rec = PRESETS.get(preset, PRESETS["balanced"])

    fit_n = float(row.fit_score) if row.fit_score is not None else NEUTRAL

    sal = _salary_value(row)
    salary_n = min(sal, SALARY_CEILING) / SALARY_CEILING * 100 if sal is not None else NEUTRAL

    age = _age_days(row, now)
    if age is None:
        recency_n = NEUTRAL
    else:
        recency_n = max(0.0, 100.0 - (age / RECENCY_WINDOW_DAYS * 100.0))

    return round(w_fit * fit_n + w_sal * salary_n + w_rec * recency_n, 4)


def sort_rows(rows: list[ShortlistRow], state: FilterState,
              now: datetime | None = None) -> list[ShortlistRow]:
    now = now or datetime.now(timezone.utc)
    if state.sort == "salary":
        return sorted(rows, key=lambda r: (_salary_value(r) is not None, _salary_value(r) or 0),
                      reverse=True)
    if state.sort == "recency":
        # newest first; nulls last
        return sorted(
            rows,
            key=lambda r: (r.posted_at is not None,
                           r.posted_at.timestamp() if r.posted_at else 0.0),
            reverse=True,
        )
    if state.sort == "composite":
        return sorted(rows, key=lambda r: composite_score(r, state.preset, now), reverse=True)
    # default: fit, nulls last
    return sorted(rows, key=lambda r: (r.fit_score is not None, r.fit_score or 0), reverse=True)


def available_skill_cloud(rows: list[ShortlistRow]) -> list[SkillTag]:
    """Deduped union of all skills across rows, by normalized token.

    A skill is `required` if ANY job requires it; `covered` if any occurrence is covered.
    Sorted: covered-first, then alphabetical (stable, deterministic for the UI).
    """
    merged: dict[str, SkillTag] = {}
    for row in rows:
        for tag in row.skills:
            token = normalize_skill(tag.name)
            if not token:
                continue
            existing = merged.get(token)
            if existing is None:
                merged[token] = SkillTag(name=tag.name, covered=tag.covered, required=tag.required)
            else:
                existing.covered = existing.covered or tag.covered
                existing.required = existing.required or tag.required
    return sorted(merged.values(), key=lambda t: (not t.covered, t.name.lower()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_filtering.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/dashboard/filtering.py tests/test_dashboard_filtering.py
git commit -m "feat(dashboard): pure metadata filtering, sorting, and named-preset composite ranking"
```

---

## Task 9: `ui.py` chip + meta-line helpers and CSS

**Files:**

- Modify: `src/resume_tailor_harness/dashboard/ui.py`
- Test: `tests/test_dashboard_ui.py`

Pure HTML helpers (the module's existing contract: no Streamlit at import/call time for these).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard_ui.py`:

```python
from resume_tailor_harness.dashboard.ui import THEME_CSS, meta_line, skill_chip
from resume_tailor_harness.tracking.queries import ShortlistRow, SkillTag


def test_skill_chip_encodes_coverage_requirement_and_active():
    covered_must = skill_chip(SkillTag("python", covered=True, required=True), active=True)
    assert "python" in covered_must
    assert "chip-have" in covered_must     # coverage channel
    assert "chip-sel" in covered_must      # active-filter ring
    gap_nice = skill_chip(SkillTag("graphql", covered=False, required=False), active=False)
    assert "chip-gap" in gap_nice
    assert "chip-nice" in gap_nice
    assert "+graphql" in gap_nice          # nice-to-have prefix


def _row(**kw):
    base = dict(job_id=1, company="C", title="T", location="L", fit_score=80,
               fit_rationale="r", sponsorship_signal=None, salary_min=None,
               salary_max=None, salary_currency="USD", remote_policy=None,
               seniority=None, employment_type=None, industry=None,
               company_size=None, posted_at=None, skills=[])
    base.update(kw)
    return ShortlistRow(**base)


def test_meta_line_omits_nulls():
    line = meta_line(_row(salary_min=150000, salary_max=190000, seniority="senior"))
    assert "150" in line and "190" in line
    assert "senior" in line.lower()
    # nothing for the missing fields
    assert "None" not in line


def test_meta_line_empty_when_all_null():
    assert meta_line(_row()) == ""


def test_theme_css_has_controldesk_and_chip_classes():
    assert ".controldesk" in THEME_CSS
    assert ".chip-have" in THEME_CSS
    assert ".chip-gap" in THEME_CSS
    assert ".chip-nice" in THEME_CSS
    assert ".chip-sel" in THEME_CSS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL — `ImportError: cannot import name 'skill_chip'`.

- [ ] **Step 3: Write the helpers + CSS**

In `src/resume_tailor_harness/dashboard/ui.py`, add the helpers (after `fit_block`):

```python
def skill_chip(tag, active: bool) -> str:
    """Render a skill chip. Channels: colour=coverage, class=requirement, ring=active filter."""
    classes = ["chip", "chip-have" if tag.covered else "chip-gap"]
    if not tag.required:
        classes.append("chip-nice")
    if active:
        classes.append("chip-sel")
    label = tag.name if tag.required else f"+{tag.name}"
    return f'<span class="{" ".join(classes)}">{label}</span>'


def meta_line(row) -> str:
    """One null-omitting mono meta string: salary · seniority · type · industry · recency."""
    parts: list[str] = []
    if row.salary_min is not None or row.salary_max is not None:
        lo = f"{row.salary_min // 1000}k" if row.salary_min else None
        hi = f"{row.salary_max // 1000}k" if row.salary_max else None
        parts.append("$" + (f"{lo}–{hi}" if lo and hi else (lo or hi)))
    if row.seniority:
        parts.append(str(row.seniority).replace("_", " ").title())
    if getattr(row, "employment_type", None):
        parts.append(str(row.employment_type).replace("_", " ").title())
    if getattr(row, "industry", None):
        parts.append(str(row.industry))
    if getattr(row, "posted_at", None) is not None:
        from datetime import datetime, timezone
        posted = row.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - posted).days)
        parts.append("today" if days == 0 else f"{days}d ago")
    return " · ".join(parts)
```

Then extend `THEME_CSS` — add this block just before the closing `</style>`:

```css
/* ── Control desk + skill chips ───────────────────────────────── */
.controldesk {
  background: var(--paper-2);
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 0.8rem 1rem;
  margin: 0 0 1.2rem;
}
.metaline {
  font-family: "IBM Plex Mono", monospace;
  font-size: 0.84rem;
  color: var(--ink);
  margin-top: 0.45rem;
}
.skills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.5rem;
}
.chip {
  display: inline-block;
  font-family: "IBM Plex Mono", monospace;
  font-size: 0.66rem;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  border: 1px solid var(--rule);
  background: #fff;
  color: var(--muted);
}
.chip-have {
  color: var(--emerald, #2f7d4f);
  border-color: var(--emerald, #2f7d4f);
  background: color-mix(in srgb, var(--emerald, #2f7d4f) 10%, #fff);
}
.chip-gap {
  color: var(--muted);
  border-color: var(--rule);
}
.chip-nice {
  border-style: dashed;
  font-size: 0.6rem;
  opacity: 0.92;
}
.chip-sel {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--oxblood) 60%, transparent);
  font-weight: 700;
}
```

Note: `--emerald` is not currently a CSS variable (it's a Python constant). The fallback `#2f7d4f` in `color-mix`/`color` keeps the chip correct without touching `:root`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_dashboard_ui.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/dashboard/ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): skill-chip + meta-line helpers and control-desk CSS"
```

---

## Task 10: Shortlist control desk + rich cards

**Files:**

- Modify: `src/resume_tailor_harness/dashboard/pages.py:65-113` (`render_shortlist_page`)
- Test: manual (Streamlit page render; logic already covered by Tasks 7–9)

Streamlit page bodies aren't unit-tested in this codebase (the tests cover the pure helpers and CSS). This task wires the tested pieces together. Keep the existing card structure (meter | body columns, pinned Approve footer) and slot in the control desk + new card content.

- [ ] **Step 1: Add the control-desk renderer**

In `src/resume_tailor_harness/dashboard/pages.py`, add imports:

```python
import streamlit as st

from resume_tailor_harness.dashboard.filtering import (
    FilterState,
    apply_filters,
    available_skill_cloud,
    sort_rows,
)
from resume_tailor_harness.dashboard.ui import meta_line, skill_chip  # add to existing ui import
from resume_tailor_harness.profile.store import load_facts
from pathlib import Path
```

Add a helper that builds `FilterState` from widgets and renders the desk:

```python
_SORT_LABELS = {"fit": "Fit", "salary": "Salary", "recency": "Recency", "composite": "Composite ★"}
_PRESET_LABELS = {"balanced": "Balanced", "pay_first": "Pay-first", "freshest": "Freshest"}


def _control_desk(rows) -> FilterState:
    st.markdown('<div class="controldesk">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        salary_min = st.number_input("Min salary", min_value=0, step=10000, value=0, key="f_salary")
        fit_min = st.slider("Min fit", 0, 100, 0, key="f_fit")
    with c2:
        remote = set(st.multiselect("Remote", ["remote", "hybrid", "onsite"], key="f_remote"))
        sponsorship = set(st.multiselect("Sponsorship", ["offered", "silent", "denied"], key="f_sponsor"))
    with c3:
        seniority = set(st.multiselect("Seniority", ["junior", "mid", "senior", "staff", "principal"], key="f_sen"))
        employment = set(st.multiselect("Type", ["full_time", "contract", "internship", "part_time"], key="f_emp"))
    with c4:
        sort = st.selectbox("Sort by", list(_SORT_LABELS), format_func=_SORT_LABELS.get, key="f_sort")
        preset = "balanced"
        if sort == "composite":
            preset = st.radio("Preset", list(_PRESET_LABELS), format_func=_PRESET_LABELS.get,
                              horizontal=True, key="f_preset")

    # skill cloud
    cloud = available_skill_cloud(rows)
    options = [t.name for t in cloud]
    chosen = st.multiselect("Skills (any match)", options, key="f_skills")
    from resume_tailor_harness.tracking.match_gap import normalize_skill
    skills = {normalize_skill(s) for s in chosen}
    st.markdown("</div>", unsafe_allow_html=True)

    return FilterState(
        salary_min=salary_min or None,
        remote=remote, sponsorship=sponsorship, seniority=seniority,
        employment_type=employment, fit_min=fit_min or None,
        skills=skills, sort=sort, preset=preset,
    )
```

- [ ] **Step 2: Rewrite `render_shortlist_page` to use the desk + rich cards**

Replace the body of `render_shortlist_page` (keep the masthead + metric_row + empty-state, insert the desk, filter/sort, and enrich the card):

```python
def render_shortlist_page(session) -> None:
    facts = load_facts(_FACTS_PATH) if Path(_FACTS_PATH).exists() else None
    rows = shortlist_rows(session, facts=facts)
    avg = round(sum(r.fit_score or 0 for r in rows) / len(rows)) if rows else 0
    sponsored = sum(1 for r in rows if r.sponsorship_signal == "offered")

    masthead(
        "Human checkpoint",
        'The Short<span class="dot">·</span>list',
        "The cost gate before the premium tailoring step. Approve only the jobs worth the spend.",
    )
    metric_row([("Awaiting review", str(len(rows))), ("Avg fit", str(avg)),
                ("Sponsorship offered", str(sponsored))])

    if not rows:
        empty_state(
            "◇", "Nothing shortlisted yet",
            "Run <code>resume-tailor-harness discover</code> to score jobs and surface the keepers here.",
        )
        return

    state = _control_desk(rows)
    visible = sort_rows(apply_filters(rows, state), state)

    if not visible:
        empty_state("◇", "No jobs match these filters",
                    "Loosen a filter or clear the skill tags to see more.")
        return

    with st.container(key="cardgrid_shortlist"):
        for row in visible:
            with st.container(border=True):
                meter, body = st.columns([1, 4], vertical_alignment="center")
                with meter:
                    st.markdown(fit_block(row.fit_score), unsafe_allow_html=True)
                with body:
                    st.markdown(
                        f'<div class="card-title">{row.title or "—"}</div>'
                        f'<div class="card-meta">{row.company or "—"} · {row.location or "location n/a"} &nbsp; '
                        f'{status_badge(row.sponsorship_signal or "unknown")}</div>'
                        f'<div class="metaline">{meta_line(row)}</div>',
                        unsafe_allow_html=True,
                    )
                    if row.skills:
                        chips = "".join(
                            skill_chip(t, active=normalize_skill(t.name) in state.skills)
                            for t in row.skills
                        )
                        st.markdown(f'<div class="skills">{chips}</div>', unsafe_allow_html=True)
                    if row.fit_rationale:
                        st.markdown(f'<div class="rationale">{row.fit_rationale}</div>', unsafe_allow_html=True)
                if st.button("Approve for tailoring  →", key=f"approve-{row.job_id}"):
                    job = get_job(session, row.job_id)
                    if job is None:
                        st.error(f"Job #{row.job_id} no longer exists.")
                        st.rerun()
                        return
                    job.status = JobStatus.approved.value
                    save_job(session, job)
                    st.success(f"Approved {row.title or 'job'} #{row.job_id}.")
                    st.rerun()
```

Add `from resume_tailor_harness.tracking.match_gap import normalize_skill` to the imports if not already present.

- [ ] **Step 3: Verify import + smoke**

Run: `.venv/Scripts/python -c "import resume_tailor_harness.dashboard.pages"`
Expected: no error (module imports cleanly).
Run: `.venv/Scripts/python -m pytest tests/test_dashboard_app.py tests/test_dashboard_match_gap.py -q`
Expected: PASS (existing dashboard tests still green).

- [ ] **Step 4: Commit**

```bash
git add src/resume_tailor_harness/dashboard/pages.py
git commit -m "feat(dashboard): Shortlist control desk, metadata filters, skill-tag cloud, rich cards"
```

---

## Task 11: Pipeline board lean meta line

**Files:**

- Modify: `src/resume_tailor_harness/dashboard/pages.py:116-132` (`_render_pipeline_card`)
- Test: manual (covered by `PipelineRow` widening in Task 7)

- [ ] **Step 1: Add the lean meta line to the pipeline card**

In `_render_pipeline_card`, inside the `head` column, after the title/company markdown, append a compact line built from the new `PipelineRow` fields:

```python
        with head:
            sal = None
            if row.salary_min or row.salary_max:
                lo = f"{row.salary_min // 1000}k" if row.salary_min else None
                hi = f"{row.salary_max // 1000}k" if row.salary_max else None
                sal = "$" + (f"{lo}–{hi}" if lo and hi else (lo or hi))
            bits = [b for b in (sal, row.remote_policy, row.seniority) if b]
            lean = " · ".join(str(b).replace("_", " ") for b in bits)
            st.markdown(
                f'<div class="card-title">{row.title or "—"}</div>'
                f'<div class="card-meta">{row.company or "—"}</div>'
                + (f'<div class="metaline">{lean}</div>' if lean else ""),
                unsafe_allow_html=True,
            )
```

- [ ] **Step 2: Verify**

Run: `.venv/Scripts/python -c "import resume_tailor_harness.dashboard.pages"`
Expected: clean import.
Run: `.venv/Scripts/python -m pytest tests/test_tracking_queries.py tests/test_dashboard_app.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/resume_tailor_harness/dashboard/pages.py
git commit -m "feat(dashboard): lean salary/remote/seniority line on pipeline cards"
```

---

## Task 12: Full suite + lint + manual headless verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: all PASS (no regressions; new tests green).

- [ ] **Step 2: Lint**

Run: `.venv/Scripts/python -m ruff check`
Expected: no errors. Fix any reported issues and re-run.

- [ ] **Step 3: Manual headless dashboard check**

Run: `.venv/Scripts/python -m streamlit run src/resume_tailor_harness/dashboard/app.py --server.headless true`
Then in a browser at the printed URL, on a DB that has shortlisted jobs:

- Confirm the control desk renders below the masthead with all filters + sort + skill cloud.
- Confirm cards show the meta line + skill chips (emerald = covered, ringed = actively filtered, `+` prefix on nice-to-haves).
- Toggle a skill tag, a seniority filter, and the salary slider; confirm the visible set narrows correctly.
- Switch Sort → Composite; confirm the three presets appear and reorder cards.
- Confirm the Pipeline board shows the single lean meta line and no filters.
  Stop with Ctrl-C.

- [ ] **Step 4: Final commit (if lint produced fixes)**

```bash
git add -A
git commit -m "chore: lint fixes for metadata filtering feature"
```

---

## Self-Review Notes

- **Spec coverage:** §3.1 extraction → Tasks 1–2; §3.2 posted_at → Tasks 3–5; §3.3 re-extract → Task 6; §3.4 queries/coverage → Task 7; §3.5 filtering/composite → Task 8; §3.6 presentation → Tasks 9–11; §3.7 ui helpers → Task 9. §4 edge cases: missing facts (Task 7 test), empty result (Tasks 8 + 10), all-null meta (Task 9 `meta_line` test), composite all-null neutral (Task 8 test). §5 testing → per-task tests. §6 YAGNI honored (no SQL columns, no sliders, no pipeline filters). LinkedIn `posted_at` deferred to null (documented in Task 5) — consistent with spec's null tolerance.
- **Type consistency:** `ShortlistRow`/`SkillTag` defined in Task 7 are imported unchanged by Tasks 8–10. `FilterState` fields defined in Task 8 are used verbatim in Task 10's `_control_desk`. `skill_chip`/`meta_line` signatures (Task 9) match their call sites (Task 10/11). `reextract(session, agent)` (Task 6) matches its CLI call.
- **No placeholders:** every code step shows complete code; test steps show real assertions.
