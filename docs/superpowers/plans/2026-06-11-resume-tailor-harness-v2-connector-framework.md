# Résumé Tailor Harness v2 — Connector Framework + Cross-Source Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LinkedIn-shaped `JobSource` seam with a one-shot `Connector.fetch(search, limit=None) -> list[RawJob]` interface, add cross-source deduplication via a normalized `(company, title)` key, and refactor the existing LinkedIn scraper onto the new seam — so every later connector (Greenhouse, Adzuna, RemoteOK, …) inherits correct source attribution and dedupe for free.

**Architecture:** This is the **backbone plan** (Plan 1 of 6) for v2 — design spec `docs/superpowers/specs/2026-06-11-resume-tailor-harness-v2-connectors-design.md`. It builds three deep modules behind small interfaces: (1) the `Connector` **seam** with `RawJob` as its single output type; (2) a dedup module whose `compute_dedup_key` + extended `find_existing` concentrate _all_ cross-source identity logic in the tracking layer (so connectors never re-solve dedupe — the **deletion test**: push this into each connector and the complexity reappears N times); (3) `ingest_jobs`, which concentrates "loop → skip-empty → dedupe → attribute source → count" in one place. LinkedIn becomes the first **adapter** on the seam; Plan 2 adds the second, making it a real seam.

**Tech Stack:** Python 3.13, uv, SQLModel/SQLAlchemy, Typer, pytest. **No new dependencies** — reuses the existing `httpx`/Playwright/`beautifulsoup4` stack. (API/feed connectors and their deps arrive in Plan 2.)

**Depends on:** v1 merged to `main` (`discovery.ingest.add_job`, `tracking.repository.find_existing`, `discovery.scraper.parser`, `discovery.scraper.linkedin`, `db.init_db`). Working tree clean.

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Architecture notes (the two lenses)

**Deepening (improve-codebase-architecture):**

- The `Connector` seam has a tiny interface (`name` + `fetch`) hiding arbitrary per-source behavior (HTML scraping, JSON paging, RSS) — high **leverage**.
- Dedup **locality**: `compute_dedup_key` lives once in `tracking/dedup.py`, consumed by `add_job` (write) and `find_existing` (lookup). A future change to identity rules touches one file.
- LinkedIn's browser I/O is isolated into two thin seam methods (`_search_html`, `_detail_html`) so `fetch`'s composition logic becomes **testable without a browser** — coverage the v1 driver lacked.

**Restraint (karpathy-guidelines) — what this plan deliberately does NOT build:**

- No connector **registry** / `build_connectors` and no `connectors.yaml` loader yet — they have no consumer until real connectors exist (Plan 2/3). Building them now would be speculative.
- `RawJob` carries exactly the six fields `add_job` already consumes — no "flexible" extras.
- `ScrapedCard` is **kept** as LinkedIn's internal pre-JD representation; we don't churn the parser or its fixtures. Every changed line traces to this plan's goal.

---

## File Structure

```
src/resume_tailor_harness/discovery/connectors/
  __init__.py                 # CREATE — package marker
  base.py                     # CREATE — RawJob dataclass + Connector Protocol
src/resume_tailor_harness/tracking/
  dedup.py                    # CREATE — normalize + compute_dedup_key (pure)
  migrate.py                  # CREATE — ensure_dedup_key_column (SQLite ALTER + backfill)
  tables.py                   # MODIFY — add Job.dedup_key (indexed)
  repository.py               # MODIFY — find_existing checks dedup_key
src/resume_tailor_harness/discovery/
  ingest.py                   # MODIFY — add_job computes dedup_key; add ingest_jobs()
  scraper/linkedin.py         # MODIFY — LinkedInScraper implements Connector.fetch
  scraper/ingest.py           # DELETE — JobSource + ingest_scraped superseded
src/resume_tailor_harness/db.py        # MODIFY — init_db runs ensure_dedup_key_column
src/resume_tailor_harness/cli.py       # MODIFY — scrape uses connector.fetch + ingest_jobs
tests/
  test_connectors_base.py     # CREATE
  test_dedup.py               # CREATE
  test_migrate.py             # CREATE
  test_discovery_ingest.py    # MODIFY — append cross-source dedup cases
  test_ingest_jobs.py         # CREATE — replaces test_scraper_ingest.py
  test_scraper_ingest.py      # DELETE — JobSource/ingest_scraped removed
  test_linkedin_connector.py  # CREATE
  test_cli_scrape.py          # MODIFY — patch connector + ingest_jobs
```

