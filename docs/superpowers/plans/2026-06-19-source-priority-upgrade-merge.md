# Source-Priority Upgrade-Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a higher-tier (direct/ATS) source re-sees a job first ingested by a lower-tier (aggregator) source, upgrade the stored posting fields in place instead of dropping the new copy — without disturbing the user's progress on that job.

**Architecture:** A pure `source_rank(source)` over a fixed 2-tier map (direct=0, aggregator=1). A new core `save_or_upgrade(...) -> (Job | None, IngestOutcome)` in `ingest.py` owns the dedup decision; `add_job` stays a thin `Job | None` wrapper (CLI + existing tests untouched), `ingest_jobs` remains insert-count compatible, and `ingest_jobs_with_outcomes` returns separate insert/upgrade counts for `run_pull` telemetry. Upgrades mutate the existing `Job` row and persist via the existing `save_job` (which already does insert-or-update); related tables (`Application`/`ResumeVersion`/`CoverLetter`) are untouched, so user progress is preserved structurally. A post-`raw` guard freezes JD/title text so a tailored resume is never silently re-based, and upgrades never overwrite existing nullable fields with missing incoming values.

**Tech Stack:** Python, SQLModel/SQLite, `pytest`. Reuses `find_existing`, `save_job`, `compute_dedup_key`.

**Spec:** `docs/superpowers/specs/2026-06-19-source-priority-upgrade-merge-design.md`

---

## File Structure

| File                                              | Responsibility                                                                             | Action        |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------- |
| `src/resume_tailor_harness/discovery/source_tier.py`       | `source_rank` — fixed direct>aggregator tier                                               | Create        |
| `src/resume_tailor_harness/discovery/ingest.py`            | `IngestOutcome`, `IngestCounts`, `save_or_upgrade`, thin `add_job`, counted ingest helpers | Modify        |
| `src/resume_tailor_harness/discovery/connectors/runner.py` | Use outcome-aware ingest counts in pull telemetry                                          | Modify        |
| `tests/test_source_tier.py`                       | tier ranking                                                                               | Create        |
| `tests/test_discovery_ingest.py`                  | upgrade/skip/freeze behavior of `save_or_upgrade`/`add_job`                                | Modify        |
| `tests/test_ingest_jobs.py`                       | upgrade not double-counted; cross-run upgrade                                              | Modify        |
| `tests/test_connector_runner.py`                  | pull telemetry includes upgrades                                                           | Modify/Create |

No change to `repository.py`, `cli.py`, config, or schema.

---

## Task 1: Fixed source tier

**Files:**

- Create: `src/resume_tailor_harness/discovery/source_tier.py`
- Test: `tests/test_source_tier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_source_tier.py
from resume_tailor_harness.discovery.source_tier import source_rank


def test_direct_sources_outrank_aggregators():
    for direct in ("greenhouse", "lever", "ashby", "workday", "tesla", "google", "companies", "url"):
        for aggregator in ("adzuna", "remoteok", "linkedin"):
            assert source_rank(direct) < source_rank(aggregator)


def test_equal_tier_sources_tie():
    assert source_rank("greenhouse") == source_rank("workday")
    assert source_rank("adzuna") == source_rank("remoteok")


def test_unknown_source_defaults_to_aggregator_tier():
    assert source_rank("mystery") == source_rank("adzuna")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_source_tier.py -v`
Expected: FAIL — `ModuleNotFoundError: source_tier`

- [ ] **Step 3: Implement the tier**

```python
# src/resume_tailor_harness/discovery/source_tier.py
"""Fixed source priority: a job's canonical (direct/ATS) copy beats an aggregator copy.

Lower rank == higher priority. Calibration is a tier label, not a per-source number.
"""

_CANONICAL = {"greenhouse", "lever", "ashby", "workday", "tesla", "google", "companies", "url"}

_DIRECT = 0
_AGGREGATOR = 1


def source_rank(source: str) -> int:
    """0 for direct/ATS sources, 1 for aggregators and anything unknown."""
    return _DIRECT if source in _CANONICAL else _AGGREGATOR
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_source_tier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/source_tier.py tests/test_source_tier.py
git commit -m "feat: fixed direct>aggregator source tier"
```

