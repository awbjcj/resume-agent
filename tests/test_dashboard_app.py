import importlib


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_dashboard_module_exposes_render_functions():
    app = importlib.import_module("resume_agent.dashboard.app")
    # The page renderers and entrypoint exist and are callable.
    assert callable(app.render_shortlist_page)
    assert callable(app.render_pipeline_page)
    assert callable(app.main)


def test_status_badge_returns_html_for_known_status():
    app = importlib.import_module("resume_agent.dashboard.app")
    html = app.status_badge("offered")
    assert "offered" in html.lower()
    assert "span" in html.lower()


def test_dashboard_pages_render_without_error(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import resume_agent.dashboard.app as appmod
    from resume_agent.config import get_settings
    from resume_agent.db import get_session, init_db, make_engine
    from resume_agent.tracking.repository import save_application, save_job, save_resume_version
    from resume_agent.tracking.tables import (
        Application,
        ApplicationStatus,
        Job,
        JobStatus,
        ResumeVersion,
    )

    db_url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    monkeypatch.setenv("DB_URL", db_url)
    get_settings.cache_clear()

    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        save_job(s, Job(source="manual", jd_text="Build backend systems.", company="Acme",
                        title="Backend Engineer", status=JobStatus.shortlisted.value, fit_score=88,
                        fit_rationale="Strong match.", criteria_json={"sponsorship_signal": "offered"}))
        j2 = save_job(s, Job(source="manual", jd_text="Platform role.", company="Beta",
                             title="Platform Eng", status=JobStatus.rendered.value, fit_score=72))
        j2_id = _require_id(j2.id)
        save_resume_version(s, ResumeVersion(job_id=j2_id, round=1, content_json={"contact": {"name": "Ada"}}))
        save_application(s, Application(job_id=j2_id, status=ApplicationStatus.submitted.value))

    try:
        at = AppTest.from_file(appmod.__file__, default_timeout=30).run()
        assert not at.exception, at.exception
        assert any("Approve" in b.label for b in at.button)  # shortlist checkpoint button

        at.radio[0].set_value("Pipeline board").run()
        assert not at.exception, at.exception
    finally:
        get_settings.cache_clear()  # don't leak the temp DB into other tests


def test_dashboard_exposes_triage_page():
    from resume_agent.dashboard import app
    assert callable(app.render_triage_page)


def test_triage_page_renders_with_a_raw_job(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import resume_agent.dashboard.app as appmod
    from resume_agent.config import get_settings
    from resume_agent.db import get_session, init_db, make_engine
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job, JobStatus

    db_url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    monkeypatch.setenv("DB_URL", db_url)
    get_settings.cache_clear()

    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.raw.value, fit_score=20))
    try:
        at = AppTest.from_file(appmod.__file__, default_timeout=30).run()
        at.radio[0].set_value("Triage").run()
        assert not at.exception, at.exception
        assert any(widget.label == "Status" for widget in at.multiselect)
        assert any(widget.label == "Sort by" for widget in at.selectbox)
    finally:
        get_settings.cache_clear()  # don't leak the temp DB into other tests
