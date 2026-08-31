from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_tailor_harness.config import Settings
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.h1b.cache import load_company_evidence
from resume_tailor_harness.h1b.models import (
    HISTORICAL_ONLY_CAVEAT,
    H1BEnrichmentReport,
    H1BSponsorshipEvidence,
)
from resume_tailor_harness.services.discovery import run_h1b_enrichment
from resume_tailor_harness.tracking.tables import H1BCompanyEvidence, Job, JobStatus


def _evidence(company: str) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        retrieved_at=now,
        expires_at=now + timedelta(days=30),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


def _persist_cache(
    session: Session, company: str, evidence: H1BSponsorshipEvidence
) -> None:
    assert evidence.expires_at is not None
    assert evidence.retrieved_at is not None
    session.add(
        H1BCompanyEvidence(
            normalized_company=company,
            status=evidence.status,
            evidence_json=evidence.model_dump(mode="json"),
            expires_at=evidence.expires_at,
            retrieved_at=evidence.retrieved_at,
        )
    )


def _expired_evidence(company: str) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        retrieved_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


class RecordingEnricher:
    """Captures which company labels were handed to the researcher."""

    def __init__(self):
        self.seen: list[str] = []

    async def enrich(self, engine, companies: list[str]) -> H1BEnrichmentReport:
        self.seen.extend(companies)
        from resume_tailor_harness.taxonomy.industries import normalize_company

        return H1BEnrichmentReport(
            by_company={
                normalized: _evidence(normalized)
                for c in companies
                if (normalized := normalize_company(c))
            }
        )


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def _add(session: Session, company: str, signal: str) -> Job:
    job = Job(
        source="manual",
        company=company,
        title=f"Role at {company}",
        jd_text="x",
        status=JobStatus.filtered.value,
        criteria_json={"sponsorship_signal": signal},
    )
    session.add(job)
    return job


def test_research_widens_beyond_silent_jobs(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()
    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(_env_file=None),  # type: ignore[call-arg]
    )
    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "explicit_no")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)
    assert {c.lower() for c in enricher.seen} == {"acme, inc.", "globex llc"}


def test_returned_scoring_map_stays_silent_only(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(_env_file=None),  # type: ignore[call-arg]
    )
    with Session(engine) as session:
        silent = _add(session, "Acme, Inc.", "silent")
        loud = _add(session, "Globex LLC", "explicit_no")
        session.commit()
        session.refresh(silent)
        session.refresh(loud)
        silent_id, loud_id = silent.id, loud.id
        result = run_h1b_enrichment(session, config, enricher=RecordingEnricher())
    assert silent_id in result
    assert loud_id not in result


def test_nothing_is_researched_when_sponsorship_is_not_required():
    engine = _engine()
    enricher = RecordingEnricher()
    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        session.commit()
        run_h1b_enrichment(
            session, SearchConfig(sponsorship_required=False), enricher=enricher
        )
    assert enricher.seen == []


def test_fresh_cache_hits_still_reach_the_scorer(monkeypatch):
    """A company already cached is not re-researched but must still score."""
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()
    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(_env_file=None),  # type: ignore[call-arg]
    )

    acme_evidence = _evidence("acme")
    globex_evidence = _evidence("globex")
    with Session(engine) as session:
        silent = _add(session, "Acme, Inc.", "silent")
        explicit_no = _add(session, "Globex LLC", "explicit_no")
        _persist_cache(session, "acme", acme_evidence)
        _persist_cache(session, "globex", globex_evidence)
        session.commit()
        session.refresh(silent)
        session.refresh(explicit_no)
        silent_id, explicit_no_id = silent.id, explicit_no.id
        result = run_h1b_enrichment(session, config, enricher=enricher)
        for job in (silent, explicit_no):
            meta = job.analysis_meta_json or {}
            assert meta.get("h1b_evidence_id") is not None
            assert meta.get("h1b_evidence_snapshot") is None

    assert enricher.seen == [], "a fresh cache hit must not be re-researched"
    assert silent_id in result, "a fresh cache hit must still reach the fit scorer"
    assert explicit_no_id not in result, "an explicit-no JD must not reach the scorer"


def test_fresh_cache_hits_still_reach_the_scorer_without_enricher(monkeypatch):
    """Disabling the enricher must not discard usable fresh cache evidence."""
    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_enrich_max_companies_per_run=50,
        ),
    )
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    with Session(engine) as session:
        silent = _add(session, "Acme, Inc.", "silent")
        explicit_no = _add(session, "Globex LLC", "explicit_no")
        _persist_cache(session, "acme", _evidence("acme"))
        _persist_cache(session, "globex", _evidence("globex"))
        session.commit()
        session.refresh(silent)
        session.refresh(explicit_no)
        silent_id, explicit_no_id = silent.id, explicit_no.id
        result = run_h1b_enrichment(session, config, enricher=None)
        for job in (silent, explicit_no):
            meta = job.analysis_meta_json or {}
            assert meta.get("h1b_evidence_id") is not None
            assert meta.get("h1b_evidence_snapshot") is None

    assert silent_id in result
    assert explicit_no_id not in result


def test_per_run_cap_takes_the_companies_with_the_most_jobs(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_enrich_max_companies_per_run=1,
        ),
    )

    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "silent")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)

    assert len(enricher.seen) == 1
    assert "acme" in enricher.seen[0].lower()


def test_per_run_cap_breaks_frequency_ties_by_normalized_name(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_enrich_max_companies_per_run=1,
        ),
    )

    with Session(engine) as session:
        _add(session, "Beta LLC", "silent")
        _add(session, "Acme, Inc.", "silent")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)

    assert enricher.seen == ["Acme, Inc."]


def test_expired_cache_deferred_by_cap_stays_out_of_scorer_map(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_enrich_max_companies_per_run=1,
        ),
    )

    with Session(engine) as session:
        stale_job = _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "silent")
        _add(session, "Globex LLC", "silent")
        _persist_cache(session, "acme", _expired_evidence("acme"))
        session.commit()
        session.refresh(stale_job)
        stale_id = stale_job.id
        result = run_h1b_enrichment(session, config, enricher=enricher)
        displayable = load_company_evidence(session, ["Acme, Inc."])

    assert enricher.seen == ["Globex LLC"]
    assert stale_id not in result
    assert displayable["acme"].status == "matched"


def test_zero_cap_researches_every_uncached_company(monkeypatch):
    engine = _engine()
    config = SearchConfig(sponsorship_required=True)
    enricher = RecordingEnricher()

    monkeypatch.setattr(
        "resume_tailor_harness.services.discovery.get_settings",
        lambda: Settings(
            _env_file=None,  # type: ignore[call-arg]
            h1b_enrich_max_companies_per_run=0,
        ),
    )

    with Session(engine) as session:
        _add(session, "Acme, Inc.", "silent")
        _add(session, "Globex LLC", "explicit_no")
        session.commit()
        run_h1b_enrichment(session, config, enricher=enricher)

    assert {company.lower() for company in enricher.seen} == {
        "acme, inc.",
        "globex llc",
    }
