from pathlib import Path

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import CoverLetter, JobStatus

runner = CliRunner()


def test_cover_letter_command_generates_and_renders(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        assert job is not None
        job.status = JobStatus.approved.value
        save_job(s, job)

    monkeypatch.setattr(cli, "load_facts", lambda path: ProfileFacts(contact=Contact(name="Ada")))
    monkeypatch.setattr(cli, "build_cover_letter_agent", lambda: object())
    monkeypatch.setattr(cli, "build_cover_letter_reviser_agent", lambda: object())
    monkeypatch.setattr(
        cli,
        "generate_cover_letter",
        lambda session, job, facts, draft_agent, reviser_agent: CoverLetter(
            id=1, job_id=job.id, fact_check_passed=True
        ),
    )
    monkeypatch.setattr(cli, "render_cover_letter", lambda session, cl_id: Path("output/x.pdf"))

    result = runner.invoke(cli.app, ["cover-letter", "--approved", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "cover letter" in result.output.lower()
