from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.repository import has_progress, progressed_job_ids
from resume_tailor_harness.tracking.tables import Application, ApplicationEvent, Job


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _setup(**app_kwargs):
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test", company="Acme", title="SWE", status="raw")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=_require_id(job.id), **app_kwargs)
    session.add(app)
    session.commit()
    session.refresh(app)
    return session, job, app


def test_empty_ready_application_is_not_progress():
    session, job, _ = _setup(status="ready")
    assert has_progress(session, _require_id(job.id)) is False
    assert progressed_job_ids(session) == set()


def test_application_with_one_event_is_progress():
    session, job, app = _setup(status="ready")
    session.add(
        ApplicationEvent(
            application_id=_require_id(app.id), kind="recruiter_screen"
        )
    )
    session.commit()
    job_id = _require_id(job.id)
    assert has_progress(session, job_id) is True
    assert progressed_job_ids(session) == {job_id}


def test_non_ready_status_is_progress():
    session, job, _ = _setup(status="submitted")
    job_id = _require_id(job.id)
    assert has_progress(session, job_id) is True
    assert progressed_job_ids(session) == {job_id}


def test_notes_are_progress():
    session, job, _ = _setup(status="ready", notes="applied via referral")
    assert has_progress(session, _require_id(job.id)) is True


def test_blank_notes_are_not_progress():
    session, job, _ = _setup(status="ready", notes="   ")
    assert has_progress(session, _require_id(job.id)) is False


def test_selected_artifact_pointer_is_progress():
    session, job, _ = _setup(status="ready", resume_version_id=1)
    assert has_progress(session, _require_id(job.id)) is True


def test_job_status_check_is_unchanged():
    session, job, _ = _setup(status="ready")
    job.status = "rendered"
    session.add(job)
    session.commit()
    assert has_progress(session, _require_id(job.id)) is True


def test_batched_and_single_predicates_agree_across_a_mixed_set():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    ids: list[int] = []
    for status, add_event in (("ready", False), ("ready", True), ("submitted", False)):
        job = Job(source="test", status="raw")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = _require_id(job.id)
        app = Application(job_id=job_id, status=status)
        session.add(app)
        session.commit()
        session.refresh(app)
        if add_event:
            session.add(
                ApplicationEvent(
                    application_id=_require_id(app.id), kind="behavioral"
                )
            )
            session.commit()
        ids.append(job_id)
    batched = progressed_job_ids(session, ids)
    singles = {i for i in ids if has_progress(session, i)}
    assert batched == singles
    assert batched == {ids[1], ids[2]}
