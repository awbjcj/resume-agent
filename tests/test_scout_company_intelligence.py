import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from sqlmodel import Session

from resume_tailor_harness.company_intelligence.models import (
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.services.scout_intelligence import ScoutCompanyIntelligenceLookup
from resume_tailor_harness.tracking.tables import CompanyIntelligenceEvidenceRow


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


@contextmanager
def _lookup(
    evidence: CompanyIntelligenceEvidence,
) -> Iterator[ScoutCompanyIntelligenceLookup]:
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
    with Session(engine) as session:
        yield ScoutCompanyIntelligenceLookup(session, now=NOW)


def test_lookup_reuses_saved_dossier_by_canonical_company_name():
    with _lookup(
        _evidence(expires_at=NOW + timedelta(days=10), version_number=3)
    ) as lookup:
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
    with _lookup(
        _evidence(expires_at=NOW - timedelta(seconds=1), version_number=2)
    ) as lookup:
        snapshot = lookup.lookup_many(["The Acme LLC"])["acme"]

        assert snapshot.status == "stale"
        assert snapshot.evidence is not None
        assert snapshot.evidence.overview.startswith("Acme builds")


def test_tool_returns_only_a_bounded_cited_projection():
    urls = [f"https://acme.example/source-{index}" for index in range(12)]
    evidence = _evidence(
        expires_at=NOW + timedelta(days=10),
        version_number=4,
    ).model_copy(
        update={
            "overview": "O" * 2_000,
            "caveat": "C" * 800,
            "insights": [
                CompanyIntelligenceInsight(
                    axis="engineering_culture",
                    summary="S" * 1_000,
                    why_it_matters="W" * 800,
                    conflicting_evidence="X" * 600,
                    citations=urls[index : index + 5],
                )
                for index in range(6)
            ],
            "sources": [
                CompanyIntelligenceSource(
                    title="T" * 500 if index == 0 else f"Source {index}",
                    url=url,
                    publisher="P" * 300 if index == 0 else "Acme",
                    source_type="official",
                    source_tier="company_official",
                )
                for index, url in enumerate([*urls, "https://unused.example/source"])
            ],
        }
    )

    with _lookup(evidence) as lookup:
        company = json.loads(lookup.get_saved_company_intelligence(["Acme"]))[
            "companies"
        ][0]

    assert len(company["overview"]) == 1_200
    assert len(company["insights"]) == 5
    assert all(len(insight["citations"]) <= 4 for insight in company["insights"])
    assert len(company["sources"]) <= 8
    assert len(company["sources"][0]["title"]) == 240
    assert len(company["sources"][0]["publisher"]) == 160
    assert "https://unused.example/source" not in {
        source["url"] for source in company["sources"]
    }
    assert company["truncation"]["applied"] is True
    assert company["truncation"]["omittedInsights"] == 1
    assert company["truncation"]["clippedFields"]


def test_tool_never_invokes_the_company_research_provider(monkeypatch):
    def fail_if_refreshed(*_args, **_kwargs):
        raise AssertionError("saved dossier lookup must not refresh research")

    monkeypatch.setattr(
        "resume_tailor_harness.services.company_intelligence.generate_company_intelligence",
        fail_if_refreshed,
    )
    with _lookup(
        _evidence(expires_at=NOW + timedelta(days=10), version_number=3)
    ) as lookup:
        payload = lookup.get_saved_company_intelligence(["Acme"])

    assert json.loads(payload)["companies"][0]["status"] == "ready"
