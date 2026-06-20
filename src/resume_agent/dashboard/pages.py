# src/resume_agent/dashboard/pages.py
"""The four dashboard pages — thin compositions over ui.py primitives."""

from pathlib import Path

import streamlit as st

from resume_agent.dashboard.filtering import (
    FilterState,
    apply_filters,
    available_skill_cloud,
    sort_rows,
)
from resume_agent.dashboard.ui import (
    AMBER,
    clamp_text,
    empty_state,
    fit_block,
    masthead,
    meta_line,
    metric_row,
    salary_label,
    skill_chip,
    skill_strip,
    status_badge,
)
from resume_agent.profile.store import load_facts
from resume_agent.tracking.analytics import fit_band_stats, source_stats
from resume_agent.tracking.match_gap import MatchGapReport, match_gap, normalize_skill
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
_SORT_LABELS = {
    "fit": "Fit",
    "salary": "Salary",
    "recency": "Recency",
    "composite": "Composite",
}
_PRESET_LABELS = {
    "balanced": "Balanced",
    "pay_first": "Pay-first",
    "freshest": "Freshest",
}


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


def _control_desk(rows) -> FilterState:
    # A real keyed container (not a bare "<div>" marker, which Streamlit
    # sanitizes into an empty box, stranding the controls below it). The CSS
    # styles div[...][class*="st-key-controldesk"] as the bordered panel.
    with st.container(key="controldesk"):
        st.markdown('<div class="controldesk-head">Filter &amp; sort</div>', unsafe_allow_html=True)
        # Balanced rows: three controls per row keeps the panel aligned without
        # forcing selectboxes into narrow 4-column cells on laptop/tablet widths.
        r1 = st.columns(3, gap="medium", vertical_alignment="top")
        with r1[0]:
            salary_min = st.number_input(
                "Min salary", min_value=0, step=10000, value=0, key="f_salary"
            )
        with r1[1]:
            fit_min = st.slider("Min fit", 0, 100, 0, key="f_fit")
        with r1[2]:
            sort = st.selectbox(
                "Sort by",
                list(_SORT_LABELS),
                format_func=lambda key: _SORT_LABELS[key],
                key="f_sort",
            )

        r2 = st.columns(3, gap="medium", vertical_alignment="top")
        with r2[0]:
            remote = set(st.multiselect("Remote", ["remote", "hybrid", "onsite"], key="f_remote"))
        with r2[1]:
            sponsorship = set(
                st.multiselect("Sponsorship", ["offered", "silent", "denied"], key="f_sponsor")
            )
        with r2[2]:
            seniority = set(
                st.multiselect(
                    "Seniority", ["junior", "mid", "senior", "staff", "principal"], key="f_sen"
                )
            )

        r3 = st.columns(2, gap="medium", vertical_alignment="top")
        with r3[0]:
            employment = set(
                st.multiselect(
                    "Type", ["full_time", "contract", "internship", "part_time"], key="f_emp"
                )
            )
        with r3[1]:
            industry_options = sorted({r.industry for r in rows if r.industry})
            industry = set(st.multiselect("Industry", industry_options, key="f_industry"))

        # Skills spans the row; the composite preset shares it only when needed.
        skill_names = [t.name for t in available_skill_cloud(rows)]
        preset = "balanced"
        if sort == "composite":
            sk_col, preset_col = st.columns([2, 1], gap="medium", vertical_alignment="top")
            with sk_col:
                chosen = st.multiselect("Skills (any match)", skill_names, key="f_skills")
            with preset_col:
                preset = st.radio(
                    "Preset",
                    list(_PRESET_LABELS),
                    format_func=lambda key: _PRESET_LABELS[key],
                    horizontal=True,
                    key="f_preset",
                )
        else:
            chosen = st.multiselect("Skills (any match)", skill_names, key="f_skills")
        skills = {normalize_skill(skill) for skill in chosen}

    return FilterState(
        salary_min=salary_min or None,
        remote=remote,
        sponsorship=sponsorship,
        seniority=seniority,
        employment_type=employment,
        industry=industry,
        fit_min=fit_min or None,
        skills=skills,
        sort=sort,
        preset=preset,
    )


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
            "◇",
            "Nothing shortlisted yet",
            "Run <code>resume-agent discover</code> to score jobs and surface the keepers here.",
        )
        return

    state = _control_desk(rows)
    visible = sort_rows(apply_filters(rows, state), state)

    if not visible:
        empty_state("◇", "No jobs match these filters", "Loosen a filter or clear the skill tags.")
        return

    with st.container(key="cardgrid_shortlist"):
        for row in visible:
            with st.container(border=True):
                # Top-align so content anchors at the card top regardless of how
                # much body it has — a content-light card no longer floats its
                # text to the vertical centre when the grid stretches it.
                meter, body = st.columns([1, 4], vertical_alignment="top")
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
                    # Skills: six-chip preview with an explicit "+N more" toggle
                    # that reveals the rest inline.
                    if row.skills:
                        chips = [
                            skill_chip(tag, active=normalize_skill(tag.name) in state.skills)
                            for tag in row.skills
                        ]
                        st.markdown(skill_strip(chips, head=6), unsafe_allow_html=True)
                    # Rationale: show a substantial preview before the in-place
                    # expansion so the card is useful without an immediate click.
                    if row.fit_rationale:
                        st.markdown(
                            clamp_text(row.fit_rationale, preview_words=100),
                            unsafe_allow_html=True,
                        )
                # Footer button lives OUTSIDE the columns so it spans the full card
                # width and (via CSS margin-top:auto) sits flush at the bottom of
                # every equal-height card — aligning across the row.
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
            salary = salary_label(row.salary_min, row.salary_max)
            bits = [bit for bit in (salary, row.remote_policy, row.seniority) if bit]
            lean = " · ".join(str(bit).replace("_", " ") for bit in bits)
            st.markdown(
                f'<div class="card-title">{row.title or "—"}</div>'
                f'<div class="card-meta">{row.company or "—"}</div>'
                + (f'<div class="metaline">{lean}</div>' if lean else ""),
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

        st.markdown('<div class="rail-head">Job description</div>', unsafe_allow_html=True)
        st.markdown(
            clamp_text(
                row.jd_text or "—",
                body_class="jd-text",
                pre=True,
                preview_words=160,
            ),
            unsafe_allow_html=True,
        )
        with st.expander("Latest review critiques"):
            if row.critique_json is None:
                st.caption("Not tailored yet — run `resume-agent tailor` to generate a review.")
            elif not row.critique_json:
                st.caption("Reviewed — no critiques raised.")
            else:
                st.json(row.critique_json)

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
            elif application.id is None:
                st.error("Cannot update an application that has not been persisted.")
                return
            else:
                update_application_status(session, application.id, new_status, notes or None)
            # No st.rerun() here: an immediate rerun restarts the script and
            # discards this message, so the click appears to do nothing. The
            # selectbox keeps its value via widget state, so a rerun is needless.
            saved = f"Saved — status set to “{new_status}”"
            st.success(saved + (f" · note: {notes}" if notes else ""))


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
        with st.container(key=f"cardgrid_pipeline_{status}"):
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
