from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tailor.review_config import ReviewConfig
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
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: ReviewConfig())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "load_style_guide", lambda path: None)
    monkeypatch.setattr(cli, "build_tailor_agent", lambda style_guide=None: object())
    monkeypatch.setattr(cli, "build_reviser_agent", lambda style_guide=None: object())
    monkeypatch.setattr(cli, "build_reviewer_agents", lambda config, style_guide=None: {})

    class _Version:
        fact_check_passed = True

    monkeypatch.setattr(
        cli,
        "tailor_jobs",
        lambda session, targets, facts, config, tailor_agent, reviewer_agents, reviser_agent, reporter=None: {  # noqa: E501
            _require_id(job.id): [_Version()] for job in targets
        },
    )

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "1 version" in result.output


def test_tailor_threads_style_guide_into_all_loop_agents(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: ReviewConfig())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "load_style_guide", lambda path: "HOUSE STYLE TEXT")

    seen: dict[str, object] = {}

    def fake_tailor(style_guide=None):
        seen["tailor"] = style_guide
        return object()

    def fake_reviser(style_guide=None):
        seen["reviser"] = style_guide
        return object()

    def fake_reviewers(config, style_guide=None):
        seen["reviewers"] = style_guide
        return {}

    monkeypatch.setattr(cli, "build_tailor_agent", fake_tailor)
    monkeypatch.setattr(cli, "build_reviser_agent", fake_reviser)
    monkeypatch.setattr(cli, "build_reviewer_agents", fake_reviewers)

    class _Version:
        fact_check_passed = True

    monkeypatch.setattr(cli, "tailor_jobs", lambda *args, **kwargs: {1: [_Version()]})

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert seen == {
        "tailor": "HOUSE STYLE TEXT",
        "reviser": "HOUSE STYLE TEXT",
        "reviewers": "HOUSE STYLE TEXT",
    }


def test_tailor_reports_missing_job(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)

    result = runner.invoke(cli.app, ["tailor", "--job-id", "999", "--db-url", db_url])

    assert result.exit_code == 1
    assert "Job #999 not found" in result.output
