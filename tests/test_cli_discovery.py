from sqlmodel import select

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def test_addjob_inserts_via_stdin(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    result = runner.invoke(
        cli.app,
        ["addjob", "--db-url", db_url, "--company", "Acme", "--title", "Engineer"],
        input="A job description from stdin",
    )
    assert result.exit_code == 0, result.output
    assert "Added job" in result.output

    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        jobs = s.exec(select(Job)).all()
        assert len(jobs) == 1
        assert jobs[0].company == "Acme"
        assert jobs[0].status == JobStatus.raw.value


def test_addjob_reports_duplicate(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    runner.invoke(cli.app, ["addjob", "--db-url", db_url], input="same jd")
    result = runner.invoke(cli.app, ["addjob", "--db-url", db_url], input="same jd")
    assert result.exit_code == 0
    assert "Duplicate" in result.output


def test_discover_runs_and_reports_counts(tmp_path, monkeypatch):
    # The funnel now routes through the discover_jobs service; the CLI just
    # opens a session, calls it, and echoes the counts.
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setattr(
        cli,
        "discover_jobs",
        lambda session, search_path, facts_path, reporter=None: {"shortlisted": 1},
    )

    result = runner.invoke(cli.app, ["discover", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "shortlisted" in result.output


def test_discover_passes_search_and_facts_paths(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    seen = {}

    def fake_discover_jobs(session, search_path, facts_path, reporter=None):
        seen["search"] = search_path
        seen["facts"] = facts_path
        return {"shortlisted": 0}

    monkeypatch.setattr(cli, "discover_jobs", fake_discover_jobs)

    result = runner.invoke(
        cli.app, ["discover", "--db-url", db_url, "--search", "S.yaml", "--facts", "F.json"]
    )
    assert result.exit_code == 0, result.output
    assert seen == {"search": "S.yaml", "facts": "F.json"}


def test_reprocess_invokes_service(tmp_path, monkeypatch):
    import resume_agent.cli as cli

    captured = {}

    def fake_reprocess_jobs(session, *, scopes, search_path, facts_path, reporter=None):
        captured["scopes"] = scopes
        return {"shortlisted": 3}

    monkeypatch.setattr(cli, "reprocess_jobs", fake_reprocess_jobs)
    db_url = f"sqlite:///{tmp_path/'t.db'}"
    result = runner.invoke(
        cli.app, ["reprocess", "--scope", "shortlisted", "--scope", "rejected:relevance",
                  "--db-url", db_url],
    )
    assert result.exit_code == 0
    assert captured["scopes"] == ["shortlisted", "rejected:relevance"]


def test_refresh_invokes_service(tmp_path, monkeypatch):
    import resume_agent.cli as cli
    from pathlib import Path
    from resume_agent.services.discovery import RefreshReport

    monkeypatch.setattr(Path, "exists", lambda self: True)

    def fake_refresh_jobs(session, **kwargs):
        return RefreshReport(pulled=5, totals={"greenhouse": 5},
                             status_counts={"shortlisted": 2}, failures={})

    monkeypatch.setattr(cli, "refresh_jobs", fake_refresh_jobs)
    db_url = f"sqlite:///{tmp_path/'t.db'}"
    result = runner.invoke(cli.app, ["refresh", "--db-url", db_url])
    assert result.exit_code == 0
    assert "5 pulled" in result.output
