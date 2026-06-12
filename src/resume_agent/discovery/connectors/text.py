import html

from bs4 import BeautifulSoup

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.search_config import SearchConfig


def html_to_text(raw: str) -> str:
    """Unescape HTML entities then strip tags to readable text."""
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _terms(search: SearchConfig) -> list[str]:
    return [t.strip().lower() for t in (*search.keywords, *search.titles) if t.strip()]


def filter_by_search(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Keep jobs whose title or JD text contains any configured term."""
    terms = _terms(search)
    if not terms:
        return jobs
    kept = []
    for job in jobs:
        haystack = f"{job.title or ''}\n{job.jd_text}".lower()
        if any(term in haystack for term in terms):
            kept.append(job)
    return kept
