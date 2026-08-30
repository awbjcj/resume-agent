from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.db import init_db, make_engine
from resume_agent.services.scout_intelligence import ScoutCompanyIntelligenceLookup
from resume_agent.tracking.tables import CompanyIntelligenceEvidenceRow


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def _evidence(
    *, expires_at: datetime, version_number: int
) -> CompanyIntelligenceEvidence:
    return CompanyIntelligenceEvidence(
        normalized_company="acme",
        display_company="Acme",
        overview="Acme builds reliable inference systems.",
        insights=[
            CompanyIntelligenceInsight(
                axis="engineering_culture",
                summary="The platform team publishes reliability work.",
                why_it_matters="Useful for infrastructure candidates.",
                citations=["https://acme.example/engineering"],
            )
        ],
        sources=[
            CompanyIntelligenceSource(
                title="Engineering at Acme",
                url="https://acme.example/engineering",
                publisher="Acme",
                source_type="official",
                source_tier="company_official",
            )
        ],
        retrieved_at=NOW - timedelta(days=2),
        expires_at=expires_at,
        caveat="Verify important claims.",
        version_number=version_number,
    )


def _lookup(evidence: CompanyIntelligenceEvidence) -> ScoutCompanyIntelligenceLookup:
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        session.add(
            CompanyIntelligenceEvidenceRow(
                normalized_company="acme",
                display_company="Acme",
                evidence_json=evidence.model_dump(mode="json"),
                retrieved_at=evidence.retrieved_at,
                expires_at=evidence.expires_at,
                schema_version=2,
            )
        )
        session.commit()
    return ScoutCompanyIntelligenceLookup(engine, now=NOW)


def test_lookup_reuses_saved_dossier_by_canonical_company_name():
    lookup = _lookup(_evidence(expires_at=NOW + timedelta(days=10), version_number=3))

    snapshots = lookup.lookup_many(["Acme, Inc.", "Unknown Co"])

    assert snapshots["acme"].status == "ready"
    assert snapshots["acme"].version_number == 3
    assert snapshots["unknown"].status == "missing"

    payload = lookup.get_saved_company_intelligence(["Acme, Inc.", "Unknown Co"])
    assert '"status":"ready"' in payload
    assert '"versionNumber":3' in payload
    assert "https://acme.example/engineering" in payload
    assert '"status":"missing"' in payload


def test_lookup_keeps_expired_dossier_visible_and_marks_it_stale():
    lookup = _lookup(_evidence(expires_at=NOW - timedelta(seconds=1), version_number=2))

    snapshot = lookup.lookup_many(["The Acme LLC"])["acme"]

    assert snapshot.status == "stale"
    assert snapshot.evidence is not None
    assert snapshot.evidence.overview.startswith("Acme builds")
