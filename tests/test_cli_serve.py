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


def test_serve_refuses_to_expose_auth_free_local_mode(monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)
    result = CliRunner().invoke(cli.app, ["serve", "--host", "0.0.0.0"])

    assert result.exit_code != 0
    assert "--mode hosted" in result.output


def test_serve_allows_hosted_mode_on_all_interfaces(monkeypatch):
    captured = {}

    def fake_run(app, host, port, **kw):
        captured.update(host=host, port=port, mode=app.state.app_mode)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = CliRunner().invoke(
        cli.app, ["serve", "--host", "0.0.0.0", "--mode", "hosted"]
    )

    assert result.exit_code == 0
    assert captured == {"host": "0.0.0.0", "port": 8000, "mode": "hosted"}
