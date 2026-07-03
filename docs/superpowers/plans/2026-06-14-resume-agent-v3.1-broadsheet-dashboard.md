# Broadsheet Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dark "Midnight Atelier" dashboard with a fresh light "Broadsheet" visual identity and an adaptive multi-column layout that fills a 32″ 4K display, while splitting the 527-line `dashboard/app.py` into a pure design-system module + thin page bodies.

**Architecture:** Pure cores + thin shells. A new `dashboard/ui.py` holds the theme CSS, palette constants, and all pure HTML helpers (including a unit-tested `column_count`). A new `dashboard/pages.py` holds the four page renderers. `app.py` shrinks to page routing + sidebar and **re-exports** the public API so existing tests pass unchanged. Visual identity and responsive layout live entirely in `ui.py`'s `THEME_CSS` (CSS grid `auto-fill` does the column reflow client-side; no Python round-trip).

**Tech Stack:** Streamlit, Python 3.13, pytest (`streamlit.testing.v1.AppTest`), CSS (Google Fonts: Newsreader, IBM Plex Mono, IBM Plex Sans).

---

## File Structure

| File                                  | Responsibility                                                                                                                                                                                       |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/resume_agent/dashboard/ui.py`    | NEW. `THEME_CSS`, palette constants, `column_count`, `status_badge`, `fit_block`, `masthead`, `metric_row`, `empty_state`, table-styling helper.                                                     |
| `src/resume_agent/dashboard/pages.py` | NEW. `render_shortlist_page`, `render_pipeline_page`, `render_analytics_page`, `render_match_gap_page`, `analytics_table_rows`, `match_gap_table_rows`, `_render_pipeline_card`, `_new_application`. |
| `src/resume_agent/dashboard/app.py`   | SLIMMED. `main()`, sidebar nav, `_engine()`, and re-exports of the public API.                                                                                                                       |
| `.streamlit/config.toml`              | MODIFIED. Light Broadsheet palette.                                                                                                                                                                  |
| `tests/test_dashboard_ui.py`          | NEW. `column_count` + moved-helper unit tests.                                                                                                                                                       |

**Re-export contract:** `app.py` must expose `status_badge`, `fit_block`, `analytics_table_rows`, `match_gap_table_rows`, `render_shortlist_page`, `render_pipeline_page`, `render_analytics_page`, `render_match_gap_page`, `main`. Existing tests (`test_dashboard_app.py`, `test_dashboard_analytics.py`, `test_dashboard_match_gap.py`) import these names from `resume_agent.dashboard.app` and must not be edited.

---

### Task 1: `column_count` pure function + `ui.py` scaffold

**Files:**

- Create: `src/resume_agent/dashboard/ui.py`
- Test: `tests/test_dashboard_ui.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_ui.py
from resume_agent.dashboard.ui import column_count


def test_column_count_caps_at_max_on_4k():
    assert column_count(3840) == 4


def test_column_count_scales_with_width():
    assert column_count(1280) == 3   # 1280 // 360 == 3
    assert column_count(800) == 2    # 800 // 360 == 2


def test_column_count_floor_is_one():
    assert column_count(300) == 1
    assert column_count(0) == 1
    assert column_count(-100) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard_ui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.dashboard.ui'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/dashboard/ui.py
"""Broadsheet design system: theme CSS, palette, and pure HTML helpers.

All functions here are pure (no Streamlit calls at import or call time) so the
module imports cleanly and the helpers are unit-testable without a server.
"""


