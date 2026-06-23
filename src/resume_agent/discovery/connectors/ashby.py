import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.text import html_to_markdown

_BASE = "https://api.ashbyhq.com/posting-api/job-board"


def parse_ashby(payload: dict, company: str) -> list[RawJob]:
    """Map an Ashby posting-api jobs payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        jd_text = item.get("descriptionPlain") or html_to_markdown(item.get("descriptionHtml", ""))
        jobs.append(
            RawJob(
                source="ashby",
                url=item.get("jobUrl"),
                company=company,
                title=item.get("title"),
                location=item.get("location"),
                jd_text=jd_text,
                posted_at=parse_iso_datetime(item.get("publishedAt")),
            )
        )
    return jobs


def fetch_ashby_board(token: str) -> dict:
    """GET an Ashby job board's postings payload."""
    resp = httpx.get(f"{_BASE}/{token}", timeout=30)
    resp.raise_for_status()
    return resp.json()
