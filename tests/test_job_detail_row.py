from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.queries import job_detail_row
from resume_tailor_harness.tracking.repository import save_application
from resume_tailor_harness.tracking.tables import Application, Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_job_detail_row_assembles_facets_and_subresources():
    with _session() as session:
        job = Job(
            source="greenhouse",
            url="http://x",
            company="Acme",
            title="SWE",
            location="Remote",
            jd_text="build things",
            status=JobStatus.tailored.value,
            fit_score=88,
            fit_rationale="great",
            criteria_json={"remote_policy": "remote", "seniority": "senior"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        save_application(session, Application(job_id=job.id, status="applied"))

        row = job_detail_row(session, job.id)

    assert row is not None
    assert row.id == job.id
    assert row.source == "greenhouse"
    assert row.jd_text == "build things"
    assert row.status == JobStatus.tailored.value
    assert row.remote_policy == "remote"
    assert row.seniority == "senior"
    assert row.has_progress is True
    assert row.application is not None and row.application.status == "applied"
    assert isinstance(row.resume_versions, list)
    assert isinstance(row.skills, list)


def test_job_detail_row_returns_none_for_missing_job():
    with _session() as session:
        assert job_detail_row(session, 9999) is None
