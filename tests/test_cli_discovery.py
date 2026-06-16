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
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        s.add(Job(source="manual", jd_text="jd", status=JobStatus.raw.value))
        s.commit()

    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "build_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "build_fit_agent", lambda: object())
    monkeypatch.setattr(
        cli, "discover", lambda session, config, facts, extract_agent, fit_agent: {"shortlisted": 1}
    )

    result = runner.invoke(cli.app, ["discover", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "shortlisted" in result.output


def test_discover_reextract_invokes_reextract(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    called = {}

    def fake_reextract(session, agent):
        called["agent"] = agent
        return 3

    extract_agent = object()
    monkeypatch.setattr(cli, "build_extract_agent", lambda: extract_agent)
    monkeypatch.setattr(cli, "reextract", fake_reextract)

    # These should not be needed for --reextract.
    monkeypatch.setattr(
        cli,
        "load_search_config",
        lambda path: (_ for _ in ()).throw(AssertionError("search loaded")),
    )
    monkeypatch.setattr(
        cli, "load_facts", lambda path: (_ for _ in ()).throw(AssertionError("facts loaded"))
    )
    monkeypatch.setattr(
        cli, "build_fit_agent", lambda: (_ for _ in ()).throw(AssertionError("fit built"))
    )

    result = runner.invoke(cli.app, ["discover", "--reextract", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert called["agent"] is extract_agent
    assert "Re-extracted metadata for 3 job(s)." in result.output
