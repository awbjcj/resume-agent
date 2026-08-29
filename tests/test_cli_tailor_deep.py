from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.tailor.service import TailorOutcome
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import JobStatus

runner = CliRunner()


def _seed(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        job = add_job(
            session,
            source="manual",
            jd_text="jd",
            company="Acme",
            title="Engineer",
        )
        assert job is not None
        job.status = JobStatus.approved.value
        save_job(session, job)
    return db_url


def test_tailor_deep_flag_selects_deep_config(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli,
        "tailor",
        lambda session, *, review_path, **kwargs: (
            captured.update(review_path=review_path) or TailorOutcome()
        ),
    )

    result = runner.invoke(
        cli.app,
        ["tailor", "--approved", "--deep", "--db-url", _seed(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert captured["review_path"] == "config/review_deep.yaml"


def test_tailor_explicit_review_wins_over_deep(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli,
        "tailor",
        lambda session, *, review_path, **kwargs: (
            captured.update(review_path=review_path) or TailorOutcome()
        ),
    )

    result = runner.invoke(
        cli.app,
        [
            "tailor",
            "--approved",
            "--deep",
            "--review",
            "custom.yaml",
            "--db-url",
            _seed(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["review_path"] == "custom.yaml"
