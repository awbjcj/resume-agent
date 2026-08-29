"""HTTP surface for deleting resume versions and cover letters."""

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    JobStatus,
    ResumeVersion,
)


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _seed(app, *, versions=1, cover_letters=0, applied_version=False):
    """Seed one tailored job and return (job_id, version_ids, cover_letter_ids)."""
    with get_session(app.state.engine) as s:
        job = Job(source="manual", jd_text="x", status=JobStatus.tailored.value)
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.id is not None
        job_id = job.id
        version_ids = []
        for round_no in range(versions):
            version = ResumeVersion(job_id=job_id, round=round_no)
            s.add(version)
            s.commit()
            s.refresh(version)
            version_ids.append(version.id)
        letter_ids = []
        for _ in range(cover_letters):
            letter = CoverLetter(job_id=job_id)
            s.add(letter)
            s.commit()
            s.refresh(letter)
            letter_ids.append(letter.id)
        if applied_version:
            s.add(Application(job_id=job_id, resume_version_id=version_ids[0]))
            s.commit()
        return job_id, version_ids, letter_ids


def test_delete_resume_version_returns_204_and_removes_it():
    client = _client()
    with client:
        job_id, versions, _ = _seed(client.app, versions=2)

        assert client.delete(f"/api/resume-versions/{versions[0]}").status_code == 204

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert [v["id"] for v in detail["resumeVersions"]] == [versions[1]]


def test_delete_cover_letter_returns_204_and_removes_it():
    client = _client()
    with client:
        job_id, _, letters = _seed(client.app, cover_letters=2)

        assert client.delete(f"/api/cover-letters/{letters[0]}").status_code == 204

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert [c["id"] for c in detail["coverLetters"]] == [letters[1]]


def test_deleting_the_applied_version_is_409():
    client = _client()
    with client:
        _, versions, _ = _seed(client.app, versions=1, applied_version=True)

        response = client.delete(f"/api/resume-versions/{versions[0]}")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ARTIFACT_IN_USE"


def test_deleting_an_unknown_version_is_404():
    client = _client()
    with client:
        _seed(client.app)

        response = client.delete("/api/resume-versions/9999")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_bulk_delete_reports_the_count():
    client = _client()
    with client:
        job_id, versions, _ = _seed(client.app, versions=3)

        response = client.post(
            "/api/resume-versions/bulk-delete", json={"ids": versions[:2]}
        )

        assert response.status_code == 200
        assert response.json() == {"deleted": 2}
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert [v["id"] for v in detail["resumeVersions"]] == [versions[2]]


def test_bulk_delete_including_the_applied_version_deletes_nothing():
    client = _client()
    with client:
        job_id, versions, _ = _seed(client.app, versions=3, applied_version=True)

        response = client.post(
            "/api/resume-versions/bulk-delete", json={"ids": versions}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ARTIFACT_IN_USE"
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert len(detail["resumeVersions"]) == 3


def test_bulk_delete_cover_letters():
    client = _client()
    with client:
        job_id, _, letters = _seed(client.app, cover_letters=2)

        response = client.post("/api/cover-letters/bulk-delete", json={"ids": letters})

        assert response.status_code == 200
        assert response.json() == {"deleted": 2}
        assert client.get(f"/api/jobs/{job_id}").json()["coverLetters"] == []


def test_bulk_delete_rejects_an_empty_id_list():
    client = _client()
    with client:
        _seed(client.app)

        assert (
            client.post(
                "/api/resume-versions/bulk-delete", json={"ids": []}
            ).status_code
            == 422
        )


def test_deselect_then_delete_the_previously_applied_version():
    client = _client()
    with client:
        job_id, versions, _ = _seed(client.app, versions=1, applied_version=True)

        deselected = client.delete(f"/api/jobs/{job_id}/select-resume")
        assert deselected.status_code == 200
        assert deselected.json()["resumeVersionId"] is None

        assert client.delete(f"/api/resume-versions/{versions[0]}").status_code == 204


def test_deselect_cover_letter_leaves_the_resume_selection_intact():
    client = _client()
    with client:
        job_id, versions, letters = _seed(client.app, versions=1, cover_letters=1)
        client.post(f"/api/jobs/{job_id}/select-resume/{versions[0]}")
        client.post(f"/api/jobs/{job_id}/select-cover-letter/{letters[0]}")

        response = client.delete(f"/api/jobs/{job_id}/select-cover-letter")

        assert response.status_code == 200
        assert response.json()["coverLetterId"] is None
        assert response.json()["resumeVersionId"] == versions[0]


def test_deselect_with_no_application_is_404():
    client = _client()
    with client:
        job_id, _, _ = _seed(client.app)

        response = client.delete(f"/api/jobs/{job_id}/select-resume")

        assert response.status_code == 404
