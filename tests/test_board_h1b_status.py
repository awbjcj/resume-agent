from datetime import datetime, timedelta, timezone

from sqlalchemy import event
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.services.board import list_board
from resume_agent.tracking.tables import H1BCompanyEvidence, Job, JobStatus


def _seed_evidence(session: Session, company: str) -> None:
    now = datetime.now(timezone.utc)
    evidence = H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        retrieved_at=now,
        expires_at=now + timedelta(days=30),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )
    session.add(
        H1BCompanyEvidence(
            normalized_company=company,
            status="matched",
            evidence_json=evidence.model_dump(mode="json"),
            expires_at=now + timedelta(days=30),
            retrieved_at=now,
        )
    )


def test_production_shortlist_page_resolves_h1b_status_in_one_query():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for index in range(6):
            session.add(
                Job(
                    source="manual",
                    company="Acme, Inc." if index % 2 == 0 else "Globex LLC",
                    title=f"Role {index}",
                    jd_text="x",
                    status=JobStatus.shortlisted.value,
                )
            )
        _seed_evidence(session, "acme")
        _seed_evidence(session, "globex")
        session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            rows = list_board(
                session, "shortlist", with_facets=False
            ).page.data
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(rows) == 6
    assert all(row.h1b_sponsorship_status == "matched" for row in rows)
    assert len(statements) == 1, "board rows must not issue one H-1B query per row"


def test_production_pipeline_page_resolves_h1b_status_in_one_query():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for index in range(6):
            session.add(
                Job(
                    source="manual",
                    company="Acme, Inc." if index % 2 == 0 else "Globex LLC",
                    title=f"Role {index}",
                    jd_text="x",
                    status=JobStatus.tailored.value,
                )
            )
        _seed_evidence(session, "acme")
        _seed_evidence(session, "globex")
        session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            rows = list_board(
                session, "pipeline", with_facets=False
            ).page.data
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(rows) == 6
    assert all(row.h1b_sponsorship_status == "matched" for row in rows)
    assert len(statements) == 1, "board rows must not issue one H-1B query per row"


def test_production_triage_page_resolves_h1b_status_in_one_query():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for index in range(6):
            session.add(
                Job(
                    source="manual",
                    company="Acme, Inc." if index % 2 == 0 else "Globex LLC",
                    title=f"Role {index}",
                    jd_text="x",
                    status=JobStatus.filtered.value,
                )
            )
        _seed_evidence(session, "acme")
        _seed_evidence(session, "globex")
        session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            rows = list_board(
                session, "triage", with_facets=False
            ).page.data
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(rows) == 6
    assert all(row.h1b_sponsorship_status == "matched" for row in rows)
    assert len(statements) == 1, "board rows must not issue one H-1B query per row"
