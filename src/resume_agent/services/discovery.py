"""Discovery + ingest use-cases: load config/facts, build agents, run, return results.

Wraps the lower-level discovery.pipeline / discovery.connectors so adapters
(CLI, API) never duplicate the build-and-load wiring. Long-running calls accept
an optional ProgressReporter passed straight through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

import httpx
import asyncio
import inspect
from datetime import datetime, timezone
from playwright.sync_api import Error as PlaywrightError
from sqlalchemy import func, select, text
from sqlmodel import Session, col, select as model_select

from resume_agent.config import get_settings
from resume_agent.career_skills.models import JobAnalysisMeta, read_job_analysis_meta
from resume_agent.discovery.connectors.config import load_connectors_config
from resume_agent.discovery.connectors.registry import build_source_connectors
from resume_agent.discovery.connectors.runner import PullReport, run_pull
from resume_agent.discovery.ingest import (
    IngestOutcome,
    ingest_jobs,
    save_or_upgrade,
)
from resume_agent.discovery.pipeline import StageScope, discover, reprocess
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.h1b.cache import load_company_evidence
from resume_agent.h1b.models import H1BEnrichmentReport, H1BSponsorshipEvidence
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.matrix import (
    SkillMatrix,
    effective_cluster_map,
    load_matrix,
    load_overrides,
)
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.services.agents import (
    DiscoveryBundle,
    build_discovery_bundle,
    build_url_extract_agent,
)
from resume_agent.taxonomy.clusters import ClusterMap, load_cluster_map
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tenancy.limits import (
    DEFAULT_MAX_ACTIVE_JOBS,
    active_limit,
    enforce_active_budget,
)
from resume_agent.tenancy.paths import (
    CONNECTORS_PATH as DEFAULT_CONNECTORS,
)
from resume_agent.tenancy.paths import (
    FACTS_PATH as DEFAULT_FACTS,
)
from resume_agent.tenancy.paths import (
    SEARCH_PATH as DEFAULT_SEARCH,
)
from resume_agent.tenancy.paths import (
    TELEMETRY_PATH as CONNECTOR_RUNS_PATH,
)
from resume_agent.tenancy.paths import (
    resolve_tenant_path,
)
from resume_agent.tracking.tables import Job
from resume_agent.tracking.tables import H1BCompanyEvidence, JobStatus


class H1BEnricher(Protocol):
    async def enrich(self, engine, companies: list[str]) -> H1BEnrichmentReport: ...


class DefaultH1BEnricher:
    async def enrich(self, engine, companies: list[str]) -> H1BEnrichmentReport:
        from resume_agent.h1b.service import (
            DefaultCompanyNameResolverFactory,
            DefaultSponsorshipAgentFactory,
            enrich_companies,
        )

        settings = get_settings()
        return await enrich_companies(
            engine,
            companies,
            settings=settings,
            agent_factory=DefaultSponsorshipAgentFactory(settings),
            company_resolver_factory=DefaultCompanyNameResolverFactory(settings),
        )


def run_h1b_enrichment(
    session: Session,
    config,
    *,
    enricher: H1BEnricher | None,
    scope: StageScope = StageScope(),
    reporter: ProgressReporter | None = None,
) -> dict[int, H1BSponsorshipEvidence]:
    """Research filtered companies and return fresh evidence for silent jobs."""
    jobs = [
        job
        for job in session.exec(
            model_select(Job).where(Job.status == JobStatus.filtered.value)
        ).all()
        if scope.job_ids is None or job.id in scope.job_ids
    ]
    if not config.sponsorship_required:
        if reporter:
            reporter.begin(
                0,
                "Checking historical sponsorship",
                phase_index=3,
                phase_count=4,
            )
            reporter.step(0)
        return {}

    # Research every surviving job's company so each card gets an answer.
    research_jobs: list[Job] = []
    job_counts: dict[str, int] = {}
    companies: dict[str, str] = {}
    for job in jobs:
        normalized = normalize_company(job.company)
        if normalized:
            research_jobs.append(job)
            job_counts[normalized] = job_counts.get(normalized, 0) + 1
            companies.setdefault(normalized, job.company or normalized)
    if reporter:
        reporter.begin(
            len(research_jobs),
            "Checking historical sponsorship",
            phase_index=3,
            phase_count=4,
        )
    if not research_jobs:
        if reporter:
            reporter.step(len(research_jobs))
        return {}

    now = datetime.now(timezone.utc)
    cached_for_display = load_company_evidence(session, list(companies.values()))
    fresh_by_company = {
        key: evidence
        for key, evidence in cached_for_display.items()
        if evidence.is_fresh(now)
    }
    # Expired rows still render on cards, but refreshing them costs a call and
    # they must never silently become scorer input if the cap defers them.
    uncached = sorted(
        (key for key in companies if key not in fresh_by_company),
        key=lambda key: (-job_counts[key], key),
    )
    cap = get_settings().h1b_enrich_max_companies_per_run
    selected = uncached if cap == 0 else uncached[:cap]

    report = H1BEnrichmentReport(by_company={})
    if selected and enricher is not None:
        outcome = enricher.enrich(session.get_bind(), [companies[key] for key in selected])
        if inspect.isawaitable(outcome):
            outcome = asyncio.run(outcome)
        report = H1BEnrichmentReport.model_validate(outcome)

    available: dict[str, H1BSponsorshipEvidence] = {
        **fresh_by_company,
        **report.by_company,
    }
    evidence_ids: dict[str, int | None] = {}
    if available:
        cache_rows = session.exec(
            model_select(H1BCompanyEvidence).where(
                col(H1BCompanyEvidence.normalized_company).in_(list(available))
            )
        ).all()
        evidence_ids = {row.normalized_company: row.id for row in cache_rows}

    evidence_by_job: dict[int, H1BSponsorshipEvidence] = {}
    for job in research_jobs:
        normalized = normalize_company(job.company)
        if not normalized:
            continue
        evidence = available.get(normalized)
        if evidence is None:
            continue
        meta = read_job_analysis_meta(job.analysis_meta_json) or JobAnalysisMeta()
        meta.h1b_evidence_id = evidence_ids.get(normalized)
        job.analysis_meta_json = meta.model_dump(mode="json")
        session.add(job)
        if (
            job.id is not None
            and (job.criteria_json or {}).get("sponsorship_signal") == "silent"
        ):
            evidence_by_job[job.id] = evidence
    session.commit()
    if reporter:
        reporter.step(len(research_jobs))
    return evidence_by_job


@dataclass(frozen=True)
class RefreshReport:
    pulled: int
    totals: dict[str, int]
    status_counts: dict[str, int]
    failures: dict[str, dict[str, str]]


class LinkedInScrapeResult(TypedDict):
    added: int
    failures: dict[str, str]


class ActiveJobQuotaError(RuntimeError):
    code = "QUOTA_EXCEEDED"


def _save_with_active_job_limit(session: Session, **values) -> Job | None:
    maximum = active_limit("max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS)
    allow_insert = True
    if maximum is not None and maximum > 0:
        if not session.in_transaction():
            session.execute(text("BEGIN IMMEDIATE"))
        active_count = int(
            session.execute(
                select(func.count()).select_from(Job).where(col(Job.archived_at).is_(None))
            ).scalar_one()
        )
        allow_insert = active_count < maximum
    job, outcome = save_or_upgrade(session, allow_insert=allow_insert, **values)
    if outcome is IngestOutcome.quota_skipped:
        raise ActiveJobQuotaError(f"active job limit reached ({maximum})")
    return job


def _skill_artifacts(
    facts_path: str, facts: ProfileFacts
) -> tuple[SkillMatrix | None, ClusterMap]:
    profile_dir = resolve_tenant_path(facts_path).parent
    overrides = load_overrides(profile_dir / "overrides.yaml")
    cluster_map = effective_cluster_map(
        load_cluster_map(profile_dir / "cluster_map.json"), overrides
    )
    matrix = load_matrix(
        profile_dir / "matrix.json", facts=facts, cluster_map=cluster_map
    )
    return matrix, cluster_map


def add_job_from_text(
    session: Session,
    *,
    jd_text: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
) -> Job | None:
    """Add a manually-supplied job. Returns None when deduped away."""
    return _save_with_active_job_limit(
        session,
        source="manual",
        jd_text=jd_text,
        url=url,
        company=company,
        title=title,
        location=location,
    )


class UrlFetchError(RuntimeError):
    """Raised when a URL could not be fetched or no JD could be extracted."""


def add_job_from_url(
    session: Session,
    *,
    url: str,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    allow_browser: bool = True,
) -> Job | None:
    """Fetch a posting URL, auto-extract fields, and add it. Returns None when deduped."""
    enforce_active_budget()
    try:
        raw = job_from_url(
            url,
            agent=build_url_extract_agent(),
            allow_browser=allow_browser and get_settings().browser_enabled,
        )
    except (httpx.HTTPError, PlaywrightError) as exc:
        raise UrlFetchError(f"Couldn't fetch {url}: {exc}") from exc
    if raw is None:
        raise UrlFetchError("Couldn't extract a job description from that URL.")
    return _save_with_active_job_limit(
        session,
        source="url",
        jd_text=raw.jd_text,
        url=url,
        company=company or raw.company,
        title=title or raw.title,
        location=location or raw.location,
    )


def discover_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
    job_ids: set[int] | None = None,
    h1b_enricher: H1BEnricher | None = None,
) -> dict[str, int]:
    """Run the full discovery funnel; return final status counts."""
    enforce_active_budget()
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    matrix, cluster_map = _skill_artifacts(facts_path, facts)
    bundle = bundle or build_discovery_bundle()
    if h1b_enricher is None and get_settings().h1b_mcp_enabled:
        h1b_enricher = DefaultH1BEnricher()
    discover_kwargs = {
        "canonicalizer": bundle.canonicalizer,
        "industry_classifier": bundle.industry_classifier,
        "reporter": reporter,
        "scope": StageScope(job_ids=frozenset(job_ids)) if job_ids is not None else StageScope(),
        "matrix": matrix,
        "cluster_map": cluster_map,
    }
    if h1b_enricher is not None:
        discover_kwargs["h1b_enricher"] = h1b_enricher
    return discover(
        session,
        config,
        facts,
        bundle.extract,
        bundle.fit,
        bundle.relevance,
        **discover_kwargs,
    )


def pull_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    limit: int | None = None,
    source_ids: list[str] | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
    skip_known: bool = True,
    relearn: bool = False,
) -> PullReport:
    """Run selected or all enabled pullable source connectors and ingest results."""
    enforce_active_budget()
    search_config = load_search_config(search_path)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_source_connectors(
        connectors_config, get_settings(), source_ids=source_ids
    )
    if relearn:
        for connector in connectors:
            if isinstance(connector, DashboardScraper):
                connector.relearn = True
    return run_pull(
        session,
        connectors,
        search_config,
        telemetry_path,
        limit=limit,
        reporter=reporter,
        finish=finish,
        skip_known=skip_known,
        max_active_jobs=active_limit("max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS),
    )


def scrape_linkedin_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
) -> LinkedInScrapeResult:
    """Scrape LinkedIn in a visible browser and ingest all fetched postings."""
    enforce_active_budget()
    if not get_settings().browser_enabled:
        return {
            "added": 0,
            "failures": {
                "linkedin": "requires a local browser (browser_enabled=false)"
            },
        }
    search_config = load_search_config(search_path)
    connector = build_linkedin_scraper()
    if reporter is not None:
        reporter.begin(1, "Scraping LinkedIn")
    result = connector.fetch(search_config, limit=limit)
    added = ingest_jobs(
        session,
        result.jobs,
        max_active_jobs=active_limit("max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS),
    )
    if reporter is not None:
        reporter.step(1)
    return {
        "added": sum(added.values()),
        "failures": dict(result.failures),
    }


def reprocess_jobs(
    session: Session,
    *,
    scopes: list[str],
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
    h1b_enricher: H1BEnricher | None = None,
) -> dict[str, int]:
    """Re-run the full funnel over the chosen scopes; returns final status counts."""
    enforce_active_budget()
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    matrix, cluster_map = _skill_artifacts(facts_path, facts)
    bundle = bundle or build_discovery_bundle()
    if h1b_enricher is None and get_settings().h1b_mcp_enabled:
        h1b_enricher = DefaultH1BEnricher()
    return reprocess(
        session,
        config,
        facts,
        bundle.extract,
        bundle.fit,
        scopes,
        relevance_agent=bundle.relevance,
        canonicalizer=bundle.canonicalizer,
        industry_classifier=bundle.industry_classifier,
        reporter=reporter,
        matrix=matrix,
        cluster_map=cluster_map,
        h1b_enricher=h1b_enricher,
    )


def refresh_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    facts_path: str = DEFAULT_FACTS,
    limit: int | None = None,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> RefreshReport:
    """Pull from every connector, then discover the newly-added raw jobs, in one pass."""
    pull_report = pull_jobs(
        session,
        search_path=search_path,
        connectors_path=connectors_path,
        telemetry_path=telemetry_path,
        limit=limit,
        reporter=reporter,
        finish=False,
    )
    counts = discover_jobs(
        session,
        search_path=search_path,
        facts_path=facts_path,
        bundle=bundle,
        reporter=reporter,
        job_ids=set(pull_report.changed_raw_job_ids),
    )
    return RefreshReport(
        pulled=sum(pull_report.totals.values()),
        totals=pull_report.totals,
        status_counts=counts,
        failures=pull_report.failures,
    )
