from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.services.cover_letters import CoverLetterResult
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import JobStatus

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

    monkeypatch.setattr(
        cli,
        "write_cover_letters",
        lambda session, job_ids=None, approved=False, facts_path=None: [
            CoverLetterResult(
                job_id=1,
                cover_letter_id=1,
                fact_check_passed=True,
                pdf_path="output/x.pdf",
            )
        ],
    )

    result = runner.invoke(cli.app, ["cover-letter", "--approved", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "cover letter" in result.output.lower()
