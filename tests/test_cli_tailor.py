from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.repository import get_job
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _seed(db_url, status):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = Job(source="manual", jd_text="jd", status=status, criteria_json={})
        s.add(job)
        s.commit()
        s.refresh(job)
        return _require_id(job.id)


def test_approve_sets_status_approved(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.shortlisted.value)

    result = runner.invoke(cli.app, ["approve", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output

    engine = make_engine(db_url)
    with get_session(engine) as s:
        job = get_job(s, job_id)
        assert job is not None
        assert job.status == JobStatus.approved.value


def test_tailor_processes_a_job(tmp_path, monkeypatch):
    # The tailor command now delegates to the tailoring service; the CLI keeps
    # the not-found guard and formats the per-job summary line.
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    class _Version:
        fact_check_passed = True

    def fake_tailor(session, *, job_ids=None, approved=False, review_path=None, facts_path=None, reporter=None):
        from resume_agent.tailor.service import TailorOutcome

        return TailorOutcome(
            versions={jid: [_Version()] for jid in (job_ids or [])}, failures={}
        )

    monkeypatch.setattr(cli, "tailor", fake_tailor)

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "1 version" in result.output


def test_tailor_reports_missing_job(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)

    result = runner.invoke(cli.app, ["tailor", "--job-id", "999", "--db-url", db_url])

    assert result.exit_code == 1
    assert "Job #999 not found" in result.output
