from typer.testing import CliRunner

from resume_tailor_harness.cli import app

runner = CliRunner()


def test_setup_command_launches_app(monkeypatch):
    launched = {"ran": False}

    class FakeApp:
        def __init__(self, *a, **k):
            pass

        def run(self):
            launched["ran"] = True

    monkeypatch.setattr("resume_tailor_harness.setup.app.SetupApp", FakeApp)
    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert launched["ran"] is True


def test_setup_is_a_registered_command():
    result = runner.invoke(app, ["--help"])
    assert "setup" in result.stdout