---

## Task 2: `save_or_upgrade` — upgrade on better source, skip otherwise

**Files:**

- Modify: `src/resume_tailor_harness/discovery/ingest.py`
- Test: `tests/test_discovery_ingest.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_discovery_ingest.py
from resume_tailor_harness.discovery.ingest import save_or_upgrade, IngestOutcome
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus


def test_save_or_upgrade_inserts_new():
    with _session() as s:
        job, outcome = save_or_upgrade(s, source="adzuna", jd_text="jd", url="http://a/1",
                                       company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.inserted
        assert job is not None and job.source == "adzuna"


def test_higher_tier_upgrades_lower_tier_in_place():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin jd", url="http://adz/1",
                                   company="Acme Corp", title="Backend Engineer")
        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url="http://workday/1", company="Acme Corp",
                                            title="Senior Backend Engineer")
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id            # same row, upgraded in place
        assert upgraded.source == "workday"
        assert upgraded.url == "http://workday/1"
        assert upgraded.jd_text == "full canonical jd"


def test_raw_upgrade_does_not_clobber_existing_fields_with_missing_values():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin jd", url="http://adz/1",
                                   company="Acme Corp", title="Backend Engineer",
                                   location="Remote")
        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url=None, company="Acme Corp",
                                            title="Backend Engineer", location=None)
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.url == "http://adz/1"       # absent incoming URL does not erase old URL
        assert upgraded.location == "Remote"


def test_lower_tier_does_not_overwrite_higher_tier():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="workday", jd_text="canonical", url="http://wd/1",
                                   company="Acme", title="Backend Engineer")
        job, outcome = save_or_upgrade(s, source="adzuna", jd_text="thin", url="http://adz/1",
                                       company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.skipped
        assert job is None
        assert first.source == "workday" and first.url == "http://wd/1"


def test_equal_tier_keeps_first_seen():
    with _session() as s:
        save_or_upgrade(s, source="greenhouse", jd_text="gh jd", url="http://gh/1",
                        company="Acme", title="Backend Engineer")
        job, outcome = save_or_upgrade(s, source="workday", jd_text="wd jd", url="http://wd/1",
                                       company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.skipped
        assert job is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_discovery_ingest.py::test_higher_tier_upgrades_lower_tier_in_place -v`
Expected: FAIL — `cannot import name 'save_or_upgrade'`

- [ ] **Step 3: Implement `save_or_upgrade` + `IngestOutcome`; reduce `add_job` to a wrapper**

```python
# ingest.py — add imports
from enum import Enum
from resume_tailor_harness.discovery.source_tier import source_rank
from resume_tailor_harness.tracking.tables import Job, JobStatus
```

```python
# ingest.py — add above add_job
class IngestOutcome(str, Enum):
    inserted = "inserted"
    upgraded = "upgraded"
    skipped = "skipped"


def save_or_upgrade(
    session: Session,
    *,
    source: str,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    posted_at: datetime | None = None,
) -> tuple[Job | None, IngestOutcome]:
    """Insert a new job, upgrade an existing one from a higher-tier source, or skip."""
    jd_text = jd_text.strip()
    url = _clean(url)
    company = _clean(company)
    title = _clean(title)
    incoming_location = _clean(location)
    dedup_key = compute_dedup_key(company, title)

    existing = find_existing(session, url, jd_text, dedup_key)
    if existing is not None:
        if source_rank(source) >= source_rank(existing.source):
            return None, IngestOutcome.skipped
        if existing.status != JobStatus.raw.value:
            if not url:
                return None, IngestOutcome.skipped
            existing.url = url
            existing.source = source
            return save_job(session, existing), IngestOutcome.upgraded

        # Higher-tier re-see while raw: re-base the posting text, but do not erase
        # existing optional fields when the incoming source omitted them.
        existing.source = source
        existing.jd_text = jd_text
        if url:
            existing.url = url
        if company is not None:
            existing.company = company
        if title is not None:
            existing.title = title
        if incoming_location is not None:
            existing.location = incoming_location
        if posted_at is not None:
            existing.posted_at = posted_at
        existing.dedup_key = compute_dedup_key(existing.company, existing.title)
        return save_job(session, existing), IngestOutcome.upgraded

    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=incoming_location,
        posted_at=posted_at,
        dedup_key=dedup_key,
        status=JobStatus.raw.value,
    )
    return save_job(session, job), IngestOutcome.inserted
```

