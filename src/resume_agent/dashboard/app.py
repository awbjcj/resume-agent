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
    render_analytics_page,
    render_match_gap_page,
    render_pipeline_page,
    render_progress_strip,
    render_shortlist_page,
    render_triage_page,
)


def _engine():
    engine = make_engine(get_settings().db_url)
    init_db(engine)
    return engine


def main() -> None:
    st.set_page_config(
        page_title="Resume Agent — Broadsheet", page_icon="▤", layout="wide"
    )
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(
            '<div class="masthead-kicker">Resume Agent</div>'
            '<div class="nameplate">The Broadsheet</div>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "View",
            ["Shortlist", "Triage", "Pipeline board", "Analytics", "Match-gap"],
            label_visibility="collapsed",
        )

    render_progress_strip()

    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Triage":
            render_triage_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        elif page == "Analytics":
            render_analytics_page(session)
        else:
            render_match_gap_page(session)


if __name__ == "__main__":
    main()
