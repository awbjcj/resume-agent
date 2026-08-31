def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"identifier": "owner", "password": "owner-password"},
    )
    assert response.status_code == 200


def test_pat_mint_list_use_and_revoke(mu_client):
    _login(mu_client)
    minted = mu_client.post("/api/account/tokens", json={"name": "automation"})
    assert minted.status_code == 201
    body = minted.json()
    assert body["token"].startswith("rat_")
    listed = mu_client.get("/api/account/tokens").json()["tokens"]
    assert listed[0]["name"] == "automation"
    assert "token" not in listed[0]
    mu_client.cookies.clear()
    assert (
        mu_client.get(
            "/api/pipeline", headers={"Authorization": f"Bearer {body['token']}"}
        ).status_code
        == 200
    )
    _login(mu_client)
    assert mu_client.delete(f"/api/account/tokens/{body['id']}").status_code == 204
    mu_client.cookies.clear()
    assert (
        mu_client.get(
            "/api/pipeline", headers={"Authorization": f"Bearer {body['token']}"}
        ).status_code
        == 401
    )


def test_link_token_is_not_general_query_auth(mu_client):
    _login(mu_client)
    minted = mu_client.post("/api/auth/link-token", json={"purpose": "sse"})
    assert minted.status_code == 200
    token = minted.json()["token"]
    mu_client.cookies.clear()
    assert mu_client.get(f"/api/pipeline?token={token}").status_code == 401


def test_sse_accepts_only_the_owner_purpose_bound_link(mu_app, mu_client):
    _login(mu_client)
    owner_id = mu_app.state.default_context.user_id
    run_id = mu_app.state.run_manager.submit(
        "test", lambda _reporter: {}, user_id=owner_id
    )
    assert mu_app.state.run_manager.get(run_id).user_id == owner_id
    token = mu_client.post("/api/auth/link-token", json={"purpose": "sse"}).json()[
        "token"
    ]
    assert mu_app.state.run_manager.get(run_id).user_id == owner_id
    mu_client.cookies.clear()

    response = mu_client.get(f"/api/runs/{run_id}/events?token={token}")
    assert response.status_code == 200, response.text
    assert '"state": "done"' in response.text

    wrong_purpose = mu_app.state.settings
    from resume_tailor_harness.api.auth import issue_link_token

    download_token = issue_link_token(
        wrong_purpose, user_id=owner_id, purpose="download"
    )
    assert (
        mu_client.get(f"/api/runs/{run_id}/events?token={download_token}").status_code
        == 401
    )


def test_download_link_is_purpose_bound(mu_client):
    _login(mu_client)
    download = mu_client.post(
        "/api/auth/link-token", json={"purpose": "download"}
    ).json()["token"]
    sse = mu_client.post("/api/auth/link-token", json={"purpose": "sse"}).json()[
        "token"
    ]
    mu_client.cookies.clear()

    assert mu_client.get(f"/api/account/export?token={download}").status_code == 200
    assert mu_client.get(f"/api/account/export?token={sse}").status_code == 401


def test_admin_export_accepts_an_admin_download_link(mu_client):
    _login(mu_client)
    token = mu_client.post("/api/auth/link-token", json={"purpose": "download"}).json()[
        "token"
    ]
    mu_client.cookies.clear()

    response = mu_client.get(f"/api/admin/export?token={token}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
