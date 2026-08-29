from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def _seed(db_url: str) -> None:
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        save_job(s, Job(source="m", jd_text="a", status=JobStatus.rejected.value))


def test_prune_dry_run_changes_nothing(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    result = runner.invoke(
        cli.app,
        [
            "prune",
            "--db-url",
            db_url,
            "--dry-run",
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()

    engine = make_engine(db_url)
    with get_session(engine) as s:
        from sqlmodel import select

        job = s.exec(select(Job)).first()
        assert job is not None and job.archived_at is None


def test_prune_applies_and_reports(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    result = runner.invoke(
        cli.app,
        ["prune", "--db-url", db_url, "--config", str(tmp_path / "absent.yaml")],
    )
    assert result.exit_code == 0, result.output
    assert "archived" in result.output.lower()

    engine = make_engine(db_url)
    with get_session(engine) as s:
        from sqlmodel import select

        job = s.exec(select(Job)).first()
        assert job is not None and job.archived_at is not None
