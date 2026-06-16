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
    assert "Extracted:" in result.output


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


def test_addjob_url_with_jd_file_skips_extraction(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("job_from_url must not run when --jd-file is given")

    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", _boom)
    jd = tmp_path / "jd.txt"
    jd.write_text("Manual JD body.", encoding="utf-8")
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--jd-file", str(jd), "--db-url", db],
    )

    assert result.exit_code == 0, result.output
    assert "Added job" in result.output


def test_addjob_url_no_extraction_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", lambda *a, **k: None)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db]
    )

    assert result.exit_code == 1
    assert "Couldn't extract" in result.output