---

## Task 1: `RawJob` + `Connector` protocol

**Files:**

- Create: `src/resume_tailor_harness/discovery/connectors/__init__.py`, `src/resume_tailor_harness/discovery/connectors/base.py`
- Test: `tests/test_connectors_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_base.py`:

```python
from resume_tailor_harness.discovery.connectors.base import Connector, RawJob
from resume_tailor_harness.discovery.search_config import SearchConfig


def test_rawjob_carries_its_own_source():
    job = RawJob(
        source="greenhouse",
        url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        title="Backend Engineer",
        location="Remote",
        jd_text="We are hiring.",
    )
    assert job.source == "greenhouse"
    assert job.jd_text == "We are hiring."


def test_connector_protocol_accepts_a_conforming_object():
    class _Fake:
        name = "fake"

        def fetch(self, search, limit=None):
            return [RawJob("fake", None, "Acme", "Eng", None, "jd")]

    fake: Connector = _Fake()  # structural conformance
    jobs = fake.fetch(SearchConfig())
    assert jobs[0].source == "fake"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.connectors'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/discovery/connectors/__init__.py`:

```python
"""Job-source connectors: a one-shot fetch() seam shared by scrapers, APIs, and feeds."""
```

Create `src/resume_tailor_harness/discovery/connectors/base.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from resume_tailor_harness.discovery.search_config import SearchConfig


@dataclass
class RawJob:
    """A single job as a connector emits it — fully formed, ready for ingest.

    ``source`` is carried by the job itself (not assumed by the ingester), so a
    mix of connectors attributes each row correctly.
    """

    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str


class Connector(Protocol):
    """A job source. ``name`` labels every RawJob it emits.

    ``fetch`` is one-shot: it returns fully-formed RawJobs (scrapers do their
    internal multi-step work; APIs/feeds do a single call). ``limit`` caps how
    many postings this run produces (politeness / cost), or None for no cap.
    """

    name: str

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_base.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/ tests/test_connectors_base.py
git commit -m "feat(connectors): RawJob + Connector seam" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: dedup key (pure normalization)

**Files:**

- Create: `src/resume_tailor_harness/tracking/dedup.py`
- Test: `tests/test_dedup.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dedup.py`:

```python
from resume_tailor_harness.tracking.dedup import compute_dedup_key


def test_dedup_key_ignores_case_punctuation_and_seniority():
    a = compute_dedup_key("Acme, Inc.", "Senior Backend Engineer")
    b = compute_dedup_key("acme inc", "Backend Engineer")
    assert a == b == "acme inc|backend engineer"


def test_dedup_key_strips_various_seniority_prefixes():
    base = compute_dedup_key("Acme", "Engineer")
    assert compute_dedup_key("Acme", "Sr. Engineer") == base
    assert compute_dedup_key("Acme", "Staff Engineer") == base
    assert compute_dedup_key("Acme", "Senior Staff Engineer") == base
    assert compute_dedup_key("Acme", "Junior Engineer") == base


def test_dedup_key_none_when_a_side_is_missing():
    assert compute_dedup_key(None, "Engineer") is None
    assert compute_dedup_key("Acme", None) is None
    assert compute_dedup_key("Acme", "   ") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.tracking.dedup'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/tracking/dedup.py`:

