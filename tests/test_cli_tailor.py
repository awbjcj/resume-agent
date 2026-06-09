from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.repository import get_job
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def _seed(db_url, status):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = Job(source="manual", jd_text="jd", status=status, criteria_json={})
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def test_approve_sets_status_approved(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.shortlisted.value)

    result = runner.invoke(cli.app, ["approve", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output

    engine = make_engine(db_url)
    with get_session(engine) as s:
        assert get_job(s, job_id).status == JobStatus.approved.value


def test_tailor_processes_a_job(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: object())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "build_tailor_agent", lambda: object())
    monkeypatch.setattr(cli, "build_reviser_agent", lambda: object())
    monkeypatch.setattr(cli, "build_reviewer_agents", lambda config: {})

    class _Version:
        fact_check_passed = True

    monkeypatch.setattr(
        cli,
        "tailor_job",
        lambda session, job, facts, config, tailor_agent, reviewer_agents, reviser_agent: [_Version()],
    )

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "1 version" in result.output
