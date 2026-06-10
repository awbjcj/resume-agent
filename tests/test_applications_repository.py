from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.repository import (
    application_for_job,
    applications_by_status,
    get_application,
    latest_resume_version,
    latest_rendered_resume_version,
    save_application,
    save_resume_version,
    update_application_status,
)
from resume_agent.tracking.tables import Application, ApplicationStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_application_crud_and_lookup():
    with _session() as s:
        app = save_application(s, Application(job_id=1, status=ApplicationStatus.ready.value))
        assert get_application(s, app.id).job_id == 1
        assert application_for_job(s, 1).id == app.id
        assert application_for_job(s, 999) is None
        assert [a.id for a in applications_by_status(s, ApplicationStatus.ready.value)] == [app.id]


def test_update_application_status_and_notes():
    with _session() as s:
        app = save_application(s, Application(job_id=1, status=ApplicationStatus.ready.value))
        updated = update_application_status(
            s, app.id, ApplicationStatus.submitted.value, notes="applied via portal"
        )
        assert updated.status == ApplicationStatus.submitted.value
        assert updated.notes == "applied via portal"


def test_submitted_status_sets_submitted_at_once():
    with _session() as s:
        created = save_application(s, Application(job_id=1, status=ApplicationStatus.submitted.value))
        assert created.submitted_at is not None

        ready = save_application(s, Application(job_id=2, status=ApplicationStatus.ready.value))
        assert ready.submitted_at is None

        submitted = update_application_status(s, ready.id, ApplicationStatus.submitted.value)
        assert submitted.submitted_at is not None

        first_submitted_at = submitted.submitted_at
        updated = update_application_status(s, submitted.id, ApplicationStatus.submitted.value, notes="done")
        assert updated.submitted_at == first_submitted_at


def test_latest_resume_version_picks_highest_round():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, content_json={"a": 1}))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        latest = latest_resume_version(s, 7)
        assert latest.round == 2
        assert latest_resume_version(s, 999) is None


def test_latest_rendered_resume_version_picks_highest_round_with_pdf():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, content_json={"a": 1}, pdf_path="one.pdf"))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        save_resume_version(s, ResumeVersion(job_id=7, round=3, content_json={"a": 3}, pdf_path="three.pdf"))
        latest = latest_rendered_resume_version(s, 7)
        assert latest.round == 3
        assert latest.pdf_path == "three.pdf"
