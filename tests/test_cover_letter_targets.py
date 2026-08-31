from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services.cover_letters import resolve_cover_letter_targets
from resume_tailor_harness.services.tailoring import resolve_targets
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _seed_jobs(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    init_db(engine)
    with get_session(engine) as session:
        for status in JobStatus:
            session.add(Job(source="manual", jd_text=status.value, status=status.value))
        session.commit()
    return engine


def test_cover_letter_bulk_targets_include_every_post_approval_stage(tmp_path):
    engine = _seed_jobs(tmp_path)

    with get_session(engine) as session:
        targets = resolve_cover_letter_targets(session, job_ids=None, approved=True)

    assert {job.status for job in targets} == {
        JobStatus.approved.value,
        JobStatus.tailored.value,
        JobStatus.rendered.value,
    }


def test_tailor_bulk_targets_remain_limited_to_approved_jobs(tmp_path):
    engine = _seed_jobs(tmp_path)

    with get_session(engine) as session:
        targets = resolve_targets(session, job_ids=None, approved=True)

    assert [job.status for job in targets] == [JobStatus.approved.value]
