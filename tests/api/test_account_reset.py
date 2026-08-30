from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlmodel import Session as WorkspaceSession
from sqlmodel import select

from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password
from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import provision_workspace, workspace_paths
from resume_agent.tracking.tables import Job


def _login(client, username="owner", password="owner-password"):
    return client.post(
        "/api/auth/login", json={"identifier": username, "password": password}
    )


def _add_user(app, username="alice") -> str:
    user_id = f"{username:0<12}"[:12]
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_hash=hash_password("alice-password"),
                role="user",
            )
        )
        session.commit()
    provision_workspace(
        app.state.data_dir,
        user_id,
        template_dir=app.state.template_config_dir,
    )
    return user_id


def _seed_workspace(app, user_id):
    paths = workspace_paths(app.state.data_dir, user_id)
    engine = make_engine(paths.db_url)
    init_db(engine)
    with WorkspaceSession(engine) as session:
        session.add(
            Job(source="manual", company="Acme", title="Engineer", dedup_key="a|e")
        )
        session.commit()
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    (paths.output_dir / "resume.pdf").write_bytes(b"%PDF")
    paths.secrets_env.write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    return paths, engine


def test_reset_requires_confirmation(mu_app, mu_client):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post("/api/account/reset", json={"scope": "jobs"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_reset_rejects_unknown_scope(mu_app, mu_client):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "unknown"}
    )

    assert response.status_code == 422


def test_reset_refuses_while_user_has_active_runs(mu_app, mu_client, monkeypatch):
    _add_user(mu_app)
    assert _login(mu_client, "alice", "alice-password").status_code == 200
    monkeypatch.setattr(
        mu_app.state.run_manager,
        "list_active",
        lambda user_id=None: ["run"],
    )

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "jobs"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUNS_ACTIVE"


def test_reset_jobs_wipes_only_authenticated_workspace(mu_app, mu_client):
    alice_id = _add_user(mu_app, "alice")
    bob_id = _add_user(mu_app, "bob")
    alice_paths, alice_engine = _seed_workspace(mu_app, alice_id)
    bob_paths, bob_engine = _seed_workspace(mu_app, bob_id)
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "jobs"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "scope": "jobs",
        "rowsDeleted": {
            "run_completions": 0,
            "saved_board_views": 0,
            "notifications": 0,
            "applications": 0,
            "cover_letters": 0,
            "resume_versions": 0,
            "skill_suggestions": 0,
            "jobs": 1,
        },
        "areasCleared": ["output", "runs", "progress", "connector_runs"],
        "failures": {},
    }
    assert list(alice_paths.output_dir.iterdir()) == []
    assert alice_paths.secrets_env.exists()
    assert (bob_paths.output_dir / "resume.pdf").exists()
    with WorkspaceSession(alice_engine) as session:
        assert session.exec(select(Job)).first() is None
    with WorkspaceSession(bob_engine) as session:
        assert session.exec(select(Job)).first() is not None


def test_reset_profile_clears_corpus_and_keeps_pipeline(mu_app, mu_client):
    user_id = _add_user(mu_app)
    paths, engine = _seed_workspace(mu_app, user_id)
    facts = paths.profile_dir / "facts.json"
    facts.parent.mkdir(parents=True, exist_ok=True)
    facts.write_text("{}", encoding="utf-8")
    sources = paths.profile_dir / "sources.json"
    sources.write_text('{"documents": [{"id": "resume"}]}', encoding="utf-8")
    source_document = paths.profile_dir / "documents" / "resume.md"
    source_document.parent.mkdir(parents=True, exist_ok=True)
    source_document.write_text("source resume", encoding="utf-8")
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post(
        "/api/account/reset?confirm=RESET", json={"scope": "profile"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["areasCleared"] == ["profile", "taxonomy"]
    assert not facts.exists()
    assert sources.read_text(encoding="utf-8") == '{"documents": [{"id": "resume"}]}'
    assert source_document.read_text(encoding="utf-8") == "source resume"
    assert (paths.profile_dir / "documents").is_dir()
    assert (paths.output_dir / "resume.pdf").exists()
    with WorkspaceSession(engine) as session:
        assert session.exec(select(Job)).first() is not None


def test_single_user_reset_uses_configured_app_paths(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "custom-data"
    runs_dir = tmp_path / "custom-runs"
    output_dir = tmp_path / "output"
    app = create_app(db_url="sqlite://", data_dir=data_dir, runs_root=runs_dir)

    with TestClient(app) as client:
        with WorkspaceSession(app.state.engine) as session:
            session.add(Job(source="manual", title="Engineer"))
            session.commit()
        for directory in (runs_dir, data_dir / "progress", output_dir):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "stale.json").write_text("{}", encoding="utf-8")
        decoy = tmp_path / "data" / "progress"
        decoy.mkdir(parents=True)
        (decoy / "keep.json").write_text("{}", encoding="utf-8")

        response = client.post(
            "/api/account/reset?confirm=RESET", json={"scope": "jobs"}
        )

        assert response.status_code == 200, response.text
        assert list(runs_dir.iterdir()) == []
        assert list((data_dir / "progress").iterdir()) == []
        assert list(output_dir.iterdir()) == []
        assert (decoy / "keep.json").exists()


def test_reset_all_preserves_sources_until_explicit_source_reset(mu_app, mu_client):
    user_id = _add_user(mu_app)
    paths, _engine = _seed_workspace(mu_app, user_id)
    sources = paths.profile_dir / "sources.json"
    sources.parent.mkdir(parents=True, exist_ok=True)
    sources.write_text('{"documents": [{"id": "resume"}]}', encoding="utf-8")
    source_document = paths.profile_dir / "documents" / "resume.md"
    source_document.parent.mkdir(parents=True, exist_ok=True)
    source_document.write_text("source resume", encoding="utf-8")
    assert _login(mu_client, "alice", "alice-password").status_code == 200

    response = mu_client.post("/api/account/reset?confirm=RESET", json={"scope": "all"})

    assert response.status_code == 200, response.text
    assert sources.read_text(encoding="utf-8") == '{"documents": [{"id": "resume"}]}'
    assert source_document.read_text(encoding="utf-8") == "source resume"
