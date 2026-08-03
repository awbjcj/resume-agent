from datetime import datetime, timedelta, timezone

from sqlalchemy import event
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.h1b.cache import load_company_evidence
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.tracking.tables import H1BCompanyEvidence


def _evidence(company: str, *, expires_in_days: int = 30) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    retrieved_at = (
        now - timedelta(days=-expires_in_days + 1)
        if expires_in_days < 0
        else now
    )
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        display_company=company.title(),
        filing_count=3,
        retrieved_at=retrieved_at,
        expires_at=now + timedelta(days=expires_in_days),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


def _seed(session: Session, company: str, **kwargs) -> None:
    evidence = _evidence(company, **kwargs)
    session.add(
        H1BCompanyEvidence(
            normalized_company=company,
            display_company=evidence.display_company,
            status=evidence.status,
            evidence_json=evidence.model_dump(mode="json"),
            expires_at=evidence.expires_at,
            retrieved_at=evidence.retrieved_at,
        )
    )
    session.commit()


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_loads_many_companies_in_one_query():
    engine = _engine()
    with Session(engine) as session:
        for name in ("acme", "globex", "initech"):
            _seed(session, name)

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "h1b_company_evidence" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            loaded = load_company_evidence(
                session, ["Acme, Inc.", "Globex LLC", "Initech"]
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert set(loaded) == {"acme", "globex", "initech"}
    assert len(statements) == 1


def test_expired_rows_are_returned_not_filtered():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "acme", expires_in_days=-5)
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc."])
    assert loaded["acme"].status == "matched"


def test_schema_version_one_row_deserializes_with_empty_periods():
    engine = _engine()
    with Session(engine) as session:
        # `_seed` uses H1BCompanyEvidence.schema_version's persisted default: 1.
        _seed(session, "acme")
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc."])
    assert loaded["acme"].periods == []


def test_corrupt_row_is_skipped_not_raised():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "acme")
        session.add(
            H1BCompanyEvidence(
                normalized_company="globex",
                status="matched",
                evidence_json={"nonsense": True},
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.commit()
    with Session(engine) as session:
        loaded = load_company_evidence(session, ["Acme, Inc.", "Globex LLC"])
    assert set(loaded) == {"acme"}


def test_blank_companies_return_empty_without_querying():
    engine = _engine()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            assert load_company_evidence(session, [None, "", "   "]) == {}
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements == []
