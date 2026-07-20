from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import CoverLetter, Job


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_cover_letter_pdf_download_404_when_no_file(tmp_path):
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            cl = CoverLetter(job_id=job.id, pdf_path=str(tmp_path / "missing.pdf"))
            s.add(cl)
            s.commit()
            s.refresh(cl)
            clid = cl.id
        resp = client.get(f"/api/cover-letters/{clid}/pdf")
    assert resp.status_code == 404


def test_cover_letter_pdf_download_uses_friendly_filename(tmp_path):
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
            cl = CoverLetter(job_id=job.id, pdf_path=str(pdf))
            s.add(cl)
            s.commit()
            s.refresh(cl)
            clid = cl.id
        resp = client.get(f"/api/cover-letters/{clid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 test"
    assert (
        f'filename="Acme_Corp-Senior_Engineer-CoverLetter-v{clid}.pdf"'
        in resp.headers["content-disposition"]
    )
