from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.discovery.connectors.base import RawJob

runner = CliRunner()


class _Conn:
    name = "greenhouse"

    def fetch(self, search, limit=None):
        return [RawJob("greenhouse", "https://gh/1", "Acme", "Engineer", "Remote", "a real jd")]


def test_pull_runs_enabled_connectors_and_reports(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    connectors_file = tmp_path / "connectors.yaml"
    connectors_file.write_text("greenhouse:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "load_connectors_config", lambda path: object())
    monkeypatch.setattr(cli, "build_connectors", lambda cfg, settings: [_Conn()])
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(tmp_path / "runs.json"))

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
