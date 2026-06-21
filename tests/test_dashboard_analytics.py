from sqlmodel import Session, SQLModel, create_engine

from resume_agent.dashboard.app import render_analytics_page
from resume_agent.dashboard.pages import analytics_table_rows
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, ApplicationStatus, Job


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_render_analytics_page_is_importable_and_callable():
    assert callable(render_analytics_page)


def test_analytics_table_rows_formats_counts_and_rates():
    with _session() as session:
        job = save_job(
            session,
            Job(
                source="greenhouse",
                company="C",
                title="T",
                fit_score=85,
                status="rendered",
            ),
        )
        assert job.id is not None
        save_application(
            session,
            Application(job_id=job.id, status=ApplicationStatus.interview.value),
        )

        rows = analytics_table_rows(session, by="source")
        assert rows == [
            {
                "Source": "greenhouse",
                "Apps": 1,
                "Responses": 1,
                "Interviews": 1,
                "Offers": 0,
                "Interview %": 100,
                "Offer %": 0,
            },
        ]
