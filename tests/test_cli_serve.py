from typer.testing import CliRunner

from resume_agent import cli


def test_serve_invokes_uvicorn(monkeypatch):
    captured = {}

    def fake_run(app, host, port, **kw):  # uvicorn.run signature (subset)
        captured["host"] = host
        captured["port"] = port

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = CliRunner().invoke(cli.app, ["serve", "--host", "127.0.0.1", "--port", "9123"])
    assert result.exit_code == 0
    assert captured == {"host": "127.0.0.1", "port": 9123}
