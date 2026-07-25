from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.errors import (
    count_open,
    dismiss_all,
    list_error_records,
    record_error,
    record_source_failures,
    set_error_status,
)
from resume_agent.tracking.tables import utcnow


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as database:
        yield database


def test_record_error_deduplicates_open_records(session):
    first = record_error(
        session,
        kind="source",
        source_label="workday:acme",
        message="HTTP 500",
        run_id="r1",
    )
    second = record_error(
        session,
        kind="source",
        source_label="workday:acme",
        message="HTTP 503",
        run_id="r2",
        details={"attempt": 2},
    )

    assert second.id == first.id
    assert second.count == 2
    assert second.message == "HTTP 503"
    assert second.run_id == "r2"
    assert second.details_json == {"attempt": 2}
    assert count_open(session) == 1


def test_terminal_record_does_not_absorb_a_new_failure(session):
    first = record_error(
        session, kind="run", source_label="pull", message="boom"
    )
    assert first.id is not None
    set_error_status(session, first.id, "resolved")

    fresh = record_error(
        session, kind="run", source_label="pull", message="boom again"
    )

    assert fresh.id != first.id
    assert fresh.status == "open"
    assert fresh.count == 1


def test_set_status_validates_identity_state_and_value(session):
    record = record_error(
        session, kind="run", source_label="tailor", message="x"
    )
    assert record.id is not None
    with pytest.raises(ValueError, match="unknown error record"):
        set_error_status(session, record.id + 99, "dismissed")
    with pytest.raises(ValueError, match="invalid status"):
        set_error_status(session, record.id, "closed")
    set_error_status(session, record.id, "dismissed")
    with pytest.raises(ValueError, match="not open"):
        set_error_status(session, record.id, "resolved")


def test_dismiss_all_status_filters_and_pruning(session):
    first = record_error(session, kind="run", source_label="pull", message="a")
    record_error(session, kind="run", source_label="tailor", message="b")
    assert dismiss_all(session) == 2
    assert list_error_records(session, status="open") == []
    assert len(list_error_records(session, status="dismissed")) == 2

    first.updated_at = utcnow() - timedelta(days=31)
    session.add(first)
    session.commit()
    assert len(list_error_records(session, status=None)) == 1


def test_record_source_failures_preserves_run_id(session):
    written = record_source_failures(
        session,
        {
            "companies": {
                "https://a.example": "detect failed",
                "https://b.example": "HTTP 403",
            }
        },
        run_id="run-123",
    )

    assert written == 2
    rows = list_error_records(session)
    assert {row.source_label for row in rows} == {
        "companies:https://a.example",
        "companies:https://b.example",
    }
    assert {row.run_id for row in rows} == {"run-123"}


def test_record_job_failure_stores_formatted_details(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(
        session, Job(source="manual", jd_text="jd", company="Acme", title="Staff")
    )
    try:
        raise ValueError("match_plan_enabled requires a match-plan agent")
    except ValueError as exc:
        failure = StageFailure.from_exception(exc)

    record = record_job_failure(
        session,
        job=job,
        stage="tailor",
        failure=failure,
        run_id="r1",
        model="openai:gpt-5",
    )

    assert record.kind == "job"
    assert record.source_label == f"job:{job.id}:tailor"
    assert record.message.startswith("ValueError: match_plan_enabled")
    details = record.details_json or {}
    assert details["jobId"] == job.id
    assert details["company"] == "Acme"
    assert details["title"] == "Staff"
    assert details["stage"] == "tailor"
    assert details["errorType"] == "ValueError"
    assert details["model"] == "openai:gpt-5"
    assert "ValueError" in details["tracebackTail"]


def test_repeated_job_failure_dedupes_and_counts(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")

    first = record_job_failure(session, job=job, stage="tailor", failure=failure)
    second = record_job_failure(session, job=job, stage="tailor", failure=failure)

    assert second.id == first.id
    assert second.count == 2


def test_different_stages_are_separate_records(session):
    from resume_agent.services.errors import StageFailure, record_job_failure
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")

    tailor = record_job_failure(session, job=job, stage="tailor", failure=failure)
    pull = record_job_failure(session, job=job, stage="pull", failure=failure)

    assert tailor.id != pull.id


def test_success_resolves_open_job_failure(session):
    from resume_agent.services.errors import (
        StageFailure,
        record_job_failure,
        resolve_job_failures,
    )
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    assert job.id is not None
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    record = record_job_failure(session, job=job, stage="tailor", failure=failure)

    resolved = resolve_job_failures(session, job.id, "tailor")

    session.refresh(record)
    assert resolved == 1
    assert record.status == "resolved"


def test_resolve_leaves_other_stages_open(session):
    from resume_agent.services.errors import (
        StageFailure,
        record_job_failure,
        resolve_job_failures,
    )
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    job = save_job(session, Job(source="manual", jd_text="jd"))
    assert job.id is not None
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    pull = record_job_failure(session, job=job, stage="pull", failure=failure)
    record_job_failure(session, job=job, stage="tailor", failure=failure)

    resolve_job_failures(session, job.id, "tailor")

    session.refresh(pull)
    assert pull.status == "open"


def test_stage_failure_truncates_message_and_traceback():
    from resume_agent.services.errors import (
        MAX_MESSAGE_CHARS,
        MAX_TRACEBACK_CHARS,
        StageFailure,
    )

    try:
        raise ValueError("x" * 5000)
    except ValueError as exc:
        failure = StageFailure.from_exception(exc)

    assert len(failure.message) == MAX_MESSAGE_CHARS
    assert len(failure.traceback_tail) <= MAX_TRACEBACK_CHARS
    assert failure.error_type == "ValueError"


def test_concurrent_writers_do_not_duplicate_or_lose_counts(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'errors.db').as_posix()}")
    init_db(engine)

    def write(index: int) -> None:
        with Session(engine) as database:
            record_error(
                database,
                kind="source",
                source_label="companies:https://example.test",
                message=f"failure {index}",
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(8)))

    with Session(engine) as database:
        rows = list_error_records(database)
        assert len(rows) == 1
        assert rows[0].count == 8
