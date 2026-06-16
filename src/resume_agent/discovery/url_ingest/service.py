from urllib.parse import urlsplit

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.url_ingest.fetch import fetch_page
from resume_agent.discovery.url_ingest.greenhouse import parse_greenhouse
from resume_agent.discovery.url_ingest.llm import extract_fields, html_to_text
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import Runner


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def job_from_url(url: str, *, agent: Runner, allow_browser: bool = True) -> RawJob | None:
    """Fetch a posting URL, route to the right extractor, and build a RawJob.

    Returns None when no job-description text could be extracted.
    """
    page = fetch_page(url, allow_browser=allow_browser)
    host = urlsplit(page.final_url).netloc.lower()
    if _matches(host, "linkedin.com"):
        meta = parse_detail_meta(page.html)
        extracted = ExtractedJob(
            title=meta.title,
            company=meta.company,
            location=meta.location,
            jd_text=parse_job_detail(page.html),
        )
    elif _matches(host, "greenhouse.io"):
        extracted = parse_greenhouse(page.html)
    else:
        extracted = extract_fields(html_to_text(page.html), agent)
    jd_text = (extracted.jd_text or "").strip()
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
