from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.gmail.client import EmailMessage
from resume_agent.tracking.repository import application_for_job, save_application
from resume_agent.tracking.tables import Application, ApplicationStatus

runner = CliRunner()


def _seed(db_url):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        job = add_job(
            session, source="manual", jd_text="jd", company="Acme", title="Eng"
        )
        assert job is not None and job.id is not None
        save_application(
            session,
            Application(job_id=job.id, status=ApplicationStatus.submitted.value),
        )


def test_sync_status_lists_then_applies(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    monkeypatch.setattr(cli, "build_gmail_service", lambda: object())
    monkeypatch.setattr(
        cli,
        "fetch_recent_messages",
        lambda service, max_results=50: [
            EmailMessage(
                sender="ta@acme.com",
                sender_domain="acme.com",
                subject="Interview invitation",
                snippet="schedule a phone screen",
            )
        ],
    )

    listed = runner.invoke(cli.app, ["sync-status", "--db-url", db_url])
    assert listed.exit_code == 0, listed.output
    assert "Acme" in listed.output and "interview" in listed.output
    assert "--apply" in listed.output

    applied = runner.invoke(cli.app, ["sync-status", "--apply", "--db-url", db_url])
    assert applied.exit_code == 0, applied.output

    from sqlmodel import select

    from resume_agent.tracking.tables import Job

    with get_session(make_engine(db_url)) as session:
        acme = session.exec(select(Job).where(Job.company == "Acme")).first()
        assert acme is not None and acme.id is not None
        application = application_for_job(session, acme.id)
        assert application is not None
        assert application.status == ApplicationStatus.interview.value
