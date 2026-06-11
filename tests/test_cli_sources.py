from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.discovery.connectors.telemetry import record_run

runner = CliRunner()


def test_sources_lists_recorded_runs(tmp_path, monkeypatch):
    runs_path = tmp_path / "runs.json"
    record_run(runs_path, "greenhouse", added=4, error=None)
    record_run(runs_path, "adzuna", added=0, error="HTTPError: 429")
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(runs_path))

    result = runner.invoke(cli.app, ["sources"])

    assert result.exit_code == 0, result.output
    assert "greenhouse" in result.output and "4" in result.output
    assert "adzuna" in result.output and "429" in result.output


def test_sources_handles_no_history(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(tmp_path / "none.json"))
    result = runner.invoke(cli.app, ["sources"])
    assert result.exit_code == 0
    assert "No connector runs recorded" in result.output
