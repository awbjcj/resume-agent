import io

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from resume_agent.api.app import create_app
from resume_agent.tracking.tables import Job


def _app(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "profile").mkdir()
    (data_root / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    db_url = f"sqlite:///{(data_root / 'resume_agent.db').as_posix()}"
    return create_app(db_url=db_url, data_dir=data_root), data_root


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
    app = create_app(
        db_url=f"sqlite:///{(data_root / 'resume_agent.db').as_posix()}",
        data_dir=data_root,
        api_token="secret",
    )
    with TestClient(app) as client:
        assert client.get("/api/admin/export").status_code == 401
