from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_job_detail_includes_versions_and_application():
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="hello", status=JobStatus.tailored.value)
            s.add(job)
            s.commit()
            s.refresh(job)
            s.add(ResumeVersion(job_id=job.id, round=0, review_score=88))
            s.commit()
            jid = job.id
        body = client.get(f"/api/jobs/{jid}").json()
    assert body["id"] == jid
    assert body["jdText"] == "hello"
    assert body["resumeVersions"][0]["reviewScore"] == 88


def test_job_detail_404():
    client = _client()
    with client:
        resp = client.get("/api/jobs/9999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_pdf_download_404_when_no_file(tmp_path):
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(tmp_path / "missing.pdf"))
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 404


def test_pdf_download_streams_file(tmp_path):
    client = _client()
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with client:
        with get_session(client.app.state.engine) as s:
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(pdf))
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 test"
