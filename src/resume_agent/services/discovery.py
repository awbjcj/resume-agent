"""Discovery + ingest use-cases: load config/facts, build agents, run, return results.

Wraps the lower-level discovery.pipeline / discovery.connectors so adapters
(CLI, API) never duplicate the build-and-load wiring. Long-running calls accept
an optional ProgressReporter passed straight through.
"""

from __future__ import annotations

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.config import load_connectors_config
from resume_agent.discovery.connectors.registry import build_connectors
from resume_agent.discovery.connectors.runner import PullReport, run_pull
from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.pipeline import backfill_rescore, discover, reextract
from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.services.agents import DiscoveryBundle, build_discovery_bundle, build_url_extract_agent
from resume_agent.tracking.tables import Job

DEFAULT_SEARCH = "config/search.yaml"
DEFAULT_FACTS = "data/profile/facts.json"
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"


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
        session, source="manual", jd_text=jd_text, url=url,
        company=company, title=title, location=location,
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
        raw = job_from_url(url, agent=build_url_extract_agent(), allow_browser=allow_browser)
    except (httpx.HTTPError, PlaywrightError) as exc:
        raise UrlFetchError(f"Couldn't fetch {url}: {exc}") from exc
    if raw is None:
        raise UrlFetchError("Couldn't extract a job description from that URL.")
    return add_job(
        session, source="url", jd_text=raw.jd_text, url=url,
        company=company or raw.company, title=title or raw.title,
        location=location or raw.location,
    )


def discover_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Run the full discovery funnel; return final status counts."""
    config = load_search_config(search_path)
    facts = load_facts(facts_path)
    bundle = bundle or build_discovery_bundle()
    return discover(
        session, config, facts, bundle.extract, bundle.fit, bundle.relevance,
        canonicalizer=bundle.canonicalizer, reporter=reporter,
    )


def pull_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
) -> PullReport:
    """Run every enabled connector and ingest results."""
    search_config = load_search_config(search_path)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_connectors(connectors_config, get_settings())
    return run_pull(
        session, connectors, search_config, telemetry_path, limit=limit, reporter=reporter
    )


def reextract_metadata(
    session: Session,
    *,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> int:
    """Re-extract criteria_json for already-processed jobs (backfill new fields).

    The dashboard's "Re-extract" discover mode. Does not change status or fit.
    Returns the number of jobs updated.
    """
    bundle = bundle or build_discovery_bundle()
    if reporter is not None:
        reporter.begin(1, "Re-extracting job metadata")
    updated = reextract(session, bundle.extract)
    if reporter is not None:
        reporter.step(1, label=f"Re-extracted {updated} job(s)")
    return updated


def rescore_existing(
    session: Session,
    *,
    facts_path: str = DEFAULT_FACTS,
    bundle: DiscoveryBundle | None = None,
    reporter: ProgressReporter | None = None,
) -> int:
    """Backfill SIC + location for already-shortlisted jobs.

    The dashboard's "Re-score" discover mode. Does not change fit or status.
    Returns the number of jobs updated.
    """
    facts = load_facts(facts_path)
    bundle = bundle or build_discovery_bundle()
    if reporter is not None:
        reporter.begin(1, "Backfilling SIC + location")
    updated = backfill_rescore(session, facts, bundle.fit, canonicalizer=bundle.canonicalizer)
    if reporter is not None:
        reporter.step(1, label=f"Rescored {updated} job(s)")
    return updated
