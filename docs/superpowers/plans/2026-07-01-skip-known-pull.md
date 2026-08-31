# Skip-Known-Jobs Pull Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip the expensive per-job work (Workday/Tesla N+1 detail GET, Adzuna browser render) for jobs already known from a same-or-higher-tier source, without ever skipping an upgrade.

**Architecture:** A `KnownJobsIndex` is built once per pull from a single DB query over active jobs. It produces a pure `skip_seen(RawJob) -> bool` predicate that mirrors `merge.decide()`'s `Skip` branch (skip only when the incoming source cannot beat the existing row on tier). The predicate is threaded — default `None` = today's behavior — into `harvest_detailed` (applied after the title gate, before the detail fetch) and into Adzuna enrichment (before the browser render). The runner builds the predicate and passes it to every `connector.fetch`; a `--refresh` CLI flag disables it. Connectors never touch the DB — the predicate is a closure built by the runner.

**Tech Stack:** Python 3, SQLModel/SQLAlchemy, httpx, Typer, pytest. Offline test suite (browser + LLM faked).

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline — no API key/network).
- Lint: `ruff check`.
- Skip predicate must mirror `merge.decide()`'s Skip rule exactly: skip iff a known row matches **and** `source_rank(incoming) >= source_rank(existing)`. Never skip when the incoming source is strictly higher-tier (the upgrade path).
- Identity match: exact `url`, **or** `compute_dedup_key(company, title)` **with** a matching normalized location. No schema change, no new columns.
- Known-index query filters `archived_at IS NULL` (mirrors `find_existing`).
- Connectors stay DB-free: they accept a `skip_seen` closure, never a `Session`.
- Default pull skips known jobs; `resume-tailor-harness pull --refresh` bypasses skip entirely.

## Review corrections (2026-07-01)

This section supersedes conflicting task snippets below.

- Define `SkipSeen = Callable[[RawJob], bool]` in `connectors/base.py`, the
  dependency-neutral interface module. `known_jobs.py` implements that contract;
  connector modules must not import a DB-aware orchestration module merely for a
  type alias.
- `KnownJobsIndex` stores the best (lowest) source rank for each identity rather
  than relying on database row order when multiple active rows share a key.
- Normalize exact URLs by trimming surrounding whitespace before indexing and
  lookup. Do not otherwise rewrite URLs because ingest currently uses exact URL
  identity.
- Adzuna must relevance-gate without applying `limit`, remove known rows, and only
  then cap to `limit`; limiting before skip can return fewer unknown jobs even when
  later candidates are available.
- The HTTP pull contract needs the design-required bypass too: add
  `refresh: bool = False` to `PullParams`, pass `skip_known=not params.refresh`,
  test the route, and regenerate OpenAPI/TypeScript contracts.
- Update every connector implementation and every runner-facing test double to
  accept the additive `skip_seen: SkipSeen | None = None` keyword. Direct calls
  that omit it remain backward compatible.
- A skipped prefetch row never reaches ingest, so it is intentionally absent from
  `PullReport.skipped`; that field continues to count ingest merge skips only.

---

### Task 1: `KnownJobsIndex` + `skip_seen` predicate

**Files:**

- Create: `src/resume_tailor_harness/discovery/known_jobs.py`
- Test: `tests/test_known_jobs.py`

**Interfaces:**

- Consumes: `RawJob` and `SkipSeen` (`discovery/connectors/base.py`), `source_rank` (`discovery/source_tier.py`), `compute_dedup_key` (`tracking/dedup.py`), `Job` (`tracking/tables.py`).
- Produces:
  - `KnownJobsIndex` with `.match(url, company, title, location) -> KnownJob | None`
  - `build_known_index(session: Session) -> KnownJobsIndex`
  - `make_skip_seen(index: KnownJobsIndex) -> SkipSeen`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_known_jobs.py
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.known_jobs import (
    KnownJobsIndex,
    build_known_index,
    make_skip_seen,
)
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _raw(source, url=None, company="Acme", title="Backend Engineer", location="Remote"):
    return RawJob(source, url, company, title, location, jd_text="")


