# Résumé Tailor Harness v2 — Application Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer "which sources and which fit-score bands actually convert?" — a dashboard page showing application response / interview / offer rates sliced by **source** and by **fit-score band**, computed by pure functions over the existing `jobs` ⋈ `applications` data. No new tables, no LLM.

**Architecture:** This is **Plan 6 of 6** for v2 (spec `docs/superpowers/specs/2026-06-11-resume-tailor-harness-v2-connectors-design.md`), an independent leaf depending only on v1 tracking. All arithmetic lives in pure, fixture-tested functions (`source_stats`, `fit_band_stats`) returning a single `CohortStat` shape; the Streamlit page is a thin renderer over them. The **interface is the test surface** — counts and rates are asserted on seeded data with no Streamlit runtime.

**Tech Stack:** Python 3.13, uv, SQLModel, Streamlit, pytest. No new deps.

**Depends on:** v1 tracking merged (`tracking.tables` `Job`/`Application`/`ApplicationStatus`), `dashboard.app` helpers (`_masthead`, `_metric_row`, `_CSS`). Independent of Plans 1–5.

> **Commit convention:** every commit ends with `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`.

---

## Architecture notes (the two lenses)

**Deepening:** `CohortStat` is one deep type — counts in, rates out (as derived properties) — so every slice (by source, by band, any future slice) speaks the same vocabulary and tests assert on counts while the UI reads rates. The grouping engine (`_cohorts`) is written once and reused by both `source_stats` and `fit_band_stats` (**locality**): a new slice is one `key` function, not a new query.

**Restraint (karpathy):** no charting library, no new tables, no caching — just `st`-rendered metric rows and a small table over pure aggregates. The page degrades on thin data (shows counts, low-n is visible) rather than hiding behind "needs more data" logic.

---

## File Structure

```
src/resume_tailor_harness/tracking/analytics.py    # CREATE — CohortStat + source_stats + fit_band_stats
src/resume_tailor_harness/dashboard/app.py         # MODIFY — render_analytics_page + radio entry
tests/test_tracking_analytics.py          # CREATE
tests/test_dashboard_analytics.py         # CREATE
```

---

## Task 1: analytics aggregates (pure)

**Files:**

- Create: `src/resume_tailor_harness/tracking/analytics.py`
- Test: `tests/test_tracking_analytics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracking_analytics.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.tracking.analytics import fit_band_stats, source_stats
from resume_tailor_harness.tracking.repository import save_application, save_job
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(s, source, fit, status):
    job = save_job(s, Job(source=source, company="C", title="T", fit_score=fit, status="rendered"))
    save_application(s, Application(job_id=job.id, status=status))


def test_source_stats_counts_and_rates():
    with _session() as s:
        _seed(s, "greenhouse", 85, ApplicationStatus.interview.value)
        _seed(s, "greenhouse", 70, ApplicationStatus.submitted.value)
        _seed(s, "adzuna", 90, ApplicationStatus.rejected.value)
        _seed(s, "adzuna", 60, ApplicationStatus.ready.value)  # not submitted → excluded

        stats = {c.label: c for c in source_stats(s)}
        assert stats["greenhouse"].applications == 2
        assert stats["greenhouse"].interviews == 1
        assert stats["greenhouse"].interview_rate == 50
        assert stats["adzuna"].applications == 1   # the 'ready' one excluded
        assert stats["adzuna"].responses == 1
        assert stats["adzuna"].offers == 0


def test_fit_band_stats_groups_by_band():
    with _session() as s:
        _seed(s, "greenhouse", 85, ApplicationStatus.offer.value)
        _seed(s, "adzuna", 90, ApplicationStatus.interview.value)
        _seed(s, "remoteok", 70, ApplicationStatus.submitted.value)

        bands = {c.label: c for c in fit_band_stats(s)}
        assert bands["80–100"].applications == 2
        assert bands["80–100"].offers == 1
        assert bands["80–100"].offer_rate == 50
        assert bands["60–79"].applications == 1


def test_empty_history_returns_empty():
    with _session() as s:
        assert source_stats(s) == []
        assert fit_band_stats(s) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracking_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.tracking.analytics'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/tracking/analytics.py`:

