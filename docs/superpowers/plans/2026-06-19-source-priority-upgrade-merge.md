# Source-Priority Upgrade-Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a higher-tier (direct/ATS) source re-sees a job first ingested by a lower-tier (aggregator) source, upgrade the stored posting fields in place instead of dropping the new copy — without disturbing the user's progress on that job.

**Architecture:** A pure `source_rank(source)` over a fixed 2-tier map (direct=0, aggregator=1). A new core `save_or_upgrade(...) -> (Job, IngestOutcome)` in `ingest.py` owns the dedup decision; `add_job` stays a thin `Job | None` wrapper (CLI + existing tests untouched), and `ingest_jobs` uses the outcome to count inserts and upgrades separately. Upgrades mutate the existing `Job` row and persist via the existing `save_job` (which already does insert-or-update); related tables (`Application`/`ResumeVersion`/`CoverLetter`) are untouched, so user progress is preserved structurally. A post-`raw` guard freezes JD/title text so a tailored resume is never silently re-based.

**Tech Stack:** Python, SQLModel/SQLite, `pytest`. Reuses `find_existing`, `save_job`, `compute_dedup_key`.

**Spec:** `docs/superpowers/specs/2026-06-19-source-priority-upgrade-merge-design.md`

> **Deviation from spec §3 (recorded):** the spec sketched `add_job` returning the upgraded job directly. To satisfy AC6 (upgrades must not be double-counted as new adds) with minimal churn, this plan keeps `add_job -> Job | None` (so `cli.py:155-162` and the 5 existing `add_job` tests stay green) and introduces `save_or_upgrade -> (Job, IngestOutcome)` as the counted path for `ingest_jobs`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/resume_agent/discovery/source_tier.py` | `source_rank` — fixed direct>aggregator tier | Create |
| `src/resume_agent/discovery/ingest.py` | `IngestOutcome`, `save_or_upgrade`, thin `add_job`, counted `ingest_jobs` | Modify |
| `tests/test_source_tier.py` | tier ranking | Create |
| `tests/test_discovery_ingest.py` | upgrade/skip/freeze behavior of `save_or_upgrade`/`add_job` | Modify |
| `tests/test_ingest_jobs.py` | upgrade not double-counted; cross-run upgrade | Modify |

No change to `repository.py`, `runner.py`, `cli.py`, config, or schema.

---

## Task 1: Fixed source tier

**Files:**
- Create: `src/resume_agent/discovery/source_tier.py`
- Test: `tests/test_source_tier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_source_tier.py
from resume_agent.discovery.source_tier import source_rank


