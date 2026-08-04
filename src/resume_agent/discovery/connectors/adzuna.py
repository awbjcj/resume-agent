import re
from urllib.parse import urlsplit


from resume_agent.discovery.connectors import http as board
from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.connectors.base import FetchResult, RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.harvest import gate_and_limit
from resume_agent.discovery.connectors.text import (
    html_to_markdown,
    is_materially_richer,
)
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.discovery.url_ingest.browser import render_pages
from resume_agent.discovery.url_ingest.fetch import is_linkedin
from resume_agent.discovery.url_ingest.greenhouse import read_greenhouse_posting
from resume_agent.discovery.url_ingest.models import PageContent

_BASE = "https://api.adzuna.com/v1/api/jobs"
_DETAIL_SELECTORS = (
    '[class*="job-description"]',
    '[id*="job-description"]',
    '[data-testid*="job-description"]',
    '[data-qa*="job-description"]',
    '[class*="jobDescription"]',
    '[id*="jobDescription"]',
    '[class*="description"]',
    '[id*="description"]',
    "article",
    "main",
)


def parse_adzuna(payload: dict) -> list[RawJob]:
    """Map an Adzuna search payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("results", []):
        jobs.append(
            RawJob(
                source="adzuna",
                url=item.get("redirect_url"),
                company=(item.get("company") or {}).get("display_name"),
                title=item.get("title"),
                location=(item.get("location") or {}).get("display_name"),
                jd_text=item.get("description") or "",
                posted_at=parse_iso_datetime(item.get("created")),
            )
        )
    return jobs


# Markdown image syntax (company logos, icons) is never JD content; markdownify
# emits it for every <img>, so strip it before measuring/keeping a candidate.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _clean_lines(text: str) -> str:
    lines = [_MD_IMAGE.sub("", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _json_ld_descriptions(soup: BeautifulSoup) -> list[str]:
    descriptions: list[str] = []

    def visit(node) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(item).lower() == "jobposting" for item in types):
            raw = node.get("description")
            if isinstance(raw, str):
                descriptions.append(html_to_markdown(raw))
        graph = node.get("@graph")
        if graph is not None:
            visit(graph)

    import json

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            visit(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return descriptions


def _candidate_texts(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = [_clean_lines(text) for text in _json_ld_descriptions(soup)]
    for selector in _DETAIL_SELECTORS:
        for node in soup.select(selector):
            if isinstance(node, Tag):
                # Markdown (not flat get_text) so headings/bullets in the JD survive.
                text = _clean_lines(html_to_markdown(node.decode_contents()))
                if text:
                    candidates.append(text)
    candidates.append(_clean_lines(html_to_markdown(html)))
    return [candidate for candidate in candidates if candidate]


def _best_detail_text(html: str, fallback: str) -> str | None:
    """First materially-richer candidate in specificity order (clean JD over page chrome).

    ``_candidate_texts`` is ordered most-specific first (JSON-LD JobPosting, then the
    job-description containers, then ``article``/``main``, then whole-page markdown last).
    Picking the first that clears the richness bar prefers the clean employer-authored
    description over a longer whole-page dump full of nav and footer links.
    """
    for candidate in _candidate_texts(html):
        if is_materially_richer(candidate, fallback):
            return candidate
    return None


def enrich_adzuna_job(job: RawJob, page: PageContent | None) -> RawJob:
    """Replace Adzuna's snippet with the full JD from an already-rendered detail page.

    Adzuna search results expose only a snippet, and its redirect link is a bot-gated
    click-tracker that only a real browser can follow to the employer posting. ``page``
    is that post-redirect page (rendered upstream by ``render_pages``). Enrichment stays
    best-effort: a missing page, or one with nothing materially richer than the snippet,
    leaves the original RawJob intact.
    """
    if page is None:
        return job
    host = (urlsplit(page.final_url).hostname or "").lower()
    title = job.title
    company = job.company
    location = job.location
    jd_text: str | None = None
    if is_linkedin(host):
        meta = parse_detail_meta(page.html)
        title = meta.title or title
        company = meta.company or company
        location = meta.location or location
        jd_text = parse_job_detail(page.html)
    else:
        target = identify_host(page.final_url)
        if target and target.ats == "greenhouse":
            # None when the page yielded no description; the generic
            # _best_detail_text pass below still gets its chance at it.
            extracted = read_greenhouse_posting(page.html)
            if extracted is not None:
                title = extracted.title or title
                company = extracted.company or company
                location = extracted.location or location
                jd_text = extracted.jd_text
    jd_text = (
        jd_text if jd_text and is_materially_richer(jd_text, job.jd_text) else None
    )
    jd_text = jd_text or _best_detail_text(page.html, job.jd_text)
    if not jd_text:
        return job
    return RawJob(
        source=job.source,
        url=job.url,
        company=company,
        title=title,
        location=location,
        jd_text=jd_text,
        posted_at=job.posted_at,
    )


def enrich_adzuna_jobs(jobs: list[RawJob]) -> tuple[list[RawJob], dict[str, str]]:
    """Render every job's redirect link in one browser pass, then enrich each in place.

    A single browser context is reused across the batch (distinct ads are safe; the
    boomerang only bites when the *same* ad is re-clicked). Failures are isolated: a
    redirect that won't render, or a launch that fails outright, leaves snippets intact
    and is recorded in the returned failures map.
    """
    urls = [job.url for job in jobs if job.url]
    try:
        pages = render_pages(urls)
    except Exception as exc:  # noqa: BLE001 - no browser -> keep every snippet.
        return jobs, {"adzuna": type(exc).__name__}
    enriched: list[RawJob] = []
    failures: dict[str, str] = {}
    for job in jobs:
        page = pages.get(job.url) if job.url else None
        if job.url and page is None:
            failures[job.url] = "render_failed"
        try:
            enriched.append(enrich_adzuna_job(job, page))
        except Exception as exc:  # noqa: BLE001 - extraction must not kill the pull.
            failures[job.url or job.title or "unknown"] = type(exc).__name__
            enriched.append(job)
    return enriched, failures


class AdzunaConnector:
    """Keyword aggregator. One search call; results filtered client-side too."""

    name = "adzuna"
    concurrent_fetch = False

    def __init__(
        self,
        app_id: str,
        app_key: str,
        country: str = "us",
        *,
        enrich_details: bool = True,
        configured_limit: int | None = None,
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.enrich_details = enrich_details
        self.configured_limit = configured_limit

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        if self.configured_limit is not None:
            limit = self.configured_limit
        jobs, filtered = gate_and_limit(
            parse_adzuna(self._get_results(search)), search, limit, skip_seen
        )
        if not self.enrich_details:
            return FetchResult(jobs=jobs, filtered=filtered)
        enriched, failures = enrich_adzuna_jobs(jobs)
        return FetchResult(jobs=enriched, failures=failures, filtered=filtered)

    def _get_results(self, search: SearchConfig) -> dict:
        role_terms = [
            term.strip()
            for term in [*search.role_anchors, *search.keywords]
            if term.strip()
        ]
        params: dict[str, str | int] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "category": "it-jobs",
            "results_per_page": 50,
        }
        if role_terms:
            # Adzuna `what_or` is space-delimited (match any word); commas would
            # cling to terms ("engineer,") and break matching.
            params["what_or"] = " ".join(dict.fromkeys(role_terms))
        excludes = [term.strip() for term in search.exclude_terms if term.strip()]
        if excludes:
            params["what_exclude"] = " ".join(excludes)
        if search.locations:
            params["where"] = search.locations[0]
            if search.distance is not None:
                params["distance"] = search.distance
        if search.min_salary is not None:
            params["salary_min"] = search.min_salary
        if search.max_days_old is not None:
            params["max_days_old"] = search.max_days_old
        # Page 1 preserves the current single-request fetch volume while narrowing the query.
        resp = board.get(f"{_BASE}/{self.country}/search/1", params=params)
        resp.raise_for_status()
        return resp.json()