def column_count(width: int, card_min: int = 360, max_cols: int = 4) -> int:
    """How many card columns fit in ``width`` px, clamped to [1, max_cols]."""
    if width <= 0:
        return 1
    return max(1, min(max_cols, width // card_min))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dashboard_ui.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/dashboard/ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): add column_count pure helper + ui.py scaffold"
```

---

### Task 2: Move palette + pure HTML helpers into `ui.py`

Move `status_badge`, `fit_block`, `_masthead`→`masthead`, `_metric_row`→`metric_row`, `_empty_state`→`empty_state` and the palette/`STATUS_COLORS` constants out of `app.py` and into `ui.py`, **re-tuned for the light Broadsheet palette** (logic unchanged). `masthead`/`metric_row`/`empty_state` keep calling `st.markdown`, so they're imported lazily inside the functions to keep `ui.py` import-pure.

**Files:**

- Modify: `src/resume_agent/dashboard/ui.py`
- Test: `tests/test_dashboard_ui.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_ui.py  (append)
from resume_agent.dashboard.ui import fit_block, status_badge


def test_status_badge_returns_html_for_known_status():
    html = status_badge("offered")
    assert "offered" in html.lower()
    assert "span" in html.lower()


def test_fit_block_colors_by_threshold():
    assert "—" in fit_block(None)            # no score → em dash
    high = fit_block(88)
    assert "88" in high
    assert 'role="meter"' in high
    assert 'aria-valuenow="88"' in high
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard_ui.py -v`
Expected: FAIL with `ImportError: cannot import name 'status_badge'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/resume_agent/dashboard/ui.py` (above `column_count`):

```python
# ── Broadsheet palette ───────────────────────────────────────────────────────
PAPER = "#f4f1ea"
INK = "#16130f"
MUTED = "#6c6253"
OXBLOOD = "#8c2f1f"
# Status hues, re-tuned for contrast on a light canvas.
EMERALD = "#2f7d4f"
AMBER = "#9a6b16"
ROSE = "#a83246"
SKY = "#2f6b8c"

STATUS_COLORS = {
    # job pipeline
    "raw": MUTED, "extracted": MUTED, "filtered": SKY, "rejected": ROSE,
    "shortlisted": AMBER, "approved": AMBER, "tailored": SKY, "rendered": EMERALD,
    # application funnel
    "ready": MUTED, "submitted": SKY, "interview": AMBER, "offer": EMERALD, "closed": MUTED,
    # sponsorship
    "offered": EMERALD, "denied": ROSE, "silent": MUTED, "unknown": MUTED,
}


def status_badge(status: str) -> str:
    """Return an HTML pill for a job/application/sponsorship status token."""
    token = (status or "unknown").lower()
    color = STATUS_COLORS.get(token, MUTED)
    label = (status or "—").replace("_", " ")
    return f'<span class="badge" style="--badge:{color}">{label}</span>'


def fit_block(score: int | None) -> str:
    """Return the HTML fit-score meter (big numeral + colored bar)."""
    pct = score if score is not None else 0
    if score is None:
        color = MUTED
    elif score >= 80:
        color = EMERALD
    elif score >= 60:
        color = AMBER
    else:
        color = ROSE
    shown = score if score is not None else "—"
    aria = (
        f'role="meter" aria-valuenow="{score}" aria-valuemin="0" aria-valuemax="100" '
        f'aria-label="Fit score {score} out of 100"'
        if score is not None
        else 'role="meter" aria-label="Fit score not yet computed"'
    )
    return (
        f'<div class="fit" {aria}>'
        f'<div class="fit-num" style="color:{color}">{shown}<span class="fit-max">/100</span></div>'
        f'<div class="fit-bar"><div class="fit-fill" style="width:{pct}%;background:{color}"></div></div>'
        '<div class="fit-cap">FIT SCORE</div>'
        "</div>"
    )


def masthead(kicker: str, title_html: str, subtitle: str) -> None:
    import streamlit as st
    st.markdown(
        f'<div class="masthead"><div class="masthead-kicker">{kicker}</div>'
        f'<h1 class="masthead-title">{title_html}</h1>'
        f'<div class="masthead-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def metric_row(metrics: list[tuple[str, str]]) -> None:
    import streamlit as st
    cells = "".join(
        f'<div class="metric"><div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div></div>'
        for label, value in metrics
    )
    st.markdown(f'<div class="metric-row">{cells}</div>', unsafe_allow_html=True)


def empty_state(glyph: str, title: str, body_html: str) -> None:
    import streamlit as st
    st.markdown(
        f'<div class="empty-state"><div class="empty-glyph">{glyph}</div>'
        f'<div class="empty-title">{title}</div>'
        f'<div class="empty-body">{body_html}</div></div>',
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dashboard_ui.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/dashboard/ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): move palette + HTML helpers into ui.py (light palette)"
```

---

### Task 3: Move page renderers into `pages.py`

Move the four `render_*` functions plus `analytics_table_rows`, `match_gap_table_rows`, `_render_pipeline_card`, `_new_application` from `app.py` into a new `pages.py`. They import their helpers from `ui.py` (`masthead`, `metric_row`, `empty_state`, `status_badge`, `fit_block`) and from `ui` the palette constant `AMBER`. Behavior is unchanged from today's `app.py`.

**Files:**

- Create: `src/resume_agent/dashboard/pages.py`
- Test: existing `tests/test_dashboard_analytics.py`, `tests/test_dashboard_match_gap.py` (via re-export in Task 4)

- [ ] **Step 1: Create `pages.py` with the moved renderers**

```python
# src/resume_agent/dashboard/pages.py
"""The four dashboard pages — thin compositions over ui.py primitives."""

from pathlib import Path

import streamlit as st

from resume_agent.dashboard.ui import (
    AMBER,
    empty_state,
    fit_block,
    masthead,
    metric_row,
    status_badge,
)
from resume_agent.profile.store import load_facts
from resume_agent.tracking.analytics import fit_band_stats, source_stats
from resume_agent.tracking.match_gap import MatchGapReport, match_gap
from resume_agent.tracking.queries import PipelineRow, pipeline_rows, shortlist_rows
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_agent.tracking.tables import Application, ApplicationStatus, JobStatus

_STATUS_ORDER = [s.value for s in JobStatus]
_FACTS_PATH = "data/profile/facts.json"


def _new_application(job_id: int, status: str, notes: str) -> Application:
    return Application(job_id=job_id, status=status, notes=notes or None)


def analytics_table_rows(session, by: str = "source") -> list[dict]:
    stats = source_stats(session) if by == "source" else fit_band_stats(session)
    header = "Source" if by == "source" else "Fit band"
    return [
        {
            header: cohort.label,
            "Apps": cohort.applications,
            "Responses": cohort.responses,
            "Interviews": cohort.interviews,
            "Offers": cohort.offers,
            "Interview %": cohort.interview_rate,
            "Offer %": cohort.offer_rate,
        }
        for cohort in stats
    ]


def match_gap_table_rows(report: MatchGapReport) -> list[dict]:
    return [
        {
            "Skill": gap.skill,
            "Demanded by": f"{gap.demand_count}/{gap.target_total}",
            "Share %": gap.demand_share,
        }
        for gap in report.gaps
    ]


def render_shortlist_page(session) -> None:
    rows = shortlist_rows(session)
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
            "◇",
            "Nothing shortlisted yet",
            "Run <code>resume-agent discover</code> to score jobs and surface the keepers here.",
        )
        return

    st.markdown('<div class="card-grid">', unsafe_allow_html=True)
    for row in rows:
        with st.container(border=True):
            meter, body = st.columns([1, 4], vertical_alignment="center")
            with meter:
                st.markdown(fit_block(row.fit_score), unsafe_allow_html=True)
            with body:
                st.markdown(
                    f'<div class="card-title">{row.title or "—"}</div>'
                    f'<div class="card-meta">{row.company or "—"} · {row.location or "location n/a"} &nbsp; '
                    f'{status_badge(row.sponsorship_signal or "unknown")}</div>',
                    unsafe_allow_html=True,
                )
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
    st.markdown('</div>', unsafe_allow_html=True)


def _render_pipeline_card(session, row: PipelineRow) -> None:
    with st.container(border=True):
        head, badges = st.columns([3, 2], vertical_alignment="center")
        with head:
            st.markdown(
                f'<div class="card-title">{row.title or "—"}</div>'
                f'<div class="card-meta">{row.company or "—"}</div>',
                unsafe_allow_html=True,
            )
        with badges:
            fit = f"{row.fit_score}" if row.fit_score is not None else "—"
            st.markdown(
                '<div style="text-align:right">'
                f'{status_badge(row.status)} &nbsp; '
                f'<span class="badge" style="--badge:{AMBER}">fit {fit}</span></div>',
                unsafe_allow_html=True,
            )

        if row.pdf_path and Path(row.pdf_path).exists():
            st.download_button(
                "⤓ Download PDF", data=Path(row.pdf_path).read_bytes(),
                file_name=Path(row.pdf_path).name, mime="application/pdf", key=f"dl-{row.job_id}",
            )
        elif row.pdf_path:
            st.caption(f"PDF expected at {row.pdf_path} (file not found)")

        with st.expander("Job description"):
            st.write(row.jd_text or "—")
        with st.expander("Latest review critiques"):
            st.json(row.critique_json or [])

        statuses = [s.value for s in ApplicationStatus]
        current = row.application_status or ApplicationStatus.ready.value
        set_col, note_col = st.columns([1, 2])
        with set_col:
            new_status = st.selectbox(
                "Application status", statuses, index=statuses.index(current), key=f"status-{row.job_id}"
            )
        with note_col:
            notes = st.text_input("Notes", key=f"notes-{row.job_id}", placeholder="e.g. applied via referral")
        if st.button("Save status", key=f"save-{row.job_id}"):
            application = application_for_job(session, row.job_id)
            if application is None:
                save_application(session, _new_application(row.job_id, new_status, notes))
            else:
                if application.id is None:
                    st.error("Cannot update an application that has not been persisted.")
                    st.rerun()
                    return
                update_application_status(session, application.id, new_status, notes or None)
            st.success("Saved.")
            st.rerun()


def render_pipeline_page(session) -> None:
    rows = pipeline_rows(session)
    masthead(
        "Mission control",
        'Pipeline <span class="dot">/</span> Board',
        "Every job by pipeline stage, with its tailored PDF, review critiques, and your application status.",
    )

    if not rows:
        empty_state(
            "◇",
            "No jobs in the pipeline",
            "Start with <code>resume-agent addjob</code> or <code>resume-agent scrape</code>.",
        )
        return

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    rendered = counts.get(JobStatus.rendered.value, 0)
    metric_row([("Total jobs", str(len(rows))), ("Rendered", str(rendered)),
                ("Stages active", str(len(counts)))])

    present = [s for s in _STATUS_ORDER if s in counts]
    present += [s for s in counts if s not in _STATUS_ORDER]
    for status in present:
        st.markdown(f'<div class="rail-head">{status} · {counts[status]}</div>', unsafe_allow_html=True)
        for row in [r for r in rows if r.status == status]:
            _render_pipeline_card(session, row)


def render_analytics_page(session) -> None:
    rows = analytics_table_rows(session, by="source")
    masthead(
        "Conversion",
        'Analytics <span class="dot">/</span> Funnel',
        "Which sources and fit-score bands actually convert. Rates are share of submitted applications.",
    )
    total_apps = sum(row["Apps"] for row in rows)
    total_offers = sum(row["Offers"] for row in rows)
    metric_row(
        [
            ("Submitted", str(total_apps)),
            ("Offers", str(total_offers)),
            ("Sources tracked", str(len(rows))),
        ]
    )

    if total_apps == 0:
        empty_state(
            "◇",
            "No applications tracked yet",
            "Mark applications as submitted in the Pipeline board to populate analytics.",
        )
        return

    st.markdown('<div class="rail-head">By source</div>', unsafe_allow_html=True)
    st.table(rows)
    st.markdown('<div class="rail-head">By fit-score band</div>', unsafe_allow_html=True)
    st.table(analytics_table_rows(session, by="band"))


def render_match_gap_page(session) -> None:
    masthead(
        "Closed loop",
        'Match <span class="dot">/</span> Gap',
        "Skills your target jobs demand that your profile does not show yet. Read-only.",
    )

    if not Path(_FACTS_PATH).exists():
        empty_state(
            "◇",
            "No profile yet",
            "Run <code>resume-agent profile build</code> to create your fact-lock profile first.",
        )
        return

    report = match_gap(session, load_facts(_FACTS_PATH))
    metric_row(
        [("Target jobs", str(report.target_total)), ("Distinct gaps", str(len(report.gaps)))]
    )

    if report.target_total == 0:
        empty_state("◇", "No target jobs yet", "Shortlist or approve jobs to populate the gap report.")
        return
    if not report.gaps:
        empty_state("◆", "No gaps", "Your profile covers every required skill across your target jobs.")
        return

    st.markdown('<div class="rail-head">Most-demanded missing skills</div>', unsafe_allow_html=True)
    st.table(match_gap_table_rows(report))
```

- [ ] **Step 2: Verify the module imports**

Run: `uv run python -c "import resume_agent.dashboard.pages"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/resume_agent/dashboard/pages.py
git commit -m "feat(dashboard): extract page renderers into pages.py"
```

---

### Task 4: Slim `app.py` to router + re-exports; inject `THEME_CSS`

Rewrite `app.py` to: load `THEME_CSS` from `ui.py`, render the sidebar nav, route to `pages.py`, and **re-export** the public API so existing tests resolve their imports. (`THEME_CSS` is added in Task 5; reference it now and Task 5 fills it.)

**Files:**

- Modify: `src/resume_agent/dashboard/app.py` (full rewrite)
- Modify: `src/resume_agent/dashboard/ui.py` (add `THEME_CSS = ""` placeholder so the import resolves)
- Test: `tests/test_dashboard_app.py`, `tests/test_dashboard_analytics.py`, `tests/test_dashboard_match_gap.py` (unchanged)

- [ ] **Step 1: Add a placeholder `THEME_CSS` to `ui.py`**

At the top of `src/resume_agent/dashboard/ui.py`, below the docstring:

```python
THEME_CSS = "<style></style>"  # filled in Task 5
```

- [ ] **Step 2: Rewrite `app.py`**

```python
# src/resume_agent/dashboard/app.py
"""Broadsheet — a light editorial control-room for the job hunt.

Thin shell: theme injection, sidebar nav, and page routing only. The design
system lives in ui.py; the page bodies live in pages.py. Public names are
re-exported here so callers (and tests) can import them from this module.
"""

import streamlit as st

from resume_agent.config import get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.dashboard.ui import (  # noqa: F401  (re-exported)
    THEME_CSS,
    fit_block,
    status_badge,
)
from resume_agent.dashboard.pages import (  # noqa: F401  (re-exported)
    analytics_table_rows,
    match_gap_table_rows,
    render_analytics_page,
    render_match_gap_page,
    render_pipeline_page,
    render_shortlist_page,
)


def _engine():
    engine = make_engine(get_settings().db_url)
    init_db(engine)
    return engine


def main() -> None:
    st.set_page_config(page_title="Resume Agent — Broadsheet", page_icon="▤", layout="wide")
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(
            '<div class="masthead-kicker">Resume Agent</div>'
            '<div class="nameplate">The Broadsheet</div>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "View",
            ["Shortlist", "Pipeline board", "Analytics", "Match-gap"],
            label_visibility="collapsed",
        )

    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        elif page == "Analytics":
            render_analytics_page(session)
        else:
            render_match_gap_page(session)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the full dashboard test suite to verify the split is behavior-preserving**

Run: `uv run pytest tests/test_dashboard_app.py tests/test_dashboard_analytics.py tests/test_dashboard_match_gap.py tests/test_dashboard_ui.py -v`
Expected: PASS (all existing dashboard tests + the new ui tests). The `AppTest.from_file` smoke test renders the slimmed app without exception.

- [ ] **Step 4: Commit**

```bash
git add src/resume_agent/dashboard/app.py src/resume_agent/dashboard/ui.py
git commit -m "refactor(dashboard): slim app.py to router + re-exports"
```

---

### Task 5: Broadsheet `THEME_CSS` (light identity + responsive grid)

Replace the placeholder `THEME_CSS` with the full Broadsheet stylesheet: Newsreader/IBM Plex Mono/IBM Plex Sans, paper palette, hairline rules, the `.card-grid` responsive grid (4-up on 4K), wide container, `clamp()` type, and re-themed stock elements (tables, selectbox, expander, buttons).

**Files:**

- Modify: `src/resume_agent/dashboard/ui.py` (replace `THEME_CSS`)
- Test: `tests/test_dashboard_app.py` (the `AppTest` smoke test re-run)

- [ ] **Step 1: Replace `THEME_CSS`**

```python
# src/resume_agent/dashboard/ui.py  — replace the THEME_CSS placeholder
THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600;6..72,700&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
  --paper:#f4f1ea; --paper-2:#efeae0; --ink:#16130f; --muted:#6c6253;
  --oxblood:#8c2f1f; --rule:rgba(22,19,15,0.16);
}

.stApp { background: var(--paper); color: var(--ink); }
.block-container { padding-top: 2.2rem; max-width: 2400px; }

html, body, [class*="css"], .stMarkdown, p, li, label,
.stTextInput input, .stSelectbox div, .stDataFrame, table {
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
}
h1, h2, h3, h4, .card-title, .nameplate, .empty-title {
  font-family: 'Newsreader', Georgia, serif !important; letter-spacing: -0.01em;
}

/* ── Masthead / nameplate ─────────────────────────────────────── */
.nameplate { font-family:'Newsreader',serif; font-size: 1.7rem; font-weight: 700; margin-bottom: 1rem; }
.masthead { margin: 0 0 1.6rem 0; padding-bottom: 1.0rem; border-bottom: 2px solid var(--ink); }
.masthead-kicker {
  font-family:'IBM Plex Mono', monospace; font-size: 0.72rem; letter-spacing: 0.34em;
  text-transform: uppercase; color: var(--oxblood); margin-bottom: 0.5rem;
}
.masthead-title { font-size: clamp(2.2rem, 2.4vw, 3.0rem); font-weight: 700; line-height: 1.02; margin: 0; color: var(--ink); }
.masthead-title .dot { color: var(--oxblood); }
.masthead-sub { color: var(--muted); margin-top: 0.5rem; font-size: 1.0rem; max-width: 70ch; }

/* ── Metric strip ─────────────────────────────────────────────── */
.metric-row { display:flex; gap: 1.0rem; margin: 0.4rem 0 1.6rem 0; flex-wrap: wrap; }
.metric { flex:1; min-width: 150px; background: var(--paper-2); border:1px solid var(--rule); border-radius: 4px; padding: 1.0rem 1.2rem; }
.metric-value { font-family:'Newsreader', serif; font-size: clamp(1.8rem, 1.8vw, 2.4rem); font-weight: 700; color: var(--ink); line-height:1; }
.metric-label { font-family:'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted); margin-top: 0.45rem; }

/* ── Responsive card grid (the 4K fill) ───────────────────────── */
.card-grid { /* marker; the bordered containers below it flow in a grid */ }
.card-grid + div[data-testid="stVerticalBlock"] {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: clamp(0.8rem, 1vw, 1.4rem);
}

/* ── Badges ───────────────────────────────────────────────────── */
.badge { display:inline-block; font-family:'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.12em; text-transform: uppercase; padding: 0.2rem 0.6rem; border-radius: 3px; color: var(--badge, #6c6253); border: 1px solid color-mix(in srgb, var(--badge, #6c6253) 55%, transparent); background: color-mix(in srgb, var(--badge, #6c6253) 12%, transparent); white-space: nowrap; }

/* ── Fit block ────────────────────────────────────────────────── */
.fit { text-align:center; }
.fit-num { font-family:'Newsreader', serif; font-size: clamp(2.0rem, 2vw, 2.8rem); font-weight: 700; line-height: 1; }
.fit-num .fit-max { font-family:'IBM Plex Mono', monospace; font-size: 0.8rem; color: var(--muted); }
.fit-bar { height: 5px; border-radius: 999px; background: rgba(22,19,15,0.12); margin: 0.5rem 0 0.3rem; overflow:hidden; }
.fit-fill { height: 100%; border-radius: 999px; }
.fit-cap { font-family:'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.22em; color: var(--muted); }

.card-title { font-size: 1.32rem; font-weight: 600; color: var(--ink); margin: 0; }
.card-meta { color: var(--muted); font-size: 0.92rem; margin-top: 0.15rem; }
.rationale { color: #3f382e; font-size: 0.95rem; line-height: 1.5; margin-top: 0.5rem; border-left: 2px solid var(--oxblood); padding-left: 0.8rem; }
.rail-head { font-family:'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.24em; font-size: 0.74rem; color: var(--muted); margin: 1.5rem 0 0.4rem; display:flex; align-items:center; gap: 0.7rem; }
.rail-head::after { content:""; flex:1; height:1px; background: var(--rule); }

/* ── Cards (Streamlit bordered containers) ────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--paper-2); border: 1px solid var(--rule) !important; border-radius: 6px;
  box-shadow: 0 1px 0 rgba(22,19,15,0.04); transition: border-color .18s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: var(--oxblood) !important; }

/* ── Buttons ──────────────────────────────────────────────────── */
.stButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; border-radius: 3px; border: 1px solid var(--oxblood); background: var(--oxblood); color: var(--paper); font-weight: 600; padding: 0.45rem 1.1rem; transition: all .15s ease; }
.stButton > button:hover { background: #75271a; border-color:#75271a; }
.stDownloadButton > button { font-family:'IBM Plex Mono', monospace; font-size: 0.74rem; letter-spacing: 0.06em; border-radius: 3px; background: transparent; color: var(--ink); border: 1px solid var(--rule); }
.stDownloadButton > button:hover { border-color: var(--oxblood); color: var(--oxblood); }

/* ── Sidebar ──────────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: var(--paper-2); border-right: 2px solid var(--ink); }
[data-testid="stSidebar"] .stRadio label { font-family:'IBM Plex Sans'; }

/* ── Inputs / tables / expander (re-themed for paper) ─────────── */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div { background: #fff !important; border-color: var(--rule) !important; border-radius: 3px !important; color: var(--ink) !important; }
[data-testid="stExpander"] summary { font-family:'IBM Plex Mono', monospace; font-size: 0.76rem; letter-spacing: 0.06em; color: var(--muted); }
table { border-collapse: collapse; }
thead th { font-family:'IBM Plex Mono', monospace !important; font-size: 0.7rem !important; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted) !important; border-bottom: 2px solid var(--ink) !important; }
tbody td { border-bottom: 1px solid var(--rule) !important; }

/* ── Focus visibility (keyboard a11y) ─────────────────────────── */
.stButton > button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.stTextInput input:focus-visible, .stSelectbox [data-baseweb="select"] > div:focus-within { border-color: var(--oxblood) !important; box-shadow: 0 0 0 2px color-mix(in srgb, var(--oxblood) 30%, transparent) !important; }

/* ── Empty states ─────────────────────────────────────────────── */
.empty-state { text-align:center; padding: 3.4rem 1.2rem; border: 1px dashed var(--rule); border-radius: 6px; margin-top: 0.4rem; background: var(--paper-2); }
.empty-glyph { font-family:'Newsreader', serif; font-size: 2.6rem; color: var(--oxblood); opacity: .9; line-height: 1; }
.empty-title { font-size: 1.34rem; color: var(--ink); margin-top: .5rem; }
.empty-body { color: var(--muted); font-size: .96rem; margin-top: .45rem; }
.empty-body code { font-family:'IBM Plex Mono', monospace; font-size: .85em; color: var(--ink); background: #fff; border: 1px solid var(--rule); border-radius: 3px; padding: .1rem .42rem; }

@media (prefers-reduced-motion: reduce) { *, .masthead { animation: none !important; transition: none !important; } }
#MainMenu, footer { visibility: hidden; }
</style>
"""
```

- [ ] **Step 2: Run the dashboard smoke test**

Run: `uv run pytest tests/test_dashboard_app.py -v`
Expected: PASS — `AppTest` renders the themed app with no exception.

- [ ] **Step 3: Commit**

```bash
git add src/resume_agent/dashboard/ui.py
git commit -m "feat(dashboard): Broadsheet light identity + responsive 4K grid CSS"
```

---

### Task 6: Light Broadsheet `.streamlit/config.toml`

**Files:**

- Modify: `.streamlit/config.toml`

- [ ] **Step 1: Replace the theme block**

```toml
# "Broadsheet" — light editorial control-room theme for Resume Agent.
[theme]
base = "light"
primaryColor = "#8c2f1f"
backgroundColor = "#f4f1ea"
secondaryBackgroundColor = "#efeae0"
textColor = "#16130f"
font = "sans serif"

[server]
headless = true
```

- [ ] **Step 2: Verify it parses by launching headlessly for 3 seconds (manual)**

Run: `uv run resume-agent dashboard` then stop it (Ctrl-C). Expected: Streamlit starts with no theme-parse warning.

- [ ] **Step 3: Commit**

```bash
git add .streamlit/config.toml
git commit -m "feat(dashboard): light Broadsheet streamlit theme config"
```

---

### Task 7: Manual 4K visual verification

This task has no automated test (CSS rendering is out of unit-test scope per the spec). It is a required manual checkpoint.

**Files:** none.

- [ ] **Step 1: Seed a little data and launch**

Run: `uv run resume-agent dashboard`
Open the local URL in a browser maximized on the 32″ 4K display (or emulate ~2560px width via the browser devtools responsive mode).

- [ ] **Step 2: Verify the checklist**

Confirm visually:

- Shortlist cards reflow to **~4 columns** at full 4K width, ~2 at ~1440px, 1 on a laptop.
- Newsreader serif headlines, IBM Plex Mono figures/kickers, IBM Plex Sans body.
- Paper canvas `#f4f1ea`, oxblood accent only on the kicker, fit numbers, rules, and the Approve button.
- Analytics & Match-gap tables read cleanly on the light canvas (mono uppercase headers, hairline rows).
- No leftover dark panels or unreadable low-contrast text.

- [ ] **Step 3: Run the full suite once more**

Run: `uv run pytest -q`
Expected: PASS (no regressions across the repo). Run `uv run ruff check src/resume_agent/dashboard` — expected: clean.

- [ ] **Step 4: Commit any final tweaks**

```bash
git add -A
git commit -m "chore(dashboard): 4K visual pass tweaks"
```

---

## Self-Review

**Spec coverage:**

- §4.1 module split → Tasks 1–4. ✓ (re-export contract verified against the three test files.)
- §4.2 Broadsheet identity (3 families, palette, motifs) → Tasks 2 (palette consts) + 5 (CSS) + 6 (config). ✓
- §4.3 adaptive 4K layout (`column_count`, `.card-grid`, 2400px, `clamp()`) → Tasks 1 + 5 + 6 + 7. ✓
- §4.4 stock-element theming → Task 5 (table/selectbox/expander/button rules). ✓
- §4.5 out of scope (no new features) → honored; only layout/identity/split touched. ✓
- §6 testing (column_count, moved helpers, smoke) → Tasks 1, 2, 4. ✓

**Placeholder scan:** `THEME_CSS = "<style></style>"` is an _intentional, named_ placeholder filled in the very next task (4→5), not a plan gap. No "TBD"/"add error handling" present.

**Type consistency:** Helper names are consistent across tasks — `masthead`/`metric_row`/`empty_state` (renamed from the underscored `app.py` originals) are defined in Task 2 and consumed in Task 3; `status_badge`/`fit_block`/`column_count`/`AMBER`/`THEME_CSS` names match between definition and import sites. `app.py` re-exports exactly the four names the tests import.
