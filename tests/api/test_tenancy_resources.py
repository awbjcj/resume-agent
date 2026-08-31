from sqlalchemy.orm import Session

from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.tenancy.context import new_user_id
from resume_tailor_harness.tenancy.system_db import User
from resume_tailor_harness.tenancy.workspace import provision_workspace


def _add_user(app, username: str, password: str):
    user = User(
        id=new_user_id(),
        username=username,
        password_hash=hash_password(password, iterations=1000),
        role="user",
    )
    user_id = user.id
    with Session(app.state.system_engine) as session:
        session.add(user)
        session.commit()
    provision_workspace(
        app.state.data_dir,
        user_id,
        template_dir=app.state.template_config_dir,
    )
    return user_id


def _login(client, username: str, password: str):
    client.cookies.clear()
    response = client.post(
        "/api/auth/login", json={"identifier": username, "password": password}
    )
    assert response.status_code == 200


def test_config_secrets_and_documents_are_isolated(mu_app, mu_client):
    _add_user(mu_app, "alice", "alice-password")
    _login(mu_client, "alice", "alice-password")
    assert (
        mu_client.put(
            "/api/config/search", json={"keywords": ["alice-only"]}
        ).status_code
        == 200
    )
    assert (
        mu_client.put(
            "/api/secrets", json={"githubToken": "alice-secret-token"}
        ).status_code
        == 200
    )
    assert (
        mu_client.post(
            "/api/profile/documents",
            files={"file": ("alice.md", b"alice resume", "text/markdown")},
            data={"docType": "resume"},
        ).status_code
        == 201
    )

    _login(mu_client, "owner", "owner-password")
    assert mu_client.get("/api/config/search").json()["keywords"] != ["alice-only"]
    github = next(
        row
        for row in mu_client.get("/api/secrets").json()
        if row["key"] == "githubToken"
    )
    assert github["isSet"] is False
    assert mu_client.get("/api/profile/documents").json() == []

    _login(mu_client, "alice", "alice-password")
    assert mu_client.get("/api/config/search").json()["keywords"] == ["alice-only"]
    assert [
        row["filename"] for row in mu_client.get("/api/profile/documents").json()
    ] == ["alice.md"]


def test_new_user_sources_are_loaded_from_their_workspace(mu_app, mu_client):
    alice_id = _add_user(mu_app, "alice", "alice-password")
    alice_connectors = (
        mu_app.state.data_dir / "users" / alice_id / "config" / "connectors.yaml"
    )
    alice_connectors.write_text(
        "remoteok:\n  enabled: true\n",
        encoding="utf-8",
    )

    _login(mu_client, "alice", "alice-password")

    response = mu_client.get("/api/sources")
    assert response.status_code == 200
    remoteok = next(source for source in response.json() if source["id"] == "remoteok")
    assert remoteok["enabled"] is True