```python
# ingest.py — replace the body of add_job with a thin wrapper (keep its signature + docstring)
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
    """Normalize, dedupe, and insert/upgrade a raw job. Returns None when skipped."""
    job, _ = save_or_upgrade(
        session,
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=location,
        posted_at=posted_at,
    )
    return job
```

> Remove the now-duplicated normalize/insert logic from the old `add_job` body (it moved into `save_or_upgrade`). Keep the existing `Job`/`JobStatus` import line if it was already there — dedupe imports.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_discovery_ingest.py -v`
Expected: PASS. The pre-existing `test_add_job_dedupes_*` tests stay green: in each, the first source is greenhouse/manual and the second is lower-or-equal tier → `skipped` → `add_job` returns `None`, exactly as before.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/ingest.py tests/test_discovery_ingest.py
git commit -m "feat: save_or_upgrade with tier-based upgrade-on-better-source"
```

---

## Task 3: Preserve user progress; freeze text post-`raw`

**Files:**

- Test only: `tests/test_discovery_ingest.py`
- (Verifies the guard already written in Task 2 — no new src code expected; if a test fails, the guard is wrong and gets fixed here.)

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_discovery_ingest.py
from resume_tailor_harness.tracking.repository import application_for_job


def test_upgrade_preserves_application_and_status():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        first.status = JobStatus.shortlisted.value
        s.add(first); s.commit()
        s.add(Application(job_id=first.id, status=ApplicationStatus.submitted.value,
                          notes="applied via referral")); s.commit()

        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url="http://wd/1", company="Acme",
                                            title="Backend Engineer")
        assert outcome is IngestOutcome.upgraded
        assert upgraded.status == JobStatus.shortlisted.value      # progress preserved
        app = application_for_job(s, upgraded.id)
        assert app is not None and app.notes == "applied via referral"


def test_post_raw_upgrade_freezes_text_but_takes_url():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="ORIGINAL jd", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        first.status = JobStatus.tailored.value     # a resume was tailored to ORIGINAL jd
        s.add(first); s.commit()

        upgraded, _ = save_or_upgrade(s, source="workday", jd_text="REPLACEMENT jd",
                                      url="http://wd/1", company="Acme", title="Backend Engineer")
        assert upgraded.url == "http://wd/1"        # canonical link taken
        assert upgraded.source == "workday"
        assert upgraded.jd_text == "ORIGINAL jd"    # text frozen — resume not re-based