```python
from dataclasses import dataclass
from typing import Callable

from sqlmodel import Session, select

from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job

_RESPONSE = {
    ApplicationStatus.interview.value,
    ApplicationStatus.offer.value,
    ApplicationStatus.rejected.value,
}
_INTERVIEW = {ApplicationStatus.interview.value, ApplicationStatus.offer.value}


def _rate(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


@dataclass
class CohortStat:
    """Conversion counts for one slice (a source, a fit band). Rates are derived."""

    label: str
    applications: int
    responses: int
    interviews: int
    offers: int

    @property
    def response_rate(self) -> int:
        return _rate(self.responses, self.applications)

    @property
    def interview_rate(self) -> int:
        return _rate(self.interviews, self.applications)

    @property
    def offer_rate(self) -> int:
        return _rate(self.offers, self.applications)


def _band(score: int | None) -> str:
    if score is None:
        return "unscored"
    if score >= 80:
        return "80–100"
    if score >= 60:
        return "60–79"
    return "0–59"


# (status, fit_score, source) rows for every *submitted* application.
def _rows(session: Session) -> list[tuple[str, int | None, str]]:
    statement = (
        select(Application.status, Job.fit_score, Job.source)
        .join(Job, Application.job_id == Job.id)
        .where(Application.status != ApplicationStatus.ready.value)
    )
    return list(session.exec(statement).all())


def _cohorts(
    rows: list[tuple[str, int | None, str]],
    key: Callable[[str, int | None, str], str],
) -> list[CohortStat]:
    buckets: dict[str, list[int]] = {}
    for status, fit, source in rows:
        counts = buckets.setdefault(key(status, fit, source), [0, 0, 0, 0])
        counts[0] += 1
        if status in _RESPONSE:
            counts[1] += 1
        if status in _INTERVIEW:
            counts[2] += 1
        if status == ApplicationStatus.offer.value:
            counts[3] += 1
    stats = [CohortStat(label, *counts) for label, counts in buckets.items()]
    return sorted(stats, key=lambda c: (-c.applications, c.label))


def source_stats(session: Session) -> list[CohortStat]:
    """Conversion stats grouped by job source."""
    return _cohorts(_rows(session), key=lambda status, fit, source: source or "unknown")


def fit_band_stats(session: Session) -> list[CohortStat]:
    """Conversion stats grouped by fit-score band."""
    return _cohorts(_rows(session), key=lambda status, fit, source: _band(fit))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tracking_analytics.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/analytics.py tests/test_tracking_analytics.py
git commit -m "feat(analytics): source + fit-band conversion stats" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: dashboard analytics page

**Files:**

- Modify: `src/resume_tailor_harness/dashboard/app.py`
- Test: `tests/test_dashboard_analytics.py`

> Following the module's convention (all Streamlit calls inside functions so it imports cleanly), the page is a thin renderer over Task 1's pure stats. The test asserts the page is importable and that a pure row-builder produces the right table data; the visual layout is verified by running the dashboard.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_analytics.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.dashboard.app import analytics_table_rows, render_analytics_page
from resume_tailor_harness.tracking.repository import save_application, save_job
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_render_analytics_page_is_importable_and_callable():
    assert callable(render_analytics_page)


def test_analytics_table_rows_formats_counts_and_rates():
    with _session() as s:
        job = save_job(s, Job(source="greenhouse", company="C", title="T", fit_score=85, status="rendered"))
        save_application(s, Application(job_id=job.id, status=ApplicationStatus.interview.value))

        rows = analytics_table_rows(s, by="source")
        assert rows == [
            {"Source": "greenhouse", "Apps": 1, "Responses": 1, "Interviews": 1, "Offers": 0,
             "Interview %": 100, "Offer %": 0},
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard_analytics.py -v`
Expected: FAIL — `ImportError: cannot import name 'analytics_table_rows' from 'resume_tailor_harness.dashboard.app'`.

