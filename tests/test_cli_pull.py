from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.discovery.connectors.runner import PullReport

runner = CliRunner()


def test_pull_runs_enabled_connectors_and_reports(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    connectors_file = tmp_path / "connectors.yaml"
    connectors_file.write_text("greenhouse:\n  enabled: true\n", encoding="utf-8")

    report = PullReport()
    report.totals["greenhouse"] = 1
    monkeypatch.setattr(
        cli,
        "pull_jobs",
        lambda session, search_path, connectors_path, telemetry_path, limit=None, reporter=None: report,
    )

    result = runner.invoke(cli.app, ["pull", "--db-url", db_url, "--connectors", str(connectors_file)])

    assert result.exit_code == 0, result.output
    assert "greenhouse" in result.output
    assert "1" in result.output


def test_pull_reports_missing_connectors_config(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    missing = tmp_path / "missing.yaml"

    result = runner.invoke(cli.app, ["pull", "--db-url", db_url, "--connectors", str(missing)])

    assert result.exit_code == 1
    assert "No connectors config found" in result.output
