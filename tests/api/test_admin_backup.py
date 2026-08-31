import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.tracking.tables import Job


def _app(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "profile").mkdir()
    (data_root / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    db_url = f"sqlite:///{(data_root / 'resume_tailor_harness.db').as_posix()}"
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('owner-password')}\n"
        "SESSION_SECRET=test-secret\n",
        encoding="utf-8",
    )
    return (
        create_app(
            db_url=db_url,
            app_mode="hosted",
            data_dir=data_root,
            env_path=env,
        ),
        data_root,
    )


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"identifier": "owner", "password": "owner-password"},
    )
    assert response.status_code == 200


def _add_job(app, title):
    with Session(app.state.engine) as session:
        session.add(
            Job(
                source="manual",
                company="Acme",
                title=title,
                url=f"https://example.test/{title}",
                jd_text="description",
            )
        )
        session.commit()


def test_export_then_import_restores_database(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        _add_job(app, "Engineer")
        exported = client.get("/api/admin/export")
        assert exported.status_code == 200
        _add_job(app, "Mutation")
        response = client.post(
            "/api/admin/import?confirm=REPLACE",
            files={"file": ("backup.tar.gz", io.BytesIO(exported.content))},
        )
        assert response.status_code == 200
        with Session(app.state.engine) as session:
            assert session.exec(select(Job.title)).all() == ["Engineer"]


def test_import_safety_gates_and_engine_survives_bad_archive(tmp_path, monkeypatch):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        assert (
            client.post(
                "/api/admin/import",
                files={"file": ("bad.tar.gz", io.BytesIO(b"bad"))},
            ).json()["error"]["code"]
            == "CONFIRM_REQUIRED"
        )
        monkeypatch.setattr(app.state.run_manager, "list_active", lambda: [object()])
        assert client.get("/api/admin/export").status_code == 409
        monkeypatch.setattr(app.state.run_manager, "list_active", lambda: [])
        response = client.post(
            "/api/admin/import?confirm=REPLACE",
            files={"file": ("bad.tar.gz", io.BytesIO(b"not a tar"))},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_ARCHIVE"
        with Session(app.state.engine) as session:
            session.exec(select(Job)).all()


def test_admin_routes_are_guarded(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('owner-password')}\n"
        "SESSION_SECRET=test-secret\n",
        encoding="utf-8",
    )
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'resume_tailor_harness.db').as_posix()}",
        app_mode="hosted",
        data_dir=data_root,
        api_token="secret",
        env_path=env,
    )
    with TestClient(app) as client:
        assert client.get("/api/admin/export").status_code == 401


def test_export_cleans_temporary_directory_when_build_fails(tmp_path, monkeypatch):
    from resume_tailor_harness.api.routers import admin

    app, _ = _app(tmp_path)
    temporary = tmp_path / "failed-export"
    temporary.mkdir()
    monkeypatch.setattr(admin.tempfile, "mkdtemp", lambda **_: str(temporary))
    monkeypatch.setattr(
        admin,
        "export_data_root",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("export failed")),
    )

    with TestClient(app) as client, pytest.raises(RuntimeError, match="export failed"):
        _login(client)
        client.get("/api/admin/export")

    assert not temporary.exists()
