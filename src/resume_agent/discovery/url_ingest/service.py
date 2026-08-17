from urllib.parse import urlsplit

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import SINGLETON_ATS, identify_host
from resume_agent.discovery.connectors.text import clean_job_description_text
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.url_ingest.ats_readers import (
    ATS_READERS,
    read_employer_hosted_greenhouse,
    with_json_ld_meta,
)
from resume_agent.discovery.url_ingest.fetch import (
    fetch_page,
    fetch_static,
    is_linkedin,
    upgrade_if_shell,
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
    them, and the LLM fallback reads the same static HTML.

    Two kinds of host are exempt and may still be rendered: an unrecognized
    one, and a ``SINGLETON_ATS`` portal (Tesla, Google Careers), which is
    recognized by host but builds its listings in JavaScript -- static HTML
    holds nothing for either a reader or the LLM to read. Both reuse the
    already-fetched page rather than issuing a second request for it.

    Whichever branch produces the body, the page's own schema.org ``JobPosting``
    markup then fills in the sidebar facts it did not carry
    (``with_json_ld_meta``). That is what an employer-hosted posting needs: it
    is not a detectable ATS, so it falls to the LLM, which is instructed to drop
    site chrome and therefore discards the location/employment-type/pay strip.

    Returns None when no job-description text could be extracted.
    """
    host = urlsplit(url).netloc.lower()
    if is_linkedin(host):
        page = fetch_page(url, allow_browser=allow_browser)
        extracted = read_linkedin_posting(page.html)
    else:
        static_page = fetch_static(url)
        # Route on the post-redirect URL: a tracking or shortened link only
        # reveals the real host after the fetch.
        if is_linkedin(urlsplit(static_page.final_url).netloc.lower()):
            page = fetch_page(static_page.final_url, allow_browser=allow_browser)
            extracted = read_linkedin_posting(page.html)
        else:
            target = identify_host(static_page.final_url)
            extracted = read_employer_hosted_greenhouse(static_page.html)
            if extracted is None and target is not None:
                reader = ATS_READERS.get(target.ats)
                if reader is not None:
                    extracted = reader(target, static_page.final_url, static_page.html)
            if extracted is not None:
                extracted = with_json_ld_meta(extracted, static_page.html)
            else:
                if target is not None and target.ats not in SINGLETON_ATS:
                    page = static_page
                else:
                    page = upgrade_if_shell(static_page, allow_browser=allow_browser)
                extracted = with_json_ld_meta(
                    extract_fields(html_to_text(page.html), agent), page.html
                )
    if extracted is None:
        return None
    jd_text = clean_job_description_text(extracted.jd_text)
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
