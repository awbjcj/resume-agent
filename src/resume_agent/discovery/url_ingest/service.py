from urllib.parse import urlsplit

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.text import clean_job_description_text
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.url_ingest.ats_readers import ATS_READERS
from resume_agent.discovery.url_ingest.fetch import (
    fetch_page,
    fetch_static,
    is_linkedin,
)
from resume_agent.discovery.url_ingest.llm import extract_fields, html_to_text
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import Runner


def read_linkedin_posting(html: str) -> ExtractedJob:
    """Read a single posting page into structured fields."""
    meta = parse_detail_meta(html)
    return ExtractedJob(
        title=meta.title,
        company=meta.company,
        location=meta.location,
        jd_text=parse_job_detail(html),
    )


def job_from_url(url: str, *, agent: Runner, allow_browser: bool = True) -> RawJob | None:
    """Fetch a posting URL, route to the right reader, and build a RawJob.

    A host ``identify_host`` recognizes as a known ATS is fetched *statically*
    (plain httpx, never a browser) and handed to its deterministic reader in
    ``ats_readers.ATS_READERS`` -- these boards have their own reliable JSON
    APIs (or JSON-LD on the page itself), so there is no need to ever render
    them. Only an unrecognized host falls back to the JS-shell-aware
    ``fetch_page`` (browser render when needed) plus the LLM. Returns None
    when no job-description text could be extracted.
    """
    host = urlsplit(url).netloc.lower()
    if is_linkedin(host):
        page = fetch_page(url, allow_browser=allow_browser)
        extracted = read_linkedin_posting(page.html)
    else:
        static_page = fetch_static(url)
        target = identify_host(static_page.final_url)
        if target is None:
            extracted = None
        else:
            reader = ATS_READERS.get(target.ats)
            extracted = reader(target, static_page.final_url, static_page.html) if reader else None
        if extracted is None:
            if target is not None:
                # Known ATS (or its reader couldn't resolve this specific job) --
                # still never touch the browser; fall back to the LLM on the
                # already-fetched static HTML.
                extracted = extract_fields(html_to_text(static_page.html), agent)
            else:
                page = fetch_page(url, allow_browser=allow_browser)
                extracted = extract_fields(html_to_text(page.html), agent)
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
