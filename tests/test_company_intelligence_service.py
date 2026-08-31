from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from resume_tailor_harness.company_intelligence.models import (
    CompanyIntelligenceDraft,
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_tailor_harness.config import Settings
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.llm_runner import UnparsedAgentOutput
from resume_tailor_harness.services.company_intelligence import (
    generate_company_intelligence,
    load_company_intelligence,
    load_company_intelligence_history,
)
from resume_tailor_harness.tracking.tables import (
    CompanyIntelligenceEvidenceRow,
    CompanyIntelligenceVersionRow,
)


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
    assert evidence.sources[0].source_tier == "company_official"
    assert evidence.sources[0].last_verified_at == now
    assert evidence.insights[0].verification_state == "single_source"
    assert evidence.version_number == 1
    assert evidence.expires_at.isoformat() == "2026-09-28T12:00:00+00:00"


def test_generation_reports_unparsed_formatter_output_at_the_model_boundary():
    engine = _engine()
    with Session(engine) as session:
        with pytest.raises(
            UnparsedAgentOutput,
            match="Expected CompanyIntelligenceDraft from company-intelligence format agent",
        ):
            generate_company_intelligence(
                session,
                company="Acme",
                settings=Settings(),
                research_agent=_Agent("https://acme.example/strategy"),
                formatter=_Agent("not structured output"),
            )


def test_legacy_payload_loads_with_v2_compatibility_defaults():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    legacy = {
        "normalized_company": "acme",
        "display_company": "Acme",
        "overview": "Legacy evidence",
        "insights": [
            {
                "axis": "strategy",
                "summary": "One supported claim",
                "citations": ["https://acme.example/strategy"],
            }
        ],
        "sources": [
            {
                "title": "Strategy",
                "url": "https://acme.example/strategy",
                "publisher": "Acme",
                "source_type": "official",
            }
        ],
        "retrieved_at": now.isoformat(),
        "expires_at": now.isoformat(),
        "caveat": "Verify",
    }

    evidence = CompanyIntelligenceEvidence.model_validate(legacy)

    assert evidence.schema_version == 2
    assert evidence.version_id is None
    assert evidence.version_number == 1
    assert evidence.research_depth == "standard"
    assert evidence.sources[0].source_tier == "other"
    assert evidence.insights[0].verification_state == "single_source"


def test_server_requires_distinct_authorities_for_corroborated_claims():
    engine = _engine()
    draft = _draft()
    draft.sources.append(
        CompanyIntelligenceSource(
            title="Independent strategy analysis",
            url="https://analysis.org/acme",
            publisher="Analysis",
            source_tier="reputable_independent",
        )
    )
    draft.insights[0].citations.append("https://analysis.org/acme")
    draft.insights[0].verification_state = "corroborated"
    with Session(engine) as session:
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent(
                "https://acme.example/strategy https://analysis.org/acme"
            ),
            formatter=_Agent(draft),
        )
        evidence = load_company_intelligence(session, "Acme")

    assert evidence is not None
    assert evidence.insights[0].verification_state == "corroborated"


def test_server_treats_subdomains_as_one_source_authority():
    engine = _engine()
    draft = _draft()
    second_url = "https://investors.acme.example/strategy"
    draft.sources.append(
        CompanyIntelligenceSource(
            title="Investor strategy page",
            url=second_url,
            publisher="Acme Investor Relations",
            source_type="official",
        )
    )
    draft.insights[0].citations.append(second_url)
    draft.insights[0].verification_state = "corroborated"
    with Session(engine) as session:
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent(
                "https://acme.example/strategy " + second_url
            ),
            formatter=_Agent(draft),
        )
        evidence = load_company_intelligence(session, "Acme")

    assert evidence is not None
    assert evidence.insights[0].verification_state == "single_source"


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
        versions = session.exec(select(CompanyIntelligenceVersionRow)).all()

    assert len(rows) == 1
    assert rows[0].id == original.id
    assert rows[0].evidence_json["overview"] == "Acme builds infrastructure software."
    assert len(versions) == 1


def test_refresh_appends_versions_and_computes_a_deterministic_diff():
    engine = _engine()
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    changed = _draft()
    changed.insights[0].summary = "Acme expanded its platform investment."
    changed.sources.append(
        CompanyIntelligenceSource(
            title="Platform update",
            url="https://news.example/acme-platform",
            publisher="News",
            source_tier="reputable_independent",
        )
    )
    changed.insights[0].citations.append("https://news.example/acme-platform")

    with Session(engine) as session:
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent("https://acme.example/strategy"),
            formatter=_Agent(_draft()),
            now=now,
            research_depth="quick",
        )
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent(
                "https://acme.example/strategy https://news.example/acme-platform"
            ),
            formatter=_Agent(changed),
            now=now.replace(day=30),
            research_depth="deep",
        )
        history = load_company_intelligence_history(session, "Acme")

    assert [item.version_number for item in history] == [2, 1]
    assert [item.research_depth for item in history] == ["deep", "quick"]
    assert history[0].previous_version_id == history[1].version_id
    assert history[0].changes.changed_axes == ["strategy"]
    assert history[0].changes.added_source_urls == [
        "https://news.example/acme-platform"
    ]


def test_first_v2_refresh_snapshots_a_legacy_current_row_before_new_version():
    engine = _engine()
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    legacy = CompanyIntelligenceEvidence(
        normalized_company="acme",
        display_company="Acme",
        overview="Legacy current row",
        insights=_draft().insights[:1],
        sources=_draft().sources[:1],
        retrieved_at=now,
        expires_at=now,
        caveat="Verify",
    ).model_dump(mode="json", exclude={"version_id", "version_number"})
    with Session(engine) as session:
        session.add(
            CompanyIntelligenceEvidenceRow(
                normalized_company="acme",
                display_company="Acme",
                evidence_json=legacy,
                retrieved_at=now,
                expires_at=now,
            )
        )
        session.commit()
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Agent("https://acme.example/strategy"),
            formatter=_Agent(_draft()),
            now=now.replace(day=30),
        )
        history = load_company_intelligence_history(session, "Acme")

    assert [item.version_number for item in history] == [2, 1]
    assert history[1].overview == "Legacy current row"