```python
import re

_SENIORITY = re.compile(
    r"^(?:(?:sr\.?|senior|jr\.?|junior|lead|staff|principal|entry[- ]level)\s+)+",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with a single space, trim."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def _normalize_title(title: str) -> str:
    return _normalize(_SENIORITY.sub("", title.strip()))


def compute_dedup_key(company: str | None, title: str | None) -> str | None:
    """A normalized ``company|title`` identity for cross-source dedupe.

    Returns ``None`` when either side is missing, so callers fall back to the
    URL / exact-JD signals instead of collapsing unrelated rows.
    """
    if not company or not company.strip() or not title or not title.strip():
        return None
    return f"{_normalize(company)}|{_normalize_title(title)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dedup.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/dedup.py tests/test_dedup.py
git commit -m "feat(dedup): normalized company+title dedup key" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: wire `dedup_key` through the Job model, `find_existing`, and `add_job`

**Files:**

- Modify: `src/resume_tailor_harness/tracking/tables.py` (Job model), `src/resume_tailor_harness/tracking/repository.py` (`find_existing`), `src/resume_tailor_harness/discovery/ingest.py` (`add_job`)
- Test: `tests/test_discovery_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discovery_ingest.py`:

```python
def test_add_job_dedupes_same_company_title_across_sources():
    # Same posting from an ATS and an aggregator: different url + jd text, same identity.
    with _session() as s:
        first = add_job(
            s, source="greenhouse", jd_text="full canonical jd",
            url="http://gh/1", company="Acme Corp", title="Senior Backend Engineer",
        )
        dup = add_job(
            s, source="adzuna", jd_text="truncated jd...",
            url="http://adz/2", company="acme corp", title="Backend Engineer",
        )
        assert first is not None
        assert dup is None  # collapsed by dedup_key


def test_add_job_keeps_distinct_when_company_or_title_missing():
    with _session() as s:
        a = add_job(s, source="manual", jd_text="text one")
        b = add_job(s, source="manual", jd_text="text two")
        assert a is not None and b is not None  # dedup_key is None → no false merge
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_ingest.py -v`
Expected: FAIL on `test_add_job_dedupes_same_company_title_across_sources` — `dup` is a Job, not None (no dedup_key yet). (`AttributeError` on `Job.dedup_key` is also acceptable depending on order.)

- [ ] **Step 3: Add the column to the Job model**

In `src/resume_tailor_harness/tracking/tables.py`, inside `class Job`, add `dedup_key` immediately after the `location` field:

```python
    location: str | None = None
    dedup_key: str | None = Field(default=None, index=True)
    jd_text: str = ""
```

- [ ] **Step 4: Extend `find_existing` to check the dedup key**

In `src/resume_tailor_harness/tracking/repository.py`, replace the whole `find_existing` function with:

```python
def find_existing(
    session: Session, url: str | None, jd_text: str, dedup_key: str | None = None
) -> Job | None:
    """Return a matching job for dedupe: by URL, else identical JD text, else dedup_key."""
    if url:
        by_url = session.exec(select(Job).where(Job.url == url)).first()
        if by_url is not None:
            return by_url
    if jd_text:
        by_jd = session.exec(select(Job).where(Job.jd_text == jd_text)).first()
        if by_jd is not None:
            return by_jd
    if dedup_key:
        return session.exec(select(Job).where(Job.dedup_key == dedup_key)).first()
    return None
```

- [ ] **Step 5: Compute and store the key in `add_job`**

In `src/resume_tailor_harness/discovery/ingest.py`, add the import and update `add_job`:

```python
from resume_tailor_harness.tracking.dedup import compute_dedup_key
```

Then, inside `add_job`, replace the body from the `jd_text = jd_text.strip()` line through the `Job(...)` construction with:

```python
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
        status=JobStatus.raw.value,
    )
    return save_job(session, job)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_discovery_ingest.py -v`
Expected: PASS (all original + 2 new tests).

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/tracking/tables.py src/resume_tailor_harness/tracking/repository.py src/resume_tailor_harness/discovery/ingest.py tests/test_discovery_ingest.py
git commit -m "feat(dedup): cross-source dedupe via Job.dedup_key" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: SQLite migration — add + backfill `dedup_key` on existing DBs

> `SQLModel.metadata.create_all` only creates missing _tables_, never missing _columns_. Existing `data/resume_tailor_harness.db` files would break on `dedup_key`. This task adds an idempotent column-ensure + backfill and wires it into `init_db` so every run self-heals — without touching the user's tracked applications.

**Files:**

- Create: `src/resume_tailor_harness/tracking/migrate.py`
- Modify: `src/resume_tailor_harness/db.py`
- Test: `tests/test_migrate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate.py`:

```python
from sqlalchemy import text
from sqlmodel import create_engine