def test_post_raw_higher_tier_without_url_is_skipped():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="ORIGINAL jd", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        first.status = JobStatus.tailored.value
        s.add(first); s.commit()

        job, outcome = save_or_upgrade(s, source="workday", jd_text="REPLACEMENT jd",
                                       url=None, company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.skipped
        assert job is None
        assert first.source == "adzuna"
```

- [ ] **Step 2: Run to verify status**

Run: `pytest tests/test_discovery_ingest.py::test_post_raw_upgrade_freezes_text_but_takes_url -v`
Expected: PASS (the `status == raw` guard in `save_or_upgrade` already enforces this). If it FAILS, correct the guard branch in `ingest.py` so only `url`/`source` are written when `status != raw`.

- [ ] **Step 3: (only if needed) fix the guard**

No code change expected. If a test failed, ensure the post-`raw` branch writes **only** `existing.url` and `existing.source`.

- [ ] **Step 4: Re-run**

Run: `pytest tests/test_discovery_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_discovery_ingest.py
git commit -m "test: upgrade preserves progress and freezes post-raw text"
```

---

## Task 4: Add outcome-aware ingest counts without changing legacy `ingest_jobs`

**Files:**

- Modify: `src/resume_tailor_harness/discovery/ingest.py` (`ingest_jobs`)
- Test: `tests/test_ingest_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ingest_jobs.py
from resume_tailor_harness.discovery.ingest import ingest_jobs_with_outcomes


def test_cross_run_upgrade_not_counted_as_new_add():
    # Run 1: aggregator claims the job.
    with _session() as s:
        summary1 = ingest_jobs_with_outcomes(s, [RawJob("adzuna", "http://adz/1", "Acme Corp",
                                                        "Backend Engineer", "Remote", "thin jd")])
        assert summary1.added == {"adzuna": 1}
        assert summary1.upgraded == {}

        # Run 2 (same session/db): the canonical Workday copy upgrades, is NOT a new add.
        summary2 = ingest_jobs_with_outcomes(s, [RawJob("workday", "http://wd/1", "Acme Corp",
                                                        "Senior Backend Engineer", "Remote",
                                                        "full canonical jd")])
        assert summary2.added == {}              # upgrade, not an add
        assert summary2.upgraded == {"workday": 1}
        assert ingest_jobs(s, [RawJob("workday", "http://wd/1", "Acme Corp",
                                      "Senior Backend Engineer", "Remote", "full canonical jd")]) == {}

        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "workday"
        assert rows[0].url == "http://wd/1"
        assert rows[0].jd_text == "full canonical jd"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ingest_jobs.py::test_cross_run_upgrade_not_counted_as_new_add -v`
Expected: FAIL — `ingest_jobs_with_outcomes` / `IngestCounts` do not exist yet.

- [ ] **Step 3: Add `IngestCounts`, keep `ingest_jobs` compatible, and expose the counted path**

```python
# ingest.py — add import
from dataclasses import dataclass
```

```python
# ingest.py — add near IngestOutcome
@dataclass(frozen=True)
class IngestCounts:
    added: dict[str, int]
    upgraded: dict[str, int]
```

```python
# ingest.py — replace ingest_jobs with these two functions
def ingest_jobs_with_outcomes(session: Session, raw_jobs: Iterable[RawJob]) -> IngestCounts:
    """Insert/upgrade RawJobs and return separate insert/upgrade counts per incoming source."""
    added: Counter[str] = Counter()
    upgraded: Counter[str] = Counter()
    for raw in raw_jobs:
        if not raw.jd_text.strip():
            continue
        _job, outcome = save_or_upgrade(
            session,
            source=raw.source,
            jd_text=raw.jd_text,
            url=raw.url,
            company=raw.company,
            title=raw.title,
            location=raw.location,
            posted_at=raw.posted_at,
        )
        if outcome is IngestOutcome.inserted:
            added[raw.source] += 1
        elif outcome is IngestOutcome.upgraded:
            upgraded[raw.source] += 1
    return IngestCounts(added=dict(added), upgraded=dict(upgraded))


def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Backward-compatible insert counts; upgrades are intentionally not new adds."""
    return ingest_jobs_with_outcomes(session, raw_jobs).added
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ingest_jobs.py -v`
Expected: PASS. `test_ingest_jobs_dedupes_same_posting_across_sources` stays green (greenhouse inserted first; adzuna/linkedin are lower-tier → skipped → uncounted → `{"greenhouse": 1}`).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/ingest.py tests/test_ingest_jobs.py
git commit -m "feat: ingest_jobs counts inserts, not upgrades"
```

---

## Task 5: Surface upgrades in pull telemetry without changing added totals

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/runner.py`
- Test: `tests/test_connector_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_connector_runner.py
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.connectors.runner import run_pull
from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.telemetry import read_runs
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Connector:
    name = "companies"
    filtered = 0
    failures = {}

    def fetch(self, search, limit=None):
        return [RawJob("workday", "http://wd/1", "Acme", "Backend Engineer", "Remote", "full jd")]


def test_run_pull_records_upgrade_note(tmp_path):
    with _session() as s:
        save_job(
            s,
            Job(source="adzuna", jd_text="thin jd", url="http://adz/1",
                company="Acme", title="Backend Engineer", status=JobStatus.raw.value,
                dedup_key="acme|backend engineer"),
        )
        totals = run_pull(s, [_Connector()], SearchConfig(), tmp_path / "runs.json")

    assert totals == {"companies": 0}
    runs = read_runs(tmp_path / "runs.json")
    assert runs["companies"]["added"] == 0
    assert "1 upgraded" in runs["companies"]["error"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_runner.py::test_run_pull_records_upgrade_note -v`
Expected: FAIL — `run_pull` still calls insert-only `ingest_jobs`, so the upgrade is hidden.

- [ ] **Step 3: Use the outcome-aware ingest helper in `run_pull`**

```python
# runner.py — import the counted helper
from resume_tailor_harness.discovery.ingest import ingest_jobs_with_outcomes
```

```python
# runner.py — replace _run_note
def _run_note(connector: Connector, added_count: int, upgraded_count: int) -> str | None:
    """Non-fatal note: upgrades, skipped sub-sources, and off-target jobs filtered."""
    filtered = int(getattr(connector, "filtered", 0) or 0)
    failures: dict[str, str] | None = getattr(connector, "failures", None)
    if not filtered and not failures and not upgraded_count:
        return None
    parts: list[str] = [f"+{added_count} added"]
    if upgraded_count:
        parts.append(f"{upgraded_count} upgraded")
    if filtered:
        parts.append(f"filtered {filtered} off-target")
    if failures:
        items = ", ".join(f"{name} ({reason})" for name, reason in failures.items())
        parts.append(f"skipped {len(failures)} source(s): {items}")
    return "; ".join(parts)
```

```python
# runner.py — replace the ingest/count block inside run_pull
            summary = ingest_jobs_with_outcomes(session, raw_jobs)
            added_count = summary.added.get(connector.name, sum(summary.added.values()))
            upgraded_count = summary.upgraded.get(connector.name, sum(summary.upgraded.values()))
            totals[connector.name] = added_count
            record_run(
                telemetry_path,
                connector.name,
                added=added_count,
                error=_run_note(connector, added_count, upgraded_count),
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_runner.py tests/test_ingest_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/runner.py tests/test_connector_runner.py
git commit -m "feat: surface source upgrades in pull telemetry"
```

---

## Task 6: Full-suite regression + lint

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS. Pay attention to `test_discovery_pipeline.py` and `test_repository.py` (they exercise ingest/dedup) — no regressions expected since lower/equal-tier re-sees still return `None`/skip.

- [ ] **Step 2: Lint**

Run: `ruff check src/resume_tailor_harness/discovery/ingest.py src/resume_tailor_harness/discovery/source_tier.py`
Expected: clean (remove any import left unused after moving logic into `save_or_upgrade`).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore: lint source-priority upgrade-merge"
```

---

## Self-Review

- **Spec coverage:** AC1 → Task 2 (`test_higher_tier_upgrades_lower_tier_in_place`); AC2 → Task 2 (`test_lower_tier_does_not_overwrite_higher_tier`); AC3 → Task 2 (`test_equal_tier_keeps_first_seen`); AC4 → Task 3 (`test_upgrade_preserves_application_and_status`); AC5 → Task 3 (`test_post_raw_upgrade_freezes_text_but_takes_url`); AC6 → Task 2 (`test_raw_upgrade_does_not_clobber_existing_fields_with_missing_values`); AC7 → Tasks 4-5; AC8 → Task 6 (full suite; no config/schema change — no Task touches them).
- **Placeholder scan:** none — all steps carry runnable code. Task 3 is a verification task with explicit tests; its "only if needed" fix is guarded, not a TBD.
- **Type consistency:** `save_or_upgrade(...) -> tuple[Job | None, IngestOutcome]` is used by `add_job` and `ingest_jobs_with_outcomes`; `IngestCounts(added, upgraded)` is used by `run_pull`; `IngestOutcome` members `inserted`/`upgraded`/`skipped` are referenced consistently; `source_rank(source: str) -> int` signature matches both call sites.
- **Architecture (deletion test):** `save_or_upgrade` concentrates normalize+dedup+tier+upgrade behind one interface that two callers (`add_job`, `ingest_jobs_with_outcomes`) reuse. `source_tier.py` is a one-function module, separately testable, with the tier list in exactly one place (locality).
- **Noted-not-fixed (spec §5):** `compute_dedup_key` still drops location; this plan does not change it. Flagged for a follow-up micro-spec.

```

```