def _persist(session, source, url, company, title, location):
    save_job(
        session,
        Job(
            source=source, url=url, company=company, title=title, location=location,
            jd_text="jd", dedup_key=compute_dedup_key(company, title),
            status=JobStatus.raw.value,
        ),
    )


def test_skip_seen_matches_by_url():
    with _session() as s:
        _persist(s, "greenhouse", "https://gh/1", "Acme", "Backend Engineer", "Remote")
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("greenhouse", url="https://gh/1")) is True


def test_skip_seen_matches_by_dedup_key_and_location():
    with _session() as s:
        _persist(s, "greenhouse", None, "Acme", "Backend Engineer", "Remote")
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("greenhouse", url=None, location="Remote")) is True


def test_skip_seen_respects_location_on_dedup_key_collapse():
    # Same title, different city -> same dedup_key but must NOT skip.
    with _session() as s:
        _persist(s, "workday", None, "GM", "Software Engineer", "Austin, TX")
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("workday", url=None, company="GM",
                         title="Software Engineer", location="Detroit, MI")) is False


def test_skip_seen_allows_upgrade_from_higher_tier():
    # Known only from an aggregator; a canonical pull must NOT be skipped.
    with _session() as s:
        _persist(s, "adzuna", "https://x/1", "Acme", "Backend Engineer", "Remote")
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("greenhouse", url="https://x/1")) is False


def test_skip_seen_skips_same_and_lower_tier():
    with _session() as s:
        _persist(s, "greenhouse", "https://gh/1", "Acme", "Backend Engineer", "Remote")
        skip = make_skip_seen(build_known_index(s))
        # Equal tier (canonical vs canonical) -> skip; aggregator vs canonical -> skip.
        assert skip(_raw("lever", url="https://gh/1")) is True
        assert skip(_raw("adzuna", url="https://gh/1")) is True


def test_skip_seen_false_for_unknown_job():
    with _session() as s:
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("greenhouse", url="https://gh/999")) is False