from resume_tailor_harness.db import init_db
from resume_tailor_harness.tracking.migrate import ensure_dedup_key_column


def test_ensure_adds_column_and_backfills_old_jobs_table():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # Simulate a pre-v2 jobs table with no dedup_key column.
        conn.execute(text(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR, "
            "company VARCHAR, title VARCHAR, jd_text VARCHAR)"
        ))
        conn.execute(text(
            "INSERT INTO jobs (id, source, company, title, jd_text) "
            "VALUES (1, 'manual', 'Acme Corp', 'Senior Backend Engineer', 'jd')"
        ))

    ensure_dedup_key_column(engine)

    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        assert "dedup_key" in cols
        indexes = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
        assert "ix_jobs_dedup_key" in indexes
        key = conn.execute(text("SELECT dedup_key FROM jobs WHERE id = 1")).scalar()
        assert key == "acme corp|backend engineer"


def test_ensure_is_noop_on_current_schema():
    engine = create_engine("sqlite://")
    init_db(engine)            # creates jobs WITH dedup_key (and ensures once)
    ensure_dedup_key_column(engine)  # second call must not error or change anything
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.tracking.migrate'`.

- [ ] **Step 3: Implement the migration**

Create `src/resume_tailor_harness/tracking/migrate.py`:

```python
from sqlalchemy import text
from sqlalchemy.engine import Engine

from resume_tailor_harness.tracking.dedup import compute_dedup_key


def ensure_dedup_key_column(engine: Engine) -> None:
    """Idempotently add ``jobs.dedup_key`` and backfill it from company/title.

    Safe to call on every startup: no-op once the column exists and all rows
    are keyed. Does nothing if the ``jobs`` table is absent (fresh DB before
    ``create_all``).
    """
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:  # table doesn't exist yet
            return
        if "dedup_key" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN dedup_key VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_dedup_key ON jobs (dedup_key)"))
        rows = conn.execute(
            text("SELECT id, company, title FROM jobs WHERE dedup_key IS NULL")
        ).fetchall()
        for row_id, company, title in rows:
            key = compute_dedup_key(company, title)
            if key:
                conn.execute(
                    text("UPDATE jobs SET dedup_key = :k WHERE id = :i"),
                    {"k": key, "i": row_id},
                )
```

- [ ] **Step 4: Wire it into `init_db`**

In `src/resume_tailor_harness/db.py`, add the import and call after `create_all`:

```python
from resume_tailor_harness.tracking.migrate import ensure_dedup_key_column
```

