from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import resumes
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_prune_dry_run_reports_counts():
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            s.add(Job(source="manual", jd_text="x", status=JobStatus.rejected.value))
            s.commit()
        body = client.post("/api/prune", json={"dryRun": True}).json()
    assert body["rejected"] >= 1
    assert "archived" in body


def test_render_endpoint_invokes_service(monkeypatch, tmp_path):
    client = _client()
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def fake_render(session, version_id, *, render_path="config/render.yaml"):
        from resume_agent.tracking.repository import get_resume_version
        v = get_resume_version(session, version_id)
        assert v is not None
        v.pdf_path = str(pdf)
        session.add(v)
        session.commit()
        return pdf

    monkeypatch.setattr(resumes, "render_resume_version", fake_render)
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            v = ResumeVersion(job_id=job.id, round=0)
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        body = client.post(f"/api/resume-versions/{vid}/render").json()
    assert body["pdfPath"].endswith("r.pdf")
