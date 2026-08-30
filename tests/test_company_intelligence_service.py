from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceDraft,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.services.company_intelligence import (
    generate_company_intelligence,
    load_company_intelligence,
)
from resume_agent.tracking.tables import CompanyIntelligenceEvidenceRow


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return _Result(self.content)


def _draft() -> CompanyIntelligenceDraft:
    return CompanyIntelligenceDraft(
        overview="Acme builds infrastructure software.",
        sources=[
            CompanyIntelligenceSource(
                title="Acme strategy",
                url="https://acme.example/strategy",
                publisher="Acme",
                source_type="official",
            ),
            CompanyIntelligenceSource(
                title="Invented source",
                url="https://invented.example/report",
                publisher="Invented",
            ),
        ],
        insights=[
            CompanyIntelligenceInsight(
                axis="strategy",
                summary="Acme is investing in platform tooling.",
                why_it_matters="Candidates can ask how teams support that investment.",
                citations=["https://acme.example/strategy"],
            ),
            CompanyIntelligenceInsight(
                axis="challenges",
                summary="This is not grounded.",
                citations=["https://invented.example/report"],
            ),
        ],
    )


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_generation_keeps_only_sources_and_claims_grounded_in_research():
    engine = _engine()
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    with Session(engine) as session:
        row = generate_company_intelligence(
            session,
            company="Acme, Inc.",
            settings=Settings(company_intelligence_ttl_days=30),
            research_agent=_Agent("Evidence https://acme.example/strategy"),
            formatter=_Agent(_draft()),
            now=now,
        )
        evidence = load_company_intelligence(session, "Acme LLC")

    assert row.normalized_company == "acme"
    assert evidence is not None
    assert [source.url for source in evidence.sources] == [
        "https://acme.example/strategy"
    ]
    assert [insight.axis for insight in evidence.insights] == ["strategy"]
    assert evidence.expires_at.isoformat() == "2026-09-28T12:00:00+00:00"


def test_generation_persists_the_exact_grounded_research_url():
    engine = _engine()
    exact_url = "HTTPS://Acme.Example/strategy#platform"
    with Session(engine) as session:
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent(f"Evidence {exact_url}"),
            formatter=_Agent(_draft()),
        )
        evidence = load_company_intelligence(session, "Acme")

    assert evidence is not None
    assert evidence.sources[0].url == exact_url
    assert evidence.insights[0].citations == [exact_url]


def test_failed_refresh_preserves_last_good_company_dossier():
    engine = _engine()
    with Session(engine) as session:
        original = generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent("https://acme.example/strategy"),
            formatter=_Agent(_draft()),
        )
        with pytest.raises(ValueError, match="no grounded insights"):
            generate_company_intelligence(
                session,
                company="Acme",
                settings=Settings(),
                research_agent=_Agent("No URLs"),
                formatter=_Agent(_draft()),
            )
        rows = session.exec(select(CompanyIntelligenceEvidenceRow)).all()

    assert len(rows) == 1
    assert rows[0].id == original.id
    assert rows[0].evidence_json["overview"] == "Acme builds infrastructure software."