```python
def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrate.py tests/test_db.py -v`
Expected: PASS (2 new + existing db tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/tracking/migrate.py src/resume_tailor_harness/db.py tests/test_migrate.py
git commit -m "feat(dedup): idempotent dedup_key column migration + backfill" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `ingest_jobs` orchestrator + remove `ingest_scraped`/`JobSource`

**Files:**

- Modify: `src/resume_tailor_harness/discovery/ingest.py` (add `ingest_jobs`)
- Delete: `src/resume_tailor_harness/discovery/scraper/ingest.py`, `tests/test_scraper_ingest.py`
- Test: `tests/test_ingest_jobs.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_jobs.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.ingest import ingest_jobs
from resume_tailor_harness.tracking.repository import jobs_by_status
from resume_tailor_harness.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _raw(source, n, company, title, jd):
    return RawJob(source, f"https://{source}/{n}", company, title, "Remote", jd)


def test_ingest_jobs_inserts_and_counts_per_source():
    raws = [
        _raw("greenhouse", 1, "Acme", "Backend Engineer", "JD A"),
        _raw("adzuna", 2, "Beta", "Platform Engineer", "JD B"),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1, "adzuna": 1}
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert {j.source for j in rows} == {"greenhouse", "adzuna"}


def test_ingest_jobs_skips_empty_jd():
    with _session() as s:
        assert ingest_jobs(s, [_raw("adzuna", 1, "Acme", "Eng", "   ")]) == {}


def test_ingest_jobs_dedupes_same_posting_across_sources():
    # Ordered ATS -> aggregator -> linkedin, as `pull` will run them.
    raws = [
        RawJob("greenhouse", "https://gh/1", "Acme Corp", "Senior Backend Engineer", "Remote", "Full canonical JD"),
        RawJob("adzuna", "https://adz/9", "acme corp", "Backend Engineer", "Remote", "Truncated JD..."),
        RawJob("linkedin", "https://li/7", "Acme Corp", "Sr. Backend Engineer", "Remote", "LinkedIn JD"),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1}  # canonical (first) wins; the rest collapse
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "greenhouse"
        assert rows[0].jd_text == "Full canonical JD"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest_jobs.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_jobs' from 'resume_tailor_harness.discovery.ingest'`.

- [ ] **Step 3: Implement `ingest_jobs`**

In `src/resume_tailor_harness/discovery/ingest.py`, add at the top:

```python
from collections import Counter
from typing import Iterable

from resume_tailor_harness.discovery.connectors.base import RawJob
```

Add at the end of the file:

```python
def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Insert RawJobs through the shared normalize/dedupe path. Returns per-source added counts.

    Empty JD text is skipped; duplicates (URL, exact JD text, or dedup_key) are dropped.
    Each row is attributed to ``raw.source`` — no source is assumed.
    """
    added: Counter[str] = Counter()
    for raw in raw_jobs:
        if not raw.jd_text.strip():
            continue
        job = add_job(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
        )
        if job is not None:
            added[raw.source] += 1
    return dict(added)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest_jobs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Delete the superseded `JobSource`/`ingest_scraped`**

```bash
git rm src/resume_tailor_harness/discovery/scraper/ingest.py tests/test_scraper_ingest.py
```

(Task 6 removes the last importer — the LinkedIn driver — and Task 7 removes the CLI import. The `scrape` command still references the old import until then, so do NOT run the full suite yet; the per-file runs above are green.)

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/discovery/ingest.py tests/test_ingest_jobs.py
git commit -m "feat(connectors): ingest_jobs orchestrator; drop JobSource/ingest_scraped" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: refactor the LinkedIn scraper onto the `Connector` seam

> The pure parsers (`parse_search_cards`, `parse_job_detail`) and their fixtures are **unchanged**. Only the driver's outer shape changes: `search()`+`fetch_jd()` → one `fetch()`, with browser I/O isolated behind `_search_html`/`_detail_html` so `fetch`'s composition is unit-testable against the existing HTML fixtures (no browser in CI).

**Files:**

- Modify: `src/resume_tailor_harness/discovery/scraper/linkedin.py`
- Test: `tests/test_linkedin_connector.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_linkedin_connector.py`:

```python
from pathlib import Path

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.scraper.linkedin import LinkedInScraper
from resume_tailor_harness.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


class _FakeBrowserScraper(LinkedInScraper):
    """Override the browser I/O seam with saved fixtures — no Playwright."""

    def _search_html(self, search):
        return (FIXTURES / "search.html").read_text(encoding="utf-8")

    def _detail_html(self, card):
        return (FIXTURES / "job.html").read_text(encoding="utf-8")


def test_linkedin_fetch_returns_rawjobs_attributed_to_linkedin():
    jobs = _FakeBrowserScraper().fetch(SearchConfig())
    assert len(jobs) == 2
    assert all(isinstance(j, RawJob) for j in jobs)
    assert all(j.source == "linkedin" for j in jobs)
    assert jobs[0].title == "Senior Backend Engineer"
    assert "5+ years of Python." in jobs[0].jd_text


def test_linkedin_fetch_respects_limit():
    assert len(_FakeBrowserScraper().fetch(SearchConfig(), limit=1)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_linkedin_connector.py -v`
Expected: FAIL — `AttributeError: 'LinkedInScraper' object has no attribute '_search_html'` (or `fetch`).

- [ ] **Step 3: Rewrite the driver**

Replace the entire contents of `src/resume_tailor_harness/discovery/scraper/linkedin.py` with:

```python
import time
import urllib.parse

from playwright.sync_api import sync_playwright

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.scraper.models import ScrapedCard
from resume_tailor_harness.discovery.scraper.parser import parse_job_detail, parse_search_cards
from resume_tailor_harness.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


def _search_url(config: SearchConfig) -> str:
    params: dict[str, str] = {}
    terms = list(dict.fromkeys([*config.titles, *config.keywords]))
    if terms:
        params["keywords"] = " ".join(terms)
    if config.locations:
        params["location"] = config.locations[0]
    if not params:
        return _SEARCH_URL
    return _SEARCH_URL + "?" + urllib.parse.urlencode(params)


class LinkedInScraper:
    """Connector over a persistent, logged-in burner LinkedIn profile.

    First run: a browser window opens; log in by hand once. The session persists
    in ``user_data_dir`` for subsequent runs. Pacing is deliberate and capped.
    Browser I/O lives in ``_search_html``/``_detail_html`` so ``fetch`` stays
    testable; those two methods are the only un-CI-tested, manually-maintained part.
    """

    name = "linkedin"

    def __init__(
        self,
        user_data_dir: str = ".linkedin_profile",
        headless: bool = False,
        pace_seconds: float = 2.0,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.pace_seconds = pace_seconds

    def _content_for_url(self, url: str, *, scroll: bool = False) -> str:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.user_data_dir, headless=self.headless
            )
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(self.pace_seconds)
                if scroll:
                    page.mouse.wheel(0, 4000)
                    time.sleep(self.pace_seconds)
                return page.content()
            finally:
                context.close()

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        cards = parse_search_cards(self._search_html(search))
        if limit is not None:
            cards = cards[:limit]
        jobs: list[RawJob] = []
        for card in cards:
            jd_text = parse_job_detail(self._detail_html(card)).strip()
            if not jd_text:
                continue
            jobs.append(
                RawJob(
                    source=self.name,
                    url=card.url,
                    company=card.company,
                    title=card.title,
                    location=card.location,
                    jd_text=jd_text,
                )
            )
        return jobs

    # --- browser I/O seam (overridden in tests; never exercised in CI) ---
    def _search_html(self, search: SearchConfig) -> str:
        return self._content_for_url(_search_url(search), scroll=True)

    def _detail_html(self, card: ScrapedCard) -> str:
        if not card.url:
            return ""
        return self._content_for_url(card.url)


def build_linkedin_scraper() -> LinkedInScraper:
    settings = get_settings()
    return LinkedInScraper(
        user_data_dir=getattr(settings, "linkedin_user_data_dir", ".linkedin_profile")
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_linkedin_connector.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Confirm it imports without launching a browser**

Run: `uv run python -c "from resume_tailor_harness.discovery.scraper.linkedin import LinkedInScraper, build_linkedin_scraper; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/discovery/scraper/linkedin.py tests/test_linkedin_connector.py
git commit -m "refactor(scraper): LinkedIn implements Connector.fetch" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: update the `scrape` CLI command + full suite

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_scrape.py`

- [ ] **Step 1: Rewrite the test**

Replace the entire contents of `tests/test_cli_scrape.py` with:

```python
from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.discovery.connectors.base import RawJob

runner = CliRunner()


class _FakeConnector:
    name = "linkedin"

    def fetch(self, search, limit=None):
        return [RawJob("linkedin", "https://li/1", "Acme", "Engineer", "Remote", "a real jd")]


def test_scrape_command_ingests_via_connector(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "build_linkedin_scraper", lambda: _FakeConnector())

    result = runner.invoke(cli.app, ["scrape", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Added 1" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_scrape.py -v`
Expected: FAIL — `ImportError`/`AttributeError` from the still-present `from resume_tailor_harness.discovery.scraper.ingest import ingest_scraped` in `cli.py` (the module was deleted in Task 5).

- [ ] **Step 3: Update the CLI imports**

In `src/resume_tailor_harness/cli.py`:

- Delete the line: `from resume_tailor_harness.discovery.scraper.ingest import ingest_scraped`
- Change `from resume_tailor_harness.discovery.ingest import add_job` to:
  `from resume_tailor_harness.discovery.ingest import add_job, ingest_jobs`

(`from resume_tailor_harness.discovery.scraper.linkedin import build_linkedin_scraper` stays.)

- [ ] **Step 4: Update the `scrape` command**

In `src/resume_tailor_harness/cli.py`, replace the body of `scrape_cmd` with:

```python
    """Scrape LinkedIn for jobs matching search.yaml and insert them as raw jobs."""
    config = load_search_config(search)
    connector = build_linkedin_scraper()
    engine = _engine(db_url)
    with get_session(engine) as session:
        added = ingest_jobs(session, connector.fetch(config, limit=limit))
    typer.echo(f"Scrape complete. Added {sum(added.values())} new job(s).")
```

- [ ] **Step 5: Run the focused test, then the full suite**

Run: `uv run pytest tests/test_cli_scrape.py -v`
Expected: PASS (1 test).

Run: `uv run pytest -q`
Expected: ALL pass — the v2 backbone is green and the v1 pipeline still works end-to-end through the new seam. (No references to `ingest_scraped`, `JobSource`, or `ScrapedCard`-as-output remain.)

Run: `rg -n "ingest_scraped|JobSource" src tests`
Expected: no output (`rg` exits 1 when there are no matches; that is expected).

Run: `uv run resume-tailor-harness scrape --help`
Expected: help text, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_scrape.py
git commit -m "feat(connectors): scrape runs via Connector.fetch + ingest_jobs" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.1, §5.3, Decisions #2/#4):**

- One-shot `Connector.fetch(search, limit=None) -> list[RawJob]` with `RawJob.source` — Task 1 (fixes the v1 `source="linkedin"` hardcode, regression-tested in Task 5).
- `ingest_jobs` replacing `ingest_scraped` — Task 5.
- Dedup: `dedup_key` + `normalize` + extended `find_existing` + backfill — Tasks 2–4. Canonical-copy-via-ordering is asserted by `test_ingest_jobs_dedupes_same_posting_across_sources` (Task 5).
- LinkedIn refactored onto the seam, parsers/fixtures untouched — Task 6.
- **Deliberately deferred to Plan 2/3 (documented in Architecture notes):** `connectors.yaml` loader + `build_connectors` registry. No spec requirement for _this_ plan is left unimplemented.

**Placeholder scan:** none — every code step shows complete code; every run step shows the exact command + expected result. Task 5 Step 5 is a real `git rm`, not a placeholder.

**Type consistency:** `RawJob(source, url, company, title, location, jd_text)` is constructed identically in Tasks 1, 5, 6, 7. `Connector.fetch(search, limit=None) -> list[RawJob]` matches `LinkedInScraper.fetch`, `_FakeConnector.fetch`, and the CLI call. `compute_dedup_key(company, title) -> str | None` matches its use in `add_job` (Task 3) and `migrate` (Task 4). `find_existing(session, url, jd_text, dedup_key=None)` matches the `add_job` call. `ingest_jobs(session, raw_jobs) -> dict[str,int]` matches the test and CLI usage.

**Ordering caveat (intentional):** the full suite is only run at Task 7 — between Tasks 5 and 7 the `cli.py` import of the deleted `ingest_scraped` is temporarily dangling, so per-file test runs are used until the CLI is updated. Called out in Task 5 Step 5.

---

## Roadmap — the remaining v2 plans (this is Plan 1 of 6)

Per the spec's build sequence (§10), each is its own plan file, same TDD style. The spine is strict; the leaves are independent.

1. **Reference connectors** — `connectors.yaml` + `ConnectorsConfig`, `build_connectors` registry, and **Greenhouse + Adzuna + RemoteOK** connectors (each a pure JSON→`RawJob` mapper over saved fixtures, no network in CI). _Depends on Plan 1._
2. **`pull` + `sources`** — ordered multi-connector run (ATS→feeds→aggregator→LinkedIn), per-source count table, connector telemetry/health. `scrape` becomes a thin LinkedIn-only alias. _Depends on Plan 2._
3. **Cover letters** — `CoverLetterContent`, fact-locked draft + light review, `cover_letter.typ`, `cover_letters` table, `cover-letter` command. _Depends on Plan 1 only._
4. **Gmail auto-status** — read-only Gmail client, email→application matching, rules+cheap-LLM classification, `sync-status` proposing transitions. _Depends on v1 tracking only._
5. **Application analytics** — dashboard page: response/interview/offer rates by source and fit-score band. _Depends on v1 tracking only._

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-tailor-harness-v2-connector-framework.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session via `executing-plans`, batched with review checkpoints.

After this backbone is green, Plan 2 (reference connectors) is the next file to write.
