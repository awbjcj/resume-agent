"""Midnight Atelier — an editorial control-room for the job hunt.

A deliberately un-SaaS Streamlit dashboard: deep-ink canvas, warm cream type,
a single amber signal accent, Fraunces display serif over IBM Plex Sans with
JetBrains Mono numerals. All Streamlit calls live inside functions so the module
imports cleanly (and tests can import it without a running server).
"""

from pathlib import Path

import streamlit as st

from resume_agent.config import get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.analytics import fit_band_stats, source_stats
from resume_agent.tracking.queries import PipelineRow, pipeline_rows, shortlist_rows
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_agent.tracking.tables import Application, ApplicationStatus, JobStatus

# ── Palette ────────────────────────────────────────────────────────────────
INK = "#12141c"
CREAM = "#ece6da"
MUTED = "#8b8a99"
AMBER = "#e9b44c"
EMERALD = "#5fce8f"
ROSE = "#e0697a"
SKY = "#6cb6e0"

# Both lifecycles + sponsorship signals map into one controlled palette.
STATUS_COLORS = {
    # job pipeline
    "raw": MUTED, "extracted": MUTED, "filtered": SKY, "rejected": ROSE,
    "shortlisted": AMBER, "approved": AMBER, "tailored": SKY, "rendered": EMERALD,
    # application funnel
    "ready": MUTED, "submitted": SKY, "interview": AMBER, "offer": EMERALD, "closed": MUTED,
    # sponsorship
    "offered": EMERALD, "denied": ROSE, "silent": MUTED, "unknown": MUTED,
}

# Human-readable order for the pipeline rails.
_STATUS_ORDER = [s.value for s in JobStatus]

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap');

:root {
  --ink:#12141c; --panel:#191c26; --panel-2:#1f2230;
  --cream:#ece6da; --muted:#8b8a99; --amber:#e9b44c;
  --line:rgba(236,230,218,0.10);
}

/* Canvas: deep ink with a faint amber dawn in the top-left. */
.stApp {
  background:
    radial-gradient(900px 500px at 0% -5%, rgba(233,180,76,0.10), transparent 60%),
    radial-gradient(1100px 700px at 100% 0%, rgba(108,182,224,0.06), transparent 55%),
    var(--ink);
  color: var(--cream);
}
.block-container { padding-top: 2.2rem; max-width: 1120px; }

html, body, [class*="css"], .stMarkdown, p, li, label, .stTextInput input, .stSelectbox div {
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
}
h1, h2, h3, h4 { font-family: 'Fraunces', Georgia, serif !important; letter-spacing: -0.01em; }

/* ── Masthead ─────────────────────────────────────────────── */
.masthead { margin: 0 0 1.6rem 0; padding-bottom: 1.1rem; border-bottom: 1px solid var(--line); }
.masthead-kicker {
  font-family:'JetBrains Mono', monospace; font-size: 0.72rem; letter-spacing: 0.34em;
  text-transform: uppercase; color: var(--amber); margin-bottom: 0.5rem;
}
.masthead-title { font-size: 2.7rem; font-weight: 600; line-height: 1.02; margin: 0; color: var(--cream); }
.masthead-title .dot { color: var(--amber); }
.masthead-sub { color: var(--muted); margin-top: 0.5rem; font-size: 0.98rem; max-width: 60ch; }

/* ── Metric strip ─────────────────────────────────────────── */
.metric-row { display:flex; gap: 0.9rem; margin: 0.4rem 0 1.6rem 0; flex-wrap: wrap; }
.metric {
  flex:1; min-width: 130px; background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border:1px solid var(--line); border-radius: 14px; padding: 0.9rem 1.1rem;
}
.metric-value { font-family:'Fraunces', serif; font-size: 2.0rem; font-weight: 600; color: var(--cream); line-height:1; }
.metric-label { font-family:'JetBrains Mono', monospace; font-size: 0.66rem; letter-spacing: 0.2em;
  text-transform: uppercase; color: var(--muted); margin-top: 0.45rem; }