def test_direct_sources_outrank_aggregators():
    for direct in ("greenhouse", "lever", "ashby", "workday", "tesla", "google", "url"):
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
# src/resume_agent/discovery/source_tier.py
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
git add src/resume_agent/discovery/source_tier.py tests/test_source_tier.py
git commit -m "feat: fixed direct>aggregator source tier"
```

---

## Task 2: `save_or_upgrade` — upgrade on better source, skip otherwise

**Files:**
- Modify: `src/resume_agent/discovery/ingest.py`
- Test: `tests/test_discovery_ingest.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_discovery_ingest.py
from resume_agent.discovery.ingest import save_or_upgrade, IngestOutcome
from resume_agent.tracking.tables import Application, ApplicationStatus


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
from resume_agent.discovery.source_tier import source_rank
from resume_agent.tracking.tables import Job, JobStatus
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
    dedup_key = compute_dedup_key(company, title)

    existing = find_existing(session, url, jd_text, dedup_key)
    if existing is not None:
        if source_rank(source) >= source_rank(existing.source):
            return None, IngestOutcome.skipped
        # Higher-tier re-see: always claim the canonical apply link + source.
        existing.url = url
        existing.source = source
        # Only re-base the posting text while the job is still untouched (status == raw),
        # so a resume already tailored to the old JD is never silently moved out from under it.
        if existing.status == JobStatus.raw.value:
            existing.jd_text = jd_text
            existing.company = company
            existing.title = title
            existing.location = _clean(location)
            existing.posted_at = posted_at
            existing.dedup_key = dedup_key
        return save_job(session, existing), IngestOutcome.upgraded

    job = Job(
        source=source,
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=_clean(location),
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
git add src/resume_agent/discovery/ingest.py tests/test_discovery_ingest.py
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
from resume_agent.tracking.repository import application_for_job


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

## Task 4: `ingest_jobs` counts inserts and upgrades without double-counting

**Files:**
- Modify: `src/resume_agent/discovery/ingest.py` (`ingest_jobs`)
- Test: `tests/test_ingest_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ingest_jobs.py
def test_cross_run_upgrade_not_counted_as_new_add():
    # Run 1: aggregator claims the job.
    with _session() as s:
        added1 = ingest_jobs(s, [RawJob("adzuna", "http://adz/1", "Acme Corp",
                                        "Backend Engineer", "Remote", "thin jd")])
        assert added1 == {"adzuna": 1}

        # Run 2 (same session/db): the canonical Workday copy upgrades, is NOT a new add.
        added2 = ingest_jobs(s, [RawJob("workday", "http://wd/1", "Acme Corp",
                                        "Senior Backend Engineer", "Remote", "full canonical jd")])
        assert added2 == {}                      # upgrade, not an add

        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "workday"
        assert rows[0].url == "http://wd/1"
        assert rows[0].jd_text == "full canonical jd"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ingest_jobs.py::test_cross_run_upgrade_not_counted_as_new_add -v`
Expected: FAIL — current `ingest_jobs` counts the upgrade (returns `{"workday": 1}`) because it only checks `job is not None`.

- [ ] **Step 3: Switch `ingest_jobs` to the outcome-aware path**

```python
# ingest.py — replace the loop body in ingest_jobs
def ingest_jobs(session: Session, raw_jobs: Iterable[RawJob]) -> dict[str, int]:
    """Insert RawJobs through the shared normalize/dedupe/upgrade path.

    Counts only true inserts per source; upgrades replace an existing row and are
    intentionally not counted as new adds.
    """
    added: Counter[str] = Counter()
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
    return dict(added)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ingest_jobs.py -v`
Expected: PASS. `test_ingest_jobs_dedupes_same_posting_across_sources` stays green (greenhouse inserted first; adzuna/linkedin are lower-tier → skipped → uncounted → `{"greenhouse": 1}`).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/ingest.py tests/test_ingest_jobs.py
git commit -m "feat: ingest_jobs counts inserts, not upgrades"
```

---

## Task 5: Full-suite regression + lint

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS. Pay attention to `test_discovery_pipeline.py` and `test_repository.py` (they exercise ingest/dedup) — no regressions expected since lower/equal-tier re-sees still return `None`/skip.

- [ ] **Step 2: Lint**

Run: `ruff check src/resume_agent/discovery/ingest.py src/resume_agent/discovery/source_tier.py`
Expected: clean (remove any import left unused after moving logic into `save_or_upgrade`).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore: lint source-priority upgrade-merge"
```

---

## Self-Review

- **Spec coverage:** AC1 → Task 2 (`test_higher_tier_upgrades_lower_tier_in_place`); AC2 → Task 2 (`test_lower_tier_does_not_overwrite_higher_tier`); AC3 → Task 2 (`test_equal_tier_keeps_first_seen`); AC4 → Task 3 (`test_upgrade_preserves_application_and_status`); AC5 → Task 3 (`test_post_raw_upgrade_freezes_text_but_takes_url`); AC6 → Task 4; AC7 → Task 5 (full suite; no config/schema change — no Task touches them).
- **Placeholder scan:** none — all steps carry runnable code. Task 3 is a verification task with explicit tests; its "only if needed" fix is guarded, not a TBD.
- **Type consistency:** `save_or_upgrade(...) -> tuple[Job | None, IngestOutcome]` used identically in `add_job` and `ingest_jobs`; `IngestOutcome` members `inserted`/`upgraded`/`skipped` referenced consistently; `source_rank(source: str) -> int` signature matches both call sites.
- **Architecture (deletion test):** `save_or_upgrade` concentrates normalize+dedup+tier+upgrade behind one interface that two callers (`add_job`, `ingest_jobs`) reuse — deleting it scatters that policy across both. `source_tier.py` is a one-function seam, separately testable, with the tier list in exactly one place (locality).
- **Noted-not-fixed (spec §5):** `compute_dedup_key` still drops location; this plan does not change it. Flagged for a follow-up micro-spec.
```