- [ ] **Step 3: Add the row-builder + page**

In `src/resume_tailor_harness/dashboard/app.py`, add the import near the other tracking imports:

```python
from resume_tailor_harness.tracking.analytics import fit_band_stats, source_stats
```

Add these functions before `def _engine():`:

```python
def analytics_table_rows(session, by: str = "source") -> list[dict]:
    """Pure table rows for the analytics page (testable without Streamlit)."""
    stats = source_stats(session) if by == "source" else fit_band_stats(session)
    header = "Source" if by == "source" else "Fit band"
    return [
        {
            header: c.label,
            "Apps": c.applications,
            "Responses": c.responses,
            "Interviews": c.interviews,
            "Offers": c.offers,
            "Interview %": c.interview_rate,
            "Offer %": c.offer_rate,
        }
        for c in stats
    ]


def render_analytics_page(session) -> None:
    rows = analytics_table_rows(session, by="source")
    _masthead(
        "Conversion",
        'Analytics <span class="dot">·</span> Funnel',
        "Which sources and fit-score bands actually convert. Rates are share of submitted applications.",
    )
    total_apps = sum(r["Apps"] for r in rows)
    total_offers = sum(r["Offers"] for r in rows)
    _metric_row([("Submitted", str(total_apps)), ("Offers", str(total_offers)),
                 ("Sources tracked", str(len(rows)))])

    if total_apps == 0:
        _empty_state(
            "◇",
            "No applications tracked yet",
            "Mark applications as submitted in the Pipeline board to populate analytics.",
        )
        return

    st.markdown('<div class="rail-head">By source</div>', unsafe_allow_html=True)
    st.table(analytics_table_rows(session, by="source"))
    st.markdown('<div class="rail-head">By fit-score band</div>', unsafe_allow_html=True)
    st.table(analytics_table_rows(session, by="band"))
```

- [ ] **Step 4: Wire the page into the radio**

In `src/resume_tailor_harness/dashboard/app.py`, inside `main()`, replace the page radio and routing:

```python
        page = st.radio("View", ["Shortlist", "Pipeline board", "Analytics"], label_visibility="collapsed")

    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        else:
            render_analytics_page(session)
```

- [ ] **Step 5: Run test, then the full suite**

Run: `uv run pytest tests/test_dashboard_analytics.py -v`
Expected: PASS (2 tests).

Run: `uv run pytest -q`
Expected: ALL pass.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/dashboard/app.py tests/test_dashboard_analytics.py
git commit -m "feat(analytics): dashboard analytics page (source + fit-band)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.6, Decision #6):** response/interview/offer rates by **source** (`source_stats`) and **fit-score band** (`fit_band_stats`) — Task 1; pure SQL/Python, no LLM, no new tables — Task 1; dashboard page with graceful low-/empty-data handling — Task 2.

**Placeholder scan:** none — full aggregation logic, page, and row-builder. The visual layout is the one manually-verified part (inherent to a UI); the data it renders is fully unit-tested via `analytics_table_rows`.

**Type consistency:** `CohortStat(label, applications, responses, interviews, offers)` with derived `*_rate` properties is used identically in Tasks 1/2. `source_stats(session)`/`fit_band_stats(session) -> list[CohortStat]` match the page + row-builder. `analytics_table_rows(session, by)` keys ("Apps", "Responses", "Interviews", "Offers", "Interview %", "Offer %" + label header) match the Task 2 assertion exactly.

**Note:** rates are a share of _submitted_ applications (`status != ready`), so a `ready` row never dilutes the denominator — asserted in Task 1's adzuna case.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-tailor-harness-v2-application-analytics.md`. Execute via **superpowers:subagent-driven-development** or **superpowers:executing-plans**. This is the final v2 plan — with Plans 1–6 merged, v2 is complete: multi-source intake (`pull`/`sources`), cover letters, Gmail auto-status, and conversion analytics, all on the v1 spine.
