import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.services import redo
from resume_agent.services.errors import StageFailure, list_error_records
from resume_agent.tailor.service import TailorOutcome
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    monkeypatch.setattr(redo, "enforce_active_budget", lambda: None)


def _rendered_job(session) -> Job:
    return save_job(
        session,
        Job(source="manual", jd_text="jd", company="Acme", title="Staff",
            status=JobStatus.rendered.value),
    )


def test_stages_run_in_pipeline_order_whatever_order_was_asked(session, monkeypatch):
    job = _rendered_job(session)
    seen: list[str] = []
    monkeypatch.setattr(
        redo, "_run_pull",
        lambda *a, **k: (seen.append("pull") or [])
    )
    monkeypatch.setattr(
        redo, "_run_extract",
        lambda *a, **k: (seen.append("extract") or [])
    )
    monkeypatch.setattr(
        redo, "_run_tailor",
        lambda *a, **k: (seen.append("tailor") or [])
    )

    redo.redo_jobs(
        session, job_ids=[job.id], stages=["tailor", "extract", "pull"]
    )

    assert seen == ["pull", "extract", "tailor"]


def test_tailor_failure_is_recorded_as_a_job_error(session, monkeypatch):
    job = _rendered_job(session)
    failure = StageFailure(
        error_type="ValueError", message="no match-plan agent", traceback_tail="tb"
    )
    monkeypatch.setattr(
        redo,
        "tailor",
        lambda *a, **k: TailorOutcome(versions={}, failures={job.id: failure}),
    )

    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])

    assert [o.status for o in outcomes] == ["failed"]
    records = list_error_records(session, "open")
    assert len(records) == 1
    assert records[0].kind == "job"
    assert records[0].source_label == f"job:{job.id}:tailor"


def test_tailor_success_resolves_an_earlier_failure(session, monkeypatch):
    job = _rendered_job(session)
    failure = StageFailure(error_type="ValueError", message="boom", traceback_tail="")
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={}, failures={job.id: failure}),
    )
    redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])
    assert len(list_error_records(session, "open")) == 1

    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )
    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["tailor"])

    assert [o.status for o in outcomes] == ["ok"]
    assert list_error_records(session, "open") == []


def test_missing_job_is_skipped_not_fatal(session, monkeypatch):
    job = _rendered_job(session)
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )

    outcomes = redo.redo_jobs(session, job_ids=[job.id, 9999], stages=["tailor"])

    statuses = {o.job_id: o.status for o in outcomes}
    assert statuses[job.id] == "ok"
    assert statuses[9999] == "skipped"


def test_render_skips_a_job_with_no_versions(session):
    job = _rendered_job(session)

    outcomes = redo.redo_jobs(session, job_ids=[job.id], stages=["render"])

    assert outcomes[0].status == "skipped"
    assert outcomes[0].detail == "no resume version"


def test_redo_never_regresses_a_rendered_job(session, monkeypatch):
    job = _rendered_job(session)
    monkeypatch.setattr(
        redo, "tailor",
        lambda *a, **k: TailorOutcome(versions={job.id: []}, failures={}),
    )
    monkeypatch.setattr(redo, "_run_extract", lambda *a, **k: [])

    redo.redo_jobs(session, job_ids=[job.id], stages=["extract", "tailor"])

    session.refresh(job)
    assert job.status == JobStatus.rendered.value
