from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SystemSession
from sqlmodel import Session

from resume_tailor_harness.api.auth import hash_password
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tenancy.system_db import User
from resume_tailor_harness.tenancy.workspace import provision_workspace
from resume_tailor_harness.tracking.tables import CoverLetter, Job, ResumeVersion


def _provision_user(app, *, username: str = "alice") -> tuple[str, Engine]:
    user_id = f"{username:0<12}"[:12]
    with SystemSession(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_hash=hash_password("alice-password", iterations=1000),
                role="user",
            )
        )
        session.commit()
    paths = provision_workspace(
        app.state.data_dir,
        user_id,
        template_dir=app.state.template_config_dir,
    )
    engine = make_engine(paths.db_url)
    init_db(engine)
    return user_id, engine


def _seed_external_artifacts(engine, external_pdf: Path) -> tuple[int, int]:
    with Session(engine) as session:
        job = Job(source="manual", jd_text="security boundary")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        version = ResumeVersion(job_id=job.id, pdf_path=str(external_pdf))
        cover = CoverLetter(job_id=job.id, pdf_path=str(external_pdf))
        session.add(version)
        session.add(cover)
        session.commit()
        session.refresh(version)
        session.refresh(cover)
        assert version.id is not None
        assert cover.id is not None
        return version.id, cover.id


def test_multi_user_downloads_reject_artifacts_outside_workspace(
    mu_app, mu_client, tmp_path
):
    _user_id, engine = _provision_user(mu_app)
    external_pdf = tmp_path / "outside.pdf"
    external_pdf.write_bytes(b"sensitive host data")
    version_id, cover_id = _seed_external_artifacts(engine, external_pdf)
    engine.dispose()
    assert (
        mu_client.post(
            "/api/auth/login",
            json={"identifier": "alice", "password": "alice-password"},
        ).status_code
        == 200
    )

    responses = [
        mu_client.get(f"/api/resume-versions/{version_id}/pdf"),
        mu_client.get(f"/api/cover-letters/{cover_id}/pdf"),
        mu_client.get(f"/api/resume-versions/{version_id}/preview"),
        mu_client.get(f"/api/cover-letters/{cover_id}/preview"),
    ]

    for response in responses:
        assert response.status_code == 404
        assert b"sensitive host data" not in response.content


def test_workspace_import_rejects_external_artifact_paths(mu_app, mu_client, tmp_path):
    _user_id, engine = _provision_user(mu_app)
    external_pdf = tmp_path / "outside.pdf"
    external_pdf.write_bytes(b"sensitive host data")
    _seed_external_artifacts(engine, external_pdf)
    engine.dispose()
    assert (
        mu_client.post(
            "/api/auth/login",
            json={"identifier": "alice", "password": "alice-password"},
        ).status_code
        == 200
    )
    exported = mu_client.get("/api/account/export")
    assert exported.status_code == 200

    imported = mu_client.post(
        "/api/account/import?confirm=REPLACE",
        files={
            "file": (
                "workspace.tar.gz",
                exported.content,
                "application/gzip",
            )
        },
    )

    assert imported.status_code == 400
    assert imported.json()["error"]["code"] == "INVALID_ARCHIVE"
