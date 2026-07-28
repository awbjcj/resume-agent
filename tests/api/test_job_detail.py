from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.repository import save_application
from resume_agent.tracking.tables import Application, Job, JobStatus, ResumeVersion


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_job_detail_includes_versions_and_application():
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(
                source="manual",
                jd_text="hello",
                status=JobStatus.tailored.value,
                criteria_json={"remote_policy": "remote"},
            )
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            s.add(ResumeVersion(job_id=job.id, round=0, review_score=88))
            save_application(s, Application(job_id=job.id, status="submitted", notes="ref"))
            s.commit()
            jid = job.id
        body = client.get(f"/api/jobs/{jid}").json()
    assert body["id"] == jid
    assert body["jdText"] == "hello"
    assert body["remotePolicy"] == "remote"
    assert body["hasProgress"] is True
    assert body["application"]["status"] == "submitted"
    assert body["application"]["notes"] == "ref"
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
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
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
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(pdf))
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 test"


def test_pdf_download_filename_is_friendly(tmp_path):
    client = _client()
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x", company="Acme Corp", title="Senior Engineer")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(pdf))
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 200
    assert (
        f'filename="Acme_Corp-Senior_Engineer-Resume-v{vid}.pdf"'
        in resp.headers["content-disposition"]
    )


def test_failed_gates_names_the_gate_that_actually_blocked():
    from resume_agent.api.schemas.jobs import ResumeVersionOut

    def _version(critiques, fact_check_passed):
        return ResumeVersionOut.model_validate(
            {
                "id": 1,
                "job_id": 1,
                "round": 1,
                "review_score": None,
                "fact_check_passed": fact_check_passed,
                "pdf_path": None,
                "critique_json": critiques,
                "created_at": "2026-07-27T00:00:00",
            }
        )

    prov = {"reviewer": "provenance", "score": 0, "passed": False}
    fact = {"reviewer": "fact-check", "score": 0, "passed": False}
    ok_fact = {"reviewer": "fact-check", "score": 100, "passed": True}
    advisory = {"reviewer": "ats-keyword", "score": 40, "passed": False}

    # The case the UI got wrong: provenance blocked, fact-check passed, yet the
    # badge read "Fact-check failed".
    assert _version([prov, ok_fact, advisory], False).failed_gates == ["provenance"]
    assert _version([{"reviewer": "provenance", "score": 100, "passed": True}, fact], False).failed_gates == [
        "fact-check"
    ]
    assert _version([prov, fact], False).failed_gates == ["provenance", "fact-check"]
    # A failing advisory reviewer is not a gate.
    assert _version(
        [{"reviewer": "provenance", "score": 100, "passed": True}, ok_fact, advisory], True
    ).failed_gates == []
