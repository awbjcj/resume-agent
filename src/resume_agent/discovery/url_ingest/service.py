from typing import Callable
from urllib.parse import urlsplit

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.text import clean_job_description_text
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.url_ingest.fetch import fetch_page, is_linkedin
from resume_agent.discovery.url_ingest.greenhouse import read_greenhouse_posting
from resume_agent.discovery.url_ingest.llm import extract_fields, html_to_text
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import Runner


def read_linkedin_posting(html: str) -> ExtractedJob:
    """Read a single LinkedIn posting page into structured fields."""
    meta = parse_detail_meta(html)
    return ExtractedJob(
        title=meta.title,
        company=meta.company,
        location=meta.location,
        jd_text=parse_job_detail(html),
    )


# ats -> reader(html) -> ExtractedJob. A single posting page per ATS, keyed by the
# identity detect.py resolves. Mirrors connectors._BACKENDS; LinkedIn is handled
# separately because it is a scraper target, not an ATS detect_ats knows.
_READERS: dict[str, Callable[[str], ExtractedJob]] = {
    "greenhouse": read_greenhouse_posting,
}


def job_from_url(url: str, *, agent: Runner, allow_browser: bool = True) -> RawJob | None:
    """Fetch a posting URL, route to the right reader, and build a RawJob.

    Returns None when no job-description text could be extracted.
    """
    page = fetch_page(url, allow_browser=allow_browser)
    host = urlsplit(page.final_url).netloc.lower()
    if is_linkedin(host):
        extracted = read_linkedin_posting(page.html)
    else:
        target = identify_host(page.final_url)
        reader = _READERS.get(target.ats) if target else None
        extracted = reader(page.html) if reader else extract_fields(html_to_text(page.html), agent)
    jd_text = clean_job_description_text(extracted.jd_text or "")
    if not jd_text:
        return None
    return RawJob(
        source="url",
        url=url,
        company=extracted.company,
        title=extracted.title,
        location=extracted.location,
        jd_text=jd_text,
    )
