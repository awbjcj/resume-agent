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
