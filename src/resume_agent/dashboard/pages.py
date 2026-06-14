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
