import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_text, primary_search_term
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://careers.google.com/api/v3/search/"  # confirm at build time
_MAX_PAGES = 20


def parse_jobs(page: dict) -> list[RawJob]:
    jobs: list[RawJob] = []
    for item in page.get("jobs", []):
        locations = item.get("locations") or []
        location = locations[0].get("display") if locations else None
        jobs.append(
            RawJob(
                source="google",
                url=item.get("apply_url"),
                company="Google",
                title=item.get("title"),
                location=location,
                jd_text=html_to_text(item.get("description", "")),
                posted_at=parse_iso_datetime(item.get("publish_date")),
            )
        )
    return jobs


def fetch_google(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    jobs: list[RawJob] = []
    query = primary_search_term(search)  # invariant across pages
    for page_num in range(1, _MAX_PAGES + 1):
        resp = httpx.get(_SEARCH_URL, params={"q": query, "page": page_num}, timeout=30)
        resp.raise_for_status()
        batch = parse_jobs(resp.json())
        if not batch:
            break
        jobs.extend(batch)
        if limit is not None and len(jobs) >= limit:
            return jobs[:limit]
    return jobs