/* ── Badges ───────────────────────────────────────────────── */
.badge {
  display:inline-block; font-family:'JetBrains Mono', monospace; font-size: 0.66rem;
  letter-spacing: 0.12em; text-transform: uppercase; padding: 0.2rem 0.6rem; border-radius: 999px;
  color: var(--badge, #8b8a99); border: 1px solid color-mix(in srgb, var(--badge, #8b8a99) 55%, transparent);
  background: color-mix(in srgb, var(--badge, #8b8a99) 14%, transparent); white-space: nowrap;
}

/* ── Fit block ────────────────────────────────────────────── */
.fit { text-align:center; }
.fit-num { font-family:'Fraunces', serif; font-size: 2.6rem; font-weight: 700; line-height: 1; }
.fit-num .fit-max { font-family:'JetBrains Mono', monospace; font-size: 0.8rem; color: var(--muted); }
.fit-bar { height: 5px; border-radius: 999px; background: rgba(236,230,218,0.10); margin: 0.5rem 0 0.3rem; overflow:hidden; }
.fit-fill { height: 100%; border-radius: 999px; }
.fit-cap { font-family:'JetBrains Mono', monospace; font-size: 0.6rem; letter-spacing: 0.22em; color: var(--muted); }

.card-title { font-family:'Fraunces', serif; font-size: 1.32rem; font-weight: 600; color: var(--cream); margin: 0; }
.card-meta { color: var(--muted); font-size: 0.9rem; margin-top: 0.15rem; }
.rationale { color: #cfc8ba; font-size: 0.95rem; line-height: 1.5; margin-top: 0.5rem;
  border-left: 2px solid var(--amber); padding-left: 0.8rem; }
.rail-head { font-family:'JetBrains Mono', monospace; text-transform: uppercase; letter-spacing: 0.24em;
  font-size: 0.74rem; color: var(--muted); margin: 1.5rem 0 0.4rem; display:flex; align-items:center; gap: 0.7rem; }
.rail-head::after { content:""; flex:1; height:1px; background: var(--line); }

/* ── Cards (Streamlit bordered containers) ────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--line) !important; border-radius: 16px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.25); transition: border-color .18s ease, transform .18s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: rgba(233,180,76,0.35) !important; transform: translateY(-1px); }

/* ── Buttons ──────────────────────────────────────────────── */
.stButton > button {
  font-family:'JetBrains Mono', monospace; font-size: 0.78rem; letter-spacing: 0.08em;
  text-transform: uppercase; border-radius: 999px; border: 1px solid var(--amber);
  background: var(--amber); color: #1a1407; font-weight: 700; padding: 0.45rem 1.1rem; transition: all .15s ease;
}
.stButton > button:hover { background: #f3c468; border-color:#f3c468; color:#150f04; transform: translateY(-1px); }
.stDownloadButton > button {
  font-family:'JetBrains Mono', monospace; font-size: 0.74rem; letter-spacing: 0.06em;
  border-radius: 999px; background: transparent; color: var(--cream); border: 1px solid var(--line);
}
.stDownloadButton > button:hover { border-color: var(--amber); color: var(--amber); }

/* ── Sidebar ──────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: #0d0f16; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] .stRadio label { font-family:'IBM Plex Sans'; }

/* Inputs */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div {
  background: var(--panel) !important; border-color: var(--line) !important; border-radius: 10px !important;
}
[data-testid="stExpander"] summary { font-family:'JetBrains Mono', monospace; font-size: 0.76rem; letter-spacing: 0.06em; color: var(--muted); }

/* ── Focus visibility (keyboard a11y) ─────────────────────── */
.stButton > button:focus-visible { outline: 2px solid var(--cream); outline-offset: 2px; }
.stDownloadButton > button:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }
.stTextInput input:focus-visible,
.stSelectbox [data-baseweb="select"] > div:focus-within {
  border-color: var(--amber) !important;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--amber) 35%, transparent) !important;
}
[data-testid="stSidebar"] .stRadio label:focus-within { color: var(--amber); }

/* ── Empty states (themed, replaces stock st.info) ────────── */
.empty-state { text-align:center; padding: 3.4rem 1.2rem; border: 1px dashed var(--line);
  border-radius: 16px; margin-top: 0.4rem; background: linear-gradient(180deg, var(--panel-2), var(--panel)); }
.empty-glyph { font-family:'Fraunces', serif; font-size: 2.6rem; color: var(--amber); opacity: .85; line-height: 1; }
.empty-title { font-family:'Fraunces', serif; font-size: 1.34rem; color: var(--cream); margin-top: .5rem; }
.empty-body { color: var(--muted); font-size: .96rem; margin-top: .45rem; }
.empty-body code { font-family:'JetBrains Mono', monospace; font-size: .85em; color: var(--cream);
  background: var(--ink); border: 1px solid var(--line); border-radius: 6px; padding: .1rem .42rem; }

/* ── Entrance: one orchestrated page-load reveal ──────────── */
@keyframes atelier-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.masthead { animation: atelier-rise .5s cubic-bezier(.2,.7,.2,1) both; }
.metric-row { animation: atelier-rise .5s cubic-bezier(.2,.7,.2,1) .07s both; }
.rail-head { animation: atelier-rise .45s cubic-bezier(.2,.7,.2,1) .1s both; }
[data-testid="stVerticalBlockBorderWrapper"] { animation: atelier-rise .45s cubic-bezier(.2,.7,.2,1) .12s both; }

@media (prefers-reduced-motion: reduce) {
  *, .masthead, .metric-row, .rail-head, [data-testid="stVerticalBlockBorderWrapper"] {
    animation: none !important; transition: none !important;
  }
}

#MainMenu, footer { visibility: hidden; }
</style>
"""


# ── Pure helpers (no Streamlit at call time → trivially testable) ───────────
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


def _masthead(kicker: str, title_html: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="masthead"><div class="masthead-kicker">{kicker}</div>'
        f'<h1 class="masthead-title">{title_html}</h1>'
        f'<div class="masthead-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def _metric_row(metrics: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="metric"><div class="metric-value">{value}</div>'
        f'<div class="metric-label">{label}</div></div>'
        for label, value in metrics
    )
    st.markdown(f'<div class="metric-row">{cells}</div>', unsafe_allow_html=True)


def _empty_state(glyph: str, title: str, body_html: str) -> None:
    """Render a themed empty state (keeps the canvas cohesive vs. stock st.info)."""
    st.markdown(
        f'<div class="empty-state"><div class="empty-glyph">{glyph}</div>'
        f'<div class="empty-title">{title}</div>'
        f'<div class="empty-body">{body_html}</div></div>',
        unsafe_allow_html=True,
    )


def _new_application(job_id: int, status: str, notes: str) -> Application:
    return Application(job_id=job_id, status=status, notes=notes or None)


def analytics_table_rows(session, by: str = "source") -> list[dict]:
    """Pure table rows for the analytics page."""
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


# ── Pages ───────────────────────────────────────────────────────────────────
def render_shortlist_page(session) -> None:
    rows = shortlist_rows(session)
    avg = round(sum(r.fit_score or 0 for r in rows) / len(rows)) if rows else 0
    sponsored = sum(1 for r in rows if r.sponsorship_signal == "offered")

    _masthead(
        "Human checkpoint",
        'The Short<span class="dot">·</span>list',
        "The cost gate before the premium tailoring step. Approve only the jobs worth the spend.",
    )
    _metric_row([("Awaiting review", str(len(rows))), ("Avg fit", str(avg)),
                 ("Sponsorship offered", str(sponsored))])

    if not rows:
        _empty_state(
            "◇",
            "Nothing shortlisted yet",
            "Run <code>resume-agent discover</code> to score jobs and surface the keepers here.",
        )
        return

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
    _masthead(
        "Mission control",
        'Pipeline <span class="dot">/</span> Board',
        "Every job by pipeline stage, with its tailored PDF, review critiques, and your application status.",
    )

    if not rows:
        _empty_state(
            "◇",
            "No jobs in the pipeline",
            "Start with <code>resume-agent addjob</code> or <code>resume-agent scrape</code>.",
        )
        return

    counts = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    rendered = counts.get(JobStatus.rendered.value, 0)
    _metric_row([("Total jobs", str(len(rows))), ("Rendered", str(rendered)),
                 ("Stages active", str(len(counts)))])

    present = [s for s in _STATUS_ORDER if s in counts]
    present += [s for s in counts if s not in _STATUS_ORDER]  # any unknown statuses last
    for status in present:
        st.markdown(f'<div class="rail-head">{status} · {counts[status]}</div>', unsafe_allow_html=True)
        for row in [r for r in rows if r.status == status]:
            _render_pipeline_card(session, row)


def render_analytics_page(session) -> None:
    rows = analytics_table_rows(session, by="source")
    _masthead(
        "Conversion",
        'Analytics <span class="dot">/</span> Funnel',
        "Which sources and fit-score bands actually convert. Rates are share of submitted applications.",
    )
    total_apps = sum(row["Apps"] for row in rows)
    total_offers = sum(row["Offers"] for row in rows)
    _metric_row(
        [
            ("Submitted", str(total_apps)),
            ("Offers", str(total_offers)),
            ("Sources tracked", str(len(rows))),
        ]
    )

    if total_apps == 0:
        _empty_state(
            "◇",
            "No applications tracked yet",
            "Mark applications as submitted in the Pipeline board to populate analytics.",
        )
        return

    st.markdown('<div class="rail-head">By source</div>', unsafe_allow_html=True)
    st.table(rows)
    st.markdown('<div class="rail-head">By fit-score band</div>', unsafe_allow_html=True)
    st.table(analytics_table_rows(session, by="band"))


def _engine():
    engine = make_engine(get_settings().db_url)
    init_db(engine)
    return engine


def main() -> None:
    st.set_page_config(page_title="Resume Agent — Atelier", page_icon="◆", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(
            '<div class="masthead-kicker">Resume Agent</div>'
            '<div style="font-family:Fraunces,serif;font-size:1.5rem;font-weight:600;margin-bottom:1rem">'
            'Atelier ◆</div>',
            unsafe_allow_html=True,
        )
        page = st.radio("View", ["Shortlist", "Pipeline board", "Analytics"], label_visibility="collapsed")

    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        else:
            render_analytics_page(session)


if __name__ == "__main__":
    main()
