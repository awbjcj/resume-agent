import resume_agent.cli as cli
from resume_agent.discovery.connectors.base import RawJob
from typer.testing import CliRunner

runner = CliRunner()


def _fake_job_from_url(url, *, agent, allow_browser=True):
    return RawJob(
        source="url", url=url, company="Acme", title="Engineer",
        location="Remote", jd_text="Build things.",
    )


def test_addjob_url_extracts_and_inserts(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", _fake_job_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db]
    )

    assert result.exit_code == 0, result.output
    assert "Added job" in result.output
    assert "Acme" in result.output


def test_addjob_url_flags_override_extracted(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", _fake_job_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--company", "Globex", "--db-url", db],
    )

    assert result.exit_code == 0, result.output
    assert "Globex" in result.output


def test_addjob_url_no_extraction_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", lambda *a, **k: None)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db]
    )

    assert result.exit_code == 1
    assert "Couldn't extract" in result.output
