"""Discovery + ingest use-cases: load config/facts, build agents, run, return results.

Wraps the lower-level discovery.pipeline / discovery.connectors so adapters
(CLI, API) never duplicate the build-and-load wiring. Long-running calls accept
an optional ProgressReporter passed straight through.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.config import load_connectors_config
from resume_agent.discovery.connectors.registry import build_source_connectors
from resume_agent.discovery.connectors.runner import PullReport, run_pull
from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.pipeline import discover, reprocess
from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.profile.store import load_facts
from resume_agent.profile.matrix import effective_cluster_map, load_matrix, load_overrides
from resume_agent.progress import ProgressReporter
from resume_agent.services.agents import (
    DiscoveryBundle,
    build_discovery_bundle,
    build_url_extract_agent,
)
from resume_agent.tracking.tables import Job
from resume_agent.taxonomy.clusters import load_cluster_map

DEFAULT_SEARCH = "config/search.yaml"
DEFAULT_FACTS = "data/profile/facts.json"
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"


@dataclass(frozen=True)
class RefreshReport:
    pulled: int
    totals: dict[str, int]
    status_counts: dict[str, int]
    failures: dict[str, dict[str, str]]


def _skill_artifacts(facts_path: str, facts):
    profile_dir = Path(facts_path).parent
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
    return add_job(
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
    try:
        raw = job_from_url(
            url, agent=build_url_extract_agent(), allow_browser=allow_browser
        )
    except (httpx.HTTPError, PlaywrightError) as exc:
        raise UrlFetchError(f"Couldn't fetch {url}: {exc}") from exc
    if raw is None:
        raise UrlFetchError("Couldn't extract a job description from that URL.")
    return add_job(
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
) -> dict[str, int]:
    """Run the full discovery funnel; return final status counts."""
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    matrix, cluster_map = _skill_artifacts(facts_path, facts)
    bundle = bundle or build_discovery_bundle()
    return discover(
        session,
        config,
        facts,
        bundle.extract,
        bundle.fit,
        bundle.relevance,
        canonicalizer=bundle.canonicalizer,
        industry_classifier=bundle.industry_classifier,
        reporter=reporter,
        job_ids=job_ids,
        matrix=matrix,
        cluster_map=cluster_map,
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
    )


def reprocess_jobs(
    session: Session,
    *,
    scopes: list[str],
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Re-run the full funnel over the chosen scopes; returns final status counts."""
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    matrix, cluster_map = _skill_artifacts(facts_path, facts)
    bundle = bundle or build_discovery_bundle()
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
