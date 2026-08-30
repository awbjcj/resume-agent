from datetime import datetime, timedelta, timezone

from sqlmodel import Session
from sqlalchemy import event

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.db import init_db, make_engine
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.services.role_comparison import compare_roles
from resume_agent.tracking.tables import (
    Application,
    ApplicationEvent,
    CompanyIntelligenceEvidenceRow,
    H1BCompanyEvidence,
    Job,
)


def test_comparison_projects_stored_evidence_sponsorship_and_latest_offer():
    engine = make_engine("sqlite://")
    init_db(engine)
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    with Session(engine) as session:
        acme = Job(source="manual", company="Acme", title="Platform Engineer", fit_score=88)
        globex = Job(source="manual", company="Globex", title="Staff Engineer", fit_score=None)
        session.add(acme)
        session.add(globex)
        session.commit()
        session.refresh(acme)
        session.refresh(globex)
        assert acme.id is not None and globex.id is not None
        acme_application = Application(job_id=acme.id, status="offer")
        globex_application = Application(job_id=globex.id, status="interview")
        session.add(acme_application)
        session.add(globex_application)
        session.commit()
        session.refresh(acme_application)
        assert acme_application.id is not None
        session.add_all(
            [
                ApplicationEvent(
                    application_id=acme_application.id,
                    kind="offer_received",
                    occurred_at=now - timedelta(days=2),
                    comp_base=180_000,
                    comp_bonus=20_000,
                    comp_currency="USD",
                ),
                ApplicationEvent(
                    application_id=acme_application.id,
                    kind="offer_received",
                    occurred_at=now - timedelta(days=1),
                    comp_base=190_000,
                    comp_bonus=25_000,
                    comp_currency="USD",
                ),
            ]
        )
        evidence = CompanyIntelligenceEvidence(
            normalized_company="acme",
            display_company="Acme",
            overview="Grounded overview",
            insights=[
                CompanyIntelligenceInsight(
                    axis="strategy",
                    summary="Supported strategy",
                    citations=["https://acme.example/strategy"],
                    verification_state="corroborated",
                )
            ],
            sources=[CompanyIntelligenceSource(url="https://acme.example/strategy")],
            retrieved_at=now - timedelta(days=40),
            expires_at=now - timedelta(days=10),
            caveat="Verify",
            research_depth="deep",
        )
        session.add(
            CompanyIntelligenceEvidenceRow(
                normalized_company="acme",
                display_company="Acme",
                evidence_json=evidence.model_dump(mode="json"),
                retrieved_at=evidence.retrieved_at,
                expires_at=evidence.expires_at,
            )
        )
        h1b = H1BSponsorshipEvidence(
            status="matched",
            normalized_company="acme",
            retrieved_at=now,
            expires_at=now + timedelta(days=30),
            confidence=0.9,
            caveat=HISTORICAL_ONLY_CAVEAT,
        )
        session.add(
            H1BCompanyEvidence(
                normalized_company="acme",
                status="matched",
                evidence_json=h1b.model_dump(mode="json"),
                retrieved_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        session.commit()

        items = compare_roles(session, [globex.id, acme.id], now=now)

    assert [item.job_id for item in items] == [globex.id, acme.id]
    assert items[0].company_evidence.state == "not_researched"
    assert items[0].fit_score is None
    assert items[1].company_evidence.research_depth == "deep"
    assert items[1].company_evidence.strongest_verification == "corroborated"
    assert items[1].company_evidence.is_stale is True
    assert items[1].h1b_status == "matched"
    assert items[1].offer_total == 215_000
    assert items[1].offer_currency == "USD"


def test_comparison_reads_only_selected_roles_with_a_bounded_query_count():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        jobs = [
            Job(source="manual", company=f"Company {index}", title="Engineer")
            for index in range(50)
        ]
        session.add_all(jobs)
        session.commit()
        for job in jobs:
            session.refresh(job)
            assert job.id is not None
            session.add(Application(job_id=job.id, status="interview"))
        session.commit()
        requested = [jobs[41].id, jobs[7].id]
        assert all(job_id is not None for job_id in requested)
        statements = 0

        def count_statement(*_args):
            nonlocal statements
            statements += 1

        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            items = compare_roles(session, [int(value) for value in requested])
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)

    assert [item.job_id for item in items] == requested
    assert statements == 4
