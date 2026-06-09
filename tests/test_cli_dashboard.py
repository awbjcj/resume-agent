from typer.testing import CliRunner

from resume_agent import cli

runner = CliRunner()


def test_dashboard_launches_streamlit(monkeypatch):
    captured = {}

    def fake_run(args, env=None):
        captured["args"] = args
        captured["env"] = env

        class _CP:
            returncode = 0

        return _CP()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["dashboard", "--db-url", "sqlite:///tmp.db"])
    assert result.exit_code == 0, result.output
    assert captured["args"][0] == "streamlit"
    assert captured["args"][1] == "run"
    assert captured["args"][2].endswith("app.py")
    assert captured["env"]["DB_URL"] == "sqlite:///tmp.db"
