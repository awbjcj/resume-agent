from sqlmodel import select
from typer.testing import CliRunner

import resume_agent.cli as cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.discovery import UrlFetchError
from resume_agent.tracking.tables import Job

runner = CliRunner()


def _fake_add_from_url(session, *, url, company=None, title=None, location=None, allow_browser=True):
    # The CLI's job: echo "Extracted:" from the returned job and "Added job".
    # URL fetching / override logic now lives in the service (tested there).
    return Job(
        source="url", url=url, company=company or "Acme",
        title=title or "Engineer", location=location or "Remote", jd_text="Build things.",
    )


def test_addjob_url_extracts_and_inserts(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "add_job_from_url", _fake_add_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db])

    assert result.exit_code == 0, result.output
    assert "Added job" in result.output
    assert "Acme" in result.output
    assert "Extracted:" in result.output


def test_addjob_url_flags_override_extracted(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "add_job_from_url", _fake_add_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--company", "Globex", "--db-url", db],
    )

    assert result.exit_code == 0, result.output
    assert "Globex" in result.output


def test_addjob_url_with_jd_file_skips_extraction(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("add_job_from_url must not run when --jd-file is given")

    monkeypatch.setattr(cli, "add_job_from_url", _boom)
    jd = tmp_path / "jd.txt"
    jd.write_text("Manual JD body.", encoding="utf-8")
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--jd-file", str(jd), "--db-url", db],
    )

    assert result.exit_code == 0, result.output
    assert "Added job" in result.output


def test_addjob_url_with_piped_stdin_skips_extraction(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("add_job_from_url must not run when stdin is given")

    monkeypatch.setattr(cli, "add_job_from_url", _boom)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--db-url", db],
        input="Manual JD from stdin.",
    )

    assert result.exit_code == 0, result.output
    engine = make_engine(db)
    init_db(engine)
    with get_session(engine) as session:
        job = session.exec(select(Job)).one()
        assert job.source == "manual"
        assert job.url == "https://acme.test/job"
        assert job.jd_text == "Manual JD from stdin."


def test_addjob_url_fetch_error_exits_cleanly(monkeypatch, tmp_path):
    def _raise(*a, **k):
        raise UrlFetchError("Couldn't fetch https://acme.test/job: boom")

    monkeypatch.setattr(cli, "add_job_from_url", _raise)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db])

    assert result.exit_code == 1
    assert "Couldn't fetch" in result.output


def test_addjob_url_no_extraction_failure(monkeypatch, tmp_path):
    def _raise(*a, **k):
        raise UrlFetchError("Couldn't extract a job description from that URL.")

    monkeypatch.setattr(cli, "add_job_from_url", _raise)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db])

    assert result.exit_code == 1
    assert "Couldn't extract" in result.output