def test_archived_jobs_are_not_known():
    from resume_tailor_harness.tracking.tables import utcnow
    with _session() as s:
        job = Job(
            source="greenhouse", url="https://gh/1", company="Acme",
            title="Backend Engineer", location="Remote", jd_text="jd",
            dedup_key=compute_dedup_key("Acme", "Backend Engineer"),
            status=JobStatus.raw.value, archived_at=utcnow(),
        )
        save_job(s, job)
        skip = make_skip_seen(build_known_index(s))
        assert skip(_raw("greenhouse", url="https://gh/1")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_known_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: resume_tailor_harness.discovery.known_jobs`.

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/discovery/known_jobs.py
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from sqlmodel import Session, select

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.source_tier import source_rank
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.tables import Job

SkipSeen = Callable[[RawJob], bool]


def _norm_loc(location: str | None) -> str:
    return (location or "").strip().lower()


@dataclass(frozen=True)
class KnownJob:
    """The identity fields of an already-ingested job the skip needs."""

    source: str
    location: str | None


@dataclass
class KnownJobsIndex:
    """Snapshot of active jobs' identities for pre-fetch skip decisions.

    Two lookups, both computable from a bare list card (no JD yet): exact apply
    ``url``, and ``(dedup_key, normalized location)`` so a title collapsed across
    cities by ``compute_dedup_key`` still distinguishes locations.
    """

    by_url: dict[str, KnownJob] = field(default_factory=dict)
    by_key_loc: dict[tuple[str, str], KnownJob] = field(default_factory=dict)

    def match(
        self, url: str | None, company: str | None, title: str | None, location: str | None
    ) -> KnownJob | None:
        if url and url in self.by_url:
            return self.by_url[url]
        key = compute_dedup_key(company, title)
        if key is not None:
            hit = self.by_key_loc.get((key, _norm_loc(location)))
            if hit is not None:
                return hit
        return None


def build_known_index(session: Session) -> KnownJobsIndex:
    """One query over active jobs -> an in-memory identity index. DB touched once."""
    archived_col = cast(Any, Job.archived_at)
    index = KnownJobsIndex()
    for job in session.exec(select(Job).where(archived_col.is_(None))).all():
        known = KnownJob(source=job.source, location=job.location)
        if job.url:
            index.by_url[job.url] = known
        if job.dedup_key:
            index.by_key_loc[(job.dedup_key, _norm_loc(job.location))] = known
    return index


def make_skip_seen(index: KnownJobsIndex) -> SkipSeen:
    """A pure predicate mirroring merge.decide()'s Skip branch, one step earlier.

    Skip a list card iff a known row matches AND the incoming source cannot beat it
    on tier (``source_rank(incoming) >= source_rank(existing)``). A strictly
    higher-tier incoming (lower rank) is the upgrade path and is never skipped.
    """

    def skip_seen(row: RawJob) -> bool:
        existing = index.match(row.url, row.company, row.title, row.location)
        if existing is None:
            return False
        return source_rank(row.source) >= source_rank(existing.source)

    return skip_seen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_known_jobs.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/known_jobs.py tests/test_known_jobs.py
git commit -m "feat: add KnownJobsIndex + skip_seen predicate for pre-fetch skip"
```

---

### Task 2: Apply `skip_seen` in `harvest_detailed`

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/harvest.py`
- Test: `tests/test_harvest_skip.py`

**Interfaces:**

- Consumes: `SkipSeen` (`discovery/known_jobs.py`).
- Produces: `harvest_detailed(rows, fetch_detail, apply_detail, *, search, limit, skip_seen=None)` — a `skip_seen(row)` that returns True short-circuits **before** `fetch_detail`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harvest_skip.py
from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.harvest import harvest_detailed
from resume_tailor_harness.discovery.search_config import SearchConfig


def _row(title, url):
    return RawJob("workday", url, "Acme", title, "Remote", jd_text="")


def test_harvest_detailed_skips_known_before_detail_fetch():
    fetched: list[str] = []

    def fetch_detail(row):
        fetched.append(row.url)
        return {"jd": "x"}

    def apply_detail(row, detail):
        row.jd_text = "Backend Engineer role building things"

    rows = [_row("Backend Engineer", "https://wd/1"), _row("Backend Engineer", "https://wd/2")]
    skip_seen = lambda row: row.url == "https://wd/1"

    jobs = harvest_detailed(
        rows, fetch_detail, apply_detail,
        search=SearchConfig(), limit=None, skip_seen=skip_seen,
    )

    assert fetched == ["https://wd/2"]  # the skipped row never hit the detail fetch
    assert [j.url for j in jobs] == ["https://wd/2"]


def test_harvest_detailed_without_skip_seen_fetches_all():
    fetched: list[str] = []

    def fetch_detail(row):
        fetched.append(row.url)
        return {"jd": "x"}

    def apply_detail(row, detail):
        row.jd_text = "Backend Engineer role building things"

    rows = [_row("Backend Engineer", "https://wd/1"), _row("Backend Engineer", "https://wd/2")]
    harvest_detailed(rows, fetch_detail, apply_detail, search=SearchConfig(), limit=None)
    assert fetched == ["https://wd/1", "https://wd/2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_harvest_skip.py -v`
Expected: FAIL — `harvest_detailed() got an unexpected keyword argument 'skip_seen'`.

- [ ] **Step 3: Edit `harvest_detailed`**

In `src/resume_tailor_harness/discovery/connectors/harvest.py`, add the import and the parameter. Replace the current `harvest_detailed` signature and loop head:

```python
from resume_tailor_harness.discovery.known_jobs import SkipSeen
```

```python
def harvest_detailed(
    rows: Iterable[T],
    fetch_detail: Callable[[T], dict | None],
    apply_detail: Callable[[T, dict], None],
    *,
    search: SearchConfig,
    limit: int | None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    """The N+1 list-then-detail dance shared by Workday and Tesla.

    Each row arrives with title + location but no JD. Title-gate before the
    expensive detail fetch; then, when ``skip_seen`` marks the row as already
    known from a same-or-higher-tier source, skip the detail fetch entirely.
    ``fetch_detail`` returns the detail payload (or ``None`` when the row has no
    detail to fetch) and may raise ``httpx.HTTPError`` — one stale detail endpoint
    skips its row, never the whole batch. ``apply_detail`` fills the JD before the
    full relevance gate runs on the now-complete row.
    """
    jobs: list[RawJob] = []
    for row in rows:
        if not title_relevance_gate([row], search):
            continue
        if skip_seen is not None and skip_seen(row):
            continue
        try:
            detail = fetch_detail(row)
        except httpx.HTTPError:
            continue
        if detail is None:
            continue
        apply_detail(row, detail)
        if relevance_gate([row], search):
            jobs.append(row)
            if limit is not None and len(jobs) >= limit:
                break
    return jobs
```

> Note: `harvest.py` imports from `known_jobs.py`, which imports `RawJob` from
> `connectors/base.py` — no import cycle (`known_jobs` does not import `harvest`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_harvest_skip.py tests/test_known_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/harvest.py tests/test_harvest_skip.py
git commit -m "feat: skip known rows before the detail fetch in harvest_detailed"
```

---

### Task 3: Propagate `skip_seen` through the N+1 backends (Workday, Tesla, Google) and Companies dispatch

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/workday.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/tesla.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/google.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/companies.py`
- Test: `tests/test_connector_companies.py` (extend)

**Interfaces:**

- Consumes: `SkipSeen`, `harvest_detailed(..., skip_seen=...)`.
- Produces:
  - `fetch_workday(target, search, limit=None, skip_seen=None)`
  - `fetch_tesla(target, search, limit=None, skip_seen=None)`
  - `fetch_google(target, search, limit=None, skip_seen=None)`
  - Every adapter in `companies._BACKENDS` has shape `(target, search, limit, skip_seen) -> RawJob[]`
  - `CompaniesConnector.fetch(search, limit=None, skip_seen=None)`

- [ ] **Step 1: Write the failing test** (Companies forwards skip_seen to the Workday backend)

```python
# tests/test_connector_companies.py  (append)
from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.companies import CompaniesConnector
from resume_tailor_harness.discovery.search_config import SearchConfig
import resume_tailor_harness.discovery.connectors.companies as companies


def test_companies_forwards_skip_seen_to_backend(monkeypatch):
    seen_skip = {}

    def fake_workday(target, search, limit=None, skip_seen=None):
        seen_skip["value"] = skip_seen
        return [RawJob("workday", "https://wd/1", "Acme", "Backend Engineer", "Remote", "jd text here")]

    monkeypatch.setattr(companies, "detect_ats", lambda url: __import__(
        "resume_tailor_harness.discovery.connectors.detect", fromlist=["AtsTarget"]
    ).AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers"))
    monkeypatch.setitem(companies._BACKENDS, "workday", fake_workday)

    marker = lambda row: False
    CompaniesConnector(["https://acme.wd5.myworkdayjobs.com/Careers"]).fetch(
        SearchConfig(), limit=None, skip_seen=marker,
    )
    assert seen_skip["value"] is marker
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py::test_companies_forwards_skip_seen_to_backend -v`
Expected: FAIL — `fetch() got an unexpected keyword argument 'skip_seen'`.

- [ ] **Step 3: Edit the backends and dispatch**

In `workday.py`, thread the parameter:

```python
def fetch_workday(
    target: AtsTarget, search: SearchConfig, limit: int | None = None, skip_seen=None
) -> list[RawJob]:
    """List (request-shaped) -> gate on title/location -> detail-fetch survivors only."""
    return harvest_detailed(
        _list_pages(target, search),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
```

In `tesla.py`:

```python
def fetch_tesla(
    target: AtsTarget, search: SearchConfig, limit: int | None = None, skip_seen=None
) -> list[RawJob]:
    resp = httpx.get(_STATE_URL, timeout=30)
    resp.raise_for_status()
    return harvest_detailed(
        parse_listings(resp.json()),
        _fetch_detail,
        apply_tesla_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
```

In `google.py`: add `skip_seen=None` to the `fetch_google(...)` signature and pass
`skip_seen=skip_seen` into its `harvest_detailed(...)` call (Google uses the same
N+1 list→detail dance). If — and only if — `fetch_google` does not call
`harvest_detailed`, still add the `skip_seen=None` parameter and ignore it, so the
adapter shape is uniform.

In `companies.py`, update every adapter and `_produce` to carry `skip_seen`:

```python
def _greenhouse(target, search, limit=None, skip_seen=None):
    return parse_greenhouse(fetch_greenhouse_board(target.token), target.token)


def _lever(target, search, limit=None, skip_seen=None):
    return parse_lever(fetch_lever_board(target.token), target.token)


def _ashby(target, search, limit=None, skip_seen=None):
    return parse_ashby(fetch_ashby_board(target.token), target.token)


def _workday(target, search, limit=None, skip_seen=None):
    return fetch_workday(target, search, limit, skip_seen=skip_seen)


def _tesla(target, search, limit=None, skip_seen=None):
    return fetch_tesla(target, search, limit, skip_seen=skip_seen)


def _google(target, search, limit=None, skip_seen=None):
    return fetch_google(target, search, limit, skip_seen=skip_seen)
```

And the connector + producer:

```python
    def fetch(self, search: SearchConfig, limit: int | None = None, skip_seen=None) -> FetchResult:
        return harvest(
            self.urls,
            lambda url: self._produce(url, search, limit, skip_seen),
            search=search,
            limit=limit,
            key=lambda url: url,
            on_error=_failure_reason,
        )

    def _produce(self, url: str, search: SearchConfig, limit: int | None, skip_seen) -> list[RawJob]:
        target = detect_ats(url)
        if target is None:
            raise NoAtsDetected
        backend = _BACKENDS.get(target.ats)
        if backend is None:
            raise UnsupportedAts(target.ats)
        return backend(target, search, limit, skip_seen=skip_seen)
```

Add `skip_seen` to the type of `_BACKENDS` values if it is annotated; otherwise leave as-is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py tests/test_connector_workday.py tests/test_connector_tesla.py tests/test_connector_google.py -v`
Expected: PASS (existing tests still green; new forwarding test passes).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/workday.py src/resume_tailor_harness/discovery/connectors/tesla.py src/resume_tailor_harness/discovery/connectors/google.py src/resume_tailor_harness/discovery/connectors/companies.py tests/test_connector_companies.py
git commit -m "feat: thread skip_seen through N+1 backends and companies dispatch"
```

---

### Task 4: Apply `skip_seen` in Adzuna enrichment (skip the browser render)

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/adzuna.py`
- Test: `tests/test_connector_adzuna.py` (extend)

**Interfaces:**

- Produces: `AdzunaConnector.fetch(search, limit=None, skip_seen=None)` — rows the
  predicate marks known are dropped **before** `enrich_adzuna_jobs` renders them, so
  the visible browser never opens for an already-known job.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connector_adzuna.py  (append)
import resume_tailor_harness.discovery.connectors.adzuna as adzuna_mod
from resume_tailor_harness.discovery.connectors.adzuna import AdzunaConnector


def test_adzuna_skips_known_jobs_before_enrichment(monkeypatch):
    payload = {"results": [
        {"redirect_url": "https://a/1", "title": "Backend Engineer",
         "company": {"display_name": "Acme"}, "location": {"display_name": "Remote"},
         "description": "python backend role building services and apis for scale"},
        {"redirect_url": "https://a/2", "title": "Backend Engineer",
         "company": {"display_name": "Beta"}, "location": {"display_name": "Remote"},
         "description": "python backend role building services and apis for scale"},
    ]}
    monkeypatch.setattr(AdzunaConnector, "_get_results", lambda self, search: payload)

    rendered_urls = []

    def fake_enrich(jobs):
        rendered_urls.extend(j.url for j in jobs)
        return jobs, {}

    monkeypatch.setattr(adzuna_mod, "enrich_adzuna_jobs", fake_enrich)

    from resume_tailor_harness.discovery.search_config import SearchConfig
    skip_seen = lambda row: row.url == "https://a/1"
    connector = AdzunaConnector("id", "key", "us")
    result = connector.fetch(SearchConfig(role_anchors=["engineer"]), limit=None, skip_seen=skip_seen)

    assert rendered_urls == ["https://a/2"]  # the known job never reached the browser
    assert {j.url for j in result.jobs} == {"https://a/2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_adzuna.py::test_adzuna_skips_known_jobs_before_enrichment -v`
Expected: FAIL — `fetch() got an unexpected keyword argument 'skip_seen'`.

- [ ] **Step 3: Edit `AdzunaConnector.fetch`**

```python
    def fetch(self, search: SearchConfig, limit: int | None = None, skip_seen=None) -> FetchResult:
        jobs, filtered = gate_and_limit(parse_adzuna(self._get_results(search)), search, limit)
        if skip_seen is not None:
            jobs = [job for job in jobs if not skip_seen(job)]
        if not self.enrich_details:
            return FetchResult(jobs=jobs, filtered=filtered)
        enriched, failures = enrich_adzuna_jobs(jobs)
        return FetchResult(jobs=enriched, filtered=filtered, failures=failures)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_adzuna.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/adzuna.py tests/test_connector_adzuna.py
git commit -m "feat: skip known Adzuna jobs before the browser render"
```

---

### Task 5: Add `skip_seen` to the Connector Protocol + remaining connectors

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/base.py` (Protocol)
- Modify: `src/resume_tailor_harness/discovery/connectors/greenhouse.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/lever.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/remoteok.py`
- Modify: `src/resume_tailor_harness/discovery/scraper/linkedin.py` (the connector class's `fetch`)
- Test: none new (covered by existing connector tests + Task 6 integration).

**Interfaces:**

- Produces: uniform `fetch(self, search, limit=None, skip_seen=None) -> FetchResult`
  across all connectors. Single-request connectors accept and ignore `skip_seen`
  (their fetch is one request; there is no per-job expense to avoid).

- [ ] **Step 1: Update the Protocol**

In `base.py`:

```python
class Connector(Protocol):
    """A job source behind the shared fetch seam."""

    name: str

    def fetch(
        self, search: SearchConfig, limit: int | None = None, skip_seen=None
    ) -> FetchResult: ...
```

- [ ] **Step 2: Add `skip_seen=None` to each single-request connector's `fetch`**

`greenhouse.py`, `lever.py`, `remoteok.py`, and the LinkedIn connector class in
`scraper/linkedin.py`: change each `def fetch(self, search, limit=None)` to
`def fetch(self, search, limit=None, skip_seen=None)`. Do **not** change their
bodies — they legitimately ignore `skip_seen` (one request fetches the whole board;
ingest already dedupes). Add a one-line comment on each:

```python
    def fetch(self, search: SearchConfig, limit: int | None = None, skip_seen=None) -> FetchResult:
        # skip_seen accepted for a uniform Protocol; a single-request board fetch has
        # no per-job step to skip, so ingest-level dedupe still handles known jobs.
        return harvest(...)  # unchanged
```

- [ ] **Step 3: Run the full connector suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k connector -v`
Expected: PASS (signatures widened, behavior unchanged).

- [ ] **Step 4: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/base.py src/resume_tailor_harness/discovery/connectors/greenhouse.py src/resume_tailor_harness/discovery/connectors/lever.py src/resume_tailor_harness/discovery/connectors/remoteok.py src/resume_tailor_harness/discovery/scraper/linkedin.py
git commit -m "feat: accept skip_seen uniformly across the Connector protocol"
```

---

### Task 6: Build the index in `run_pull` and add `skip_known` toggle

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/runner.py`
- Modify: `tests/test_connectors_runner.py` (update test doubles + add test)

**Interfaces:**

- Consumes: `build_known_index`, `make_skip_seen`.
- Produces: `run_pull(session, connectors, search, telemetry_path, limit=None, reporter=None, finish=True, skip_known=True)`. When `skip_known` is True, builds the index once and passes a `skip_seen` closure to every `connector.fetch`; when False, passes `skip_seen=None`.

- [ ] **Step 1: Update the existing test doubles + write the failing test**

In `tests/test_connectors_runner.py`, widen the two doubles' signatures and add a test:

```python
class _Good:
    name = "greenhouse"

    def fetch(self, search, limit=None, skip_seen=None):
        return FetchResult(
            jobs=[RawJob("greenhouse", "https://gh/1", "Acme", "Backend Engineer", "Remote", "jd a")]
        )


class _Boom:
    name = "adzuna"

    def fetch(self, search, limit=None, skip_seen=None):
        raise RuntimeError("HTTP 429")


class _SpySkip:
    name = "workday"

    def __init__(self):
        self.received_skip = "unset"

    def fetch(self, search, limit=None, skip_seen=None):
        self.received_skip = skip_seen
        return FetchResult(jobs=[])


def test_run_pull_passes_skip_seen_when_skip_known(tmp_path):
    with _session() as s:
        spy = _SpySkip()
        run_pull(s, [spy], SearchConfig(), tmp_path / "runs.json", skip_known=True)
        assert callable(spy.received_skip)


def test_run_pull_passes_none_when_refresh(tmp_path):
    with _session() as s:
        spy = _SpySkip()
        run_pull(s, [spy], SearchConfig(), tmp_path / "runs.json", skip_known=False)
        assert spy.received_skip is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_runner.py -v`
Expected: FAIL — `run_pull() got an unexpected keyword argument 'skip_known'`.

- [ ] **Step 3: Edit `run_pull`**

Add the import and the toggle:

```python
from resume_tailor_harness.discovery.known_jobs import build_known_index, make_skip_seen
```

Change the signature and add the index build before the loop, then pass `skip_seen`:

```python
def run_pull(
    session: Session,
    connectors: list[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
    skip_known: bool = True,
) -> PullReport:
    ...
    report = PullReport()
    skip_seen = make_skip_seen(build_known_index(session)) if skip_known else None
    if reporter:
        reporter.begin(total=len(connectors), label="Starting", added=0)
    added_total = 0
    for index, connector in enumerate(connectors, 1):
        if reporter:
            reporter.step(index - 1, label=f"Pulling {connector.name}")
        try:
            result = connector.fetch(search, limit=limit, skip_seen=skip_seen)
            ...
```

(Only the two changed lines are the signature `skip_known: bool = True`, the
`skip_seen = ...` build, and the `connector.fetch(search, limit=limit, skip_seen=skip_seen)`
call. Everything else in the loop is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/runner.py tests/test_connectors_runner.py
git commit -m "feat: build known-jobs index in run_pull with a skip_known toggle"
```

---

### Task 7: Thread `skip_known` through the service + `--refresh` CLI flag

**Files:**

- Modify: `src/resume_tailor_harness/services/discovery.py` (`pull_jobs`)
- Modify: `src/resume_tailor_harness/cli.py` (`pull_cmd`)
- Test: `tests/test_services_sources.py` (extend) or a small new `tests/test_pull_refresh.py`

**Interfaces:**

- Produces:
  - `pull_jobs(..., skip_known: bool = True)` forwarding to `run_pull`.
  - `resume-tailor-harness pull --refresh` → `pull_jobs(skip_known=False)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pull_refresh.py
import resume_tailor_harness.services.discovery as disc


def test_pull_jobs_forwards_skip_known(monkeypatch, tmp_path):
    captured = {}

    def fake_run_pull(session, connectors, search, telemetry_path, **kw):
        captured.update(kw)
        from resume_tailor_harness.discovery.connectors.runner import PullReport
        return PullReport()

    monkeypatch.setattr(disc, "run_pull", fake_run_pull)
    monkeypatch.setattr(disc, "build_source_connectors", lambda *a, **k: [])
    monkeypatch.setattr(disc, "load_search_config", lambda p: __import__(
        "resume_tailor_harness.discovery.search_config", fromlist=["SearchConfig"]).SearchConfig())
    monkeypatch.setattr(disc, "load_connectors_config", lambda p: object())

    disc.pull_jobs(session=None, skip_known=False)
    assert captured["skip_known"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pull_refresh.py -v`
Expected: FAIL — `pull_jobs() got an unexpected keyword argument 'skip_known'`.

- [ ] **Step 3: Edit `pull_jobs` and `pull_cmd`**

In `services/discovery.py`, add the parameter and forward it:

```python
def pull_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    limit: int | None = None,
    source_ids: list[str] | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
    skip_known: bool = True,
) -> PullReport:
    """Run selected or all enabled pullable source connectors and ingest results."""
    search_config = load_search_config(search_path)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_source_connectors(connectors_config, get_settings(), source_ids=source_ids)
    return run_pull(
        session, connectors, search_config, telemetry_path,
        limit=limit, reporter=reporter, finish=finish, skip_known=skip_known,
    )
```

In `cli.py`, add the flag to `pull_cmd` and pass it (note: `--refresh` here means
"re-fetch jobs already known", distinct from the top-level `refresh` command):

```python
@app.command("pull")
def pull_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Re-fetch and re-ingest jobs already known (bypass skip-known).",
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    ...
        report = pull_jobs(
            session, search_path=search, connectors_path=connectors_path,
            telemetry_path=CONNECTOR_RUNS_PATH, limit=limit,
            reporter=ProgressReporter("pull"), skip_known=not refresh,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pull_refresh.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/discovery.py src/resume_tailor_harness/cli.py tests/test_pull_refresh.py
git commit -m "feat: expose skip-known bypass as resume-tailor-harness pull --refresh"
```

---

### Task 8: Full-suite regression + lint

- [ ] **Step 1: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (no regressions; the widened `fetch` signature is backward-compatible via the default `skip_seen=None`).

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: no findings in the changed files.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint pass for skip-known pull"
```

---

## Self-Review

- **Spec coverage:** Thread C requirements — pre-fetch early-out in `harvest_detailed` (Task 2) + Adzuna (Task 4); identity by url or dedup_key+location, no schema change (Task 1); mirrors `decide()` Skip via `source_rank` (Task 1); archived filtered (Task 1); DB-free connectors via injected closure (Tasks 3–6); `--refresh` bypass (Task 7). All covered.
- **Type consistency:** `SkipSeen = Callable[[RawJob], bool]` defined in Task 1 and consumed unchanged in Tasks 2–6. `skip_seen` keyword name is identical across `harvest_detailed`, every backend `fetch_*`, every adapter, every connector `fetch`, and `run_pull`. `skip_known` (bool) is the runner/service/CLI toggle; `refresh` (CLI bool) = `not skip_known`.
- **Placeholder scan:** none — every step carries real code or an exact command. Google's edit is conditional but concrete (add param; forward into `harvest_detailed`; if absent, accept-and-ignore).
