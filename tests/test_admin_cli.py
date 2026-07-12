import httpx

from resume_agent import admin_cli


def test_admin_cli_login_persists_pat_and_reuses_it(tmp_path, monkeypatch, capsys):
    credentials = tmp_path / "credentials.json"
    monkeypatch.setattr(admin_cli, "CREDENTIALS_PATH", credentials)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(
                200,
                json={"username": "owner", "role": "admin"},
                headers={"set-cookie": "session=ok; Path=/"},
            )
        if request.url.path == "/api/account/tokens":
            assert "session=ok" in request.headers.get("cookie", "")
            return httpx.Response(
                201, json={"id": "t1", "name": "cli", "token": "rat_secret"}
            )
        if request.url.path == "/api/admin/invites":
            assert request.headers["authorization"] == "Bearer rat_secret"
            return httpx.Response(
                201, json={"id": "i1", "code": "inv_once", "expiresAt": "soon"}
            )
        raise AssertionError(request.url)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        admin_cli,
        "_make_client",
        lambda base_url: httpx.Client(base_url=base_url, transport=transport),
    )

    admin_cli.do_login("https://example.test", "owner", "owner-password")
    assert admin_cli.load_credentials() == {
        "apiUrl": "https://example.test",
        "username": "owner",
        "token": "rat_secret",
    }
    admin_cli.do_invite(7)
    assert "inv_once" in capsys.readouterr().out
