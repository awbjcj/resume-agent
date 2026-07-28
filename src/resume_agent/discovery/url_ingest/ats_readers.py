"""Deterministic, browser-free single-job readers for every known ATS host.

``identify_host`` (detect.py) recognizes these hosts without any network call.
For each one there's a reader here that turns one already-fetched *static*
HTML page (plain httpx, never a browser) plus the resolved ``AtsTarget`` into
an ``ExtractedJob`` -- reusing the same parsing building blocks the board-level
connectors already rely on, so a single job's provenance is exactly as
reliable as a full-board pull.

Every reader tries the page's own JSON-LD ``JobPosting`` markup first (cheap,
no extra request) and falls back to the ATS's own JSON API, keyed by an id
parsed straight out of the pasted URL, when JSON-LD is absent or the page
didn't carry a job description. A reader returns ``None`` only when it could
not identify or fetch the specific job at all -- the caller then falls back to
the LLM on the same static HTML, still without ever touching a browser.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.bamboohr import detail_url as bamboohr_detail_url
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget, workday_external_path
from resume_agent.discovery.connectors.lever import fetch_lever_posting, parse_lever
from resume_agent.discovery.connectors.personio import parse_personio
from resume_agent.discovery.connectors.personio import search_url as personio_search_url
from resume_agent.discovery.connectors.smartrecruiters import (
    detail_url as sr_detail_url,
)
from resume_agent.discovery.connectors.text import html_to_markdown, jobposting_json_ld
from resume_agent.discovery.connectors.workable import (
    account_url as workable_account_url,
)
from resume_agent.discovery.connectors.workable import parse_workable
from resume_agent.discovery.connectors.workday import cxs_detail_url
from resume_agent.discovery.url_ingest.greenhouse import read_greenhouse_posting
from resume_agent.discovery.url_ingest.models import ExtractedJob

Reader = Callable[[AtsTarget, str, str], ExtractedJob | None]


def _extracted_from_row(row: RawJob) -> ExtractedJob:
    return ExtractedJob(company=row.company, title=row.title, location=row.location, jd_text=row.jd_text)


def _path_segments(url: str) -> list[str]:
    return [segment for segment in urlsplit(url).path.split("/") if segment]


def _last_segment(url: str) -> str:
    segments = _path_segments(url)
    return segments[-1] if segments else ""


def _segment_after(url: str, marker: str) -> str | None:
    segments = _path_segments(url)
    if marker not in segments:
        return None
    idx = segments.index(marker)
    return segments[idx + 1] if idx + 1 < len(segments) else None


def _json_ld_location(posting: dict) -> str | None:
    if posting.get("jobLocationType") == "TELECOMMUTE":
        return "Remote"
    job_location = posting.get("jobLocation")
    candidates = job_location if isinstance(job_location, list) else [job_location]
    for location in candidates:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, str) and address.strip():
            return address.strip()
        if not isinstance(address, dict):
            continue
        parts = (
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        )
        joined = ", ".join(part for part in parts if part)
        if joined:
            return joined
    return None


def _from_json_ld(html: str) -> ExtractedJob | None:
    """The page's own schema.org ``JobPosting`` markup, when present."""
    posting = jobposting_json_ld(html)
    if posting is None:
        return None
    organization = posting.get("hiringOrganization")
    company = organization.get("name") if isinstance(organization, dict) else None
    return ExtractedJob(
        company=company,
        title=posting.get("title"),
        location=_json_ld_location(posting),
        jd_text=html_to_markdown(posting.get("description") or ""),
    )


def _read_ashby(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    job_id = _last_segment(url)
    try:
        payload = fetch_ashby_board(target.token)
    except httpx.HTTPError:
        return extracted
    item = next((job for job in payload.get("jobs", []) if job.get("id") == job_id), None)
    if item is None:
        return extracted
    return _extracted_from_row(parse_ashby({"jobs": [item]}, target.token)[0])


def _read_lever(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    posting_id = _last_segment(url)
    try:
        payload = fetch_lever_posting(target.token, posting_id)
    except httpx.HTTPError:
        return extracted
    return _extracted_from_row(parse_lever([payload], target.token)[0])


def _smartrecruiters_posting_id(url: str) -> str | None:
    segments = _path_segments(url)
    if len(segments) < 2:
        return None
    return segments[1].split("-", 1)[0]


def _smartrecruiters_location(location: dict | None) -> str | None:
    if not location:
        return None
    parts = (location.get("city"), location.get("region"), location.get("country"))
    return ", ".join(part for part in parts if part) or None


def _read_smartrecruiters(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    posting_id = _smartrecruiters_posting_id(url)
    if posting_id is None:
        return extracted
    try:
        resp = httpx.get(sr_detail_url(target.token, posting_id), timeout=30)
        resp.raise_for_status()
        detail = resp.json()
    except httpx.HTTPError:
        return extracted
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    names = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
    jd_text = html_to_markdown(
        "\n".join((sections.get(name) or {}).get("text") or "" for name in names)
    )
    company = (detail.get("company") or {}).get("name") or target.token
    return ExtractedJob(
        company=company,
        title=detail.get("name"),
        location=_smartrecruiters_location(detail.get("location")),
        jd_text=jd_text,
    )


def _read_workable(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    shortcode = _segment_after(url, "j")
    if shortcode is None:
        return extracted
    try:
        resp = httpx.get(
            workable_account_url(target.token),
            params={"details": "true"},
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError:
        return extracted
    item = next(
        (job for job in payload.get("jobs") or [] if job.get("shortcode") == shortcode), None
    )
    if item is None:
        return extracted
    row = parse_workable({"name": payload.get("name"), "jobs": [item]}, target.token)[0]
    return _extracted_from_row(row)


def _read_personio(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    position_id = _segment_after(url, "job")
    if position_id is None:
        return extracted
    try:
        resp = httpx.get(
            personio_search_url(target.token, target.country), timeout=30, follow_redirects=True
        )
        resp.raise_for_status()
        rows = parse_personio(resp.text, target.token, target.country)
    except (httpx.HTTPError, ValueError):
        return extracted
    match = next(
        (row for row in rows if row.url and _last_segment(row.url) == position_id), None
    )
    return _extracted_from_row(match) if match is not None else extracted


def _bamboohr_location(opening: dict) -> str | None:
    location = opening.get("atsLocation") or opening.get("location") or {}
    parts = (
        location.get("city"),
        location.get("state") or location.get("province"),
        location.get("country"),
    )
    result = ", ".join(part for part in parts if part)
    return result or ("Remote" if opening.get("isRemote") else None)


def _read_bamboohr(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    opening_id = _segment_after(url, "careers")
    if opening_id is None:
        return extracted
    try:
        resp = httpx.get(bamboohr_detail_url(target.token, opening_id), timeout=30)
        resp.raise_for_status()
        opening = ((resp.json().get("result") or {}).get("jobOpening")) or {}
    except httpx.HTTPError:
        return extracted
    if not opening:
        return extracted
    return ExtractedJob(
        company=target.token,
        title=opening.get("jobOpeningName"),
        location=_bamboohr_location(opening),
        jd_text=html_to_markdown(opening.get("description") or ""),
    )


def _read_workday(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    extracted = _from_json_ld(html)
    if extracted is not None and extracted.jd_text:
        return extracted
    external_path = workday_external_path(target, url)
    if external_path is None:
        return extracted
    try:
        resp = httpx.get(cxs_detail_url(target, external_path), timeout=30)
        resp.raise_for_status()
        info = resp.json().get("jobPostingInfo") or {}
    except httpx.HTTPError:
        return extracted
    if not info:
        return extracted
    return ExtractedJob(
        company=target.tenant,
        title=info.get("title"),
        location=info.get("location"),
        jd_text=html_to_markdown(info.get("jobDescription") or ""),
    )


def _read_greenhouse(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    return read_greenhouse_posting(html)


ATS_READERS: dict[str, Reader] = {
    "greenhouse": _read_greenhouse,
    "ashby": _read_ashby,
    "lever": _read_lever,
    "smartrecruiters": _read_smartrecruiters,
    "workable": _read_workable,
    "personio": _read_personio,
    "bamboohr": _read_bamboohr,
    "recruitee": lambda target, url, html: _from_json_ld(html),
    "breezy": lambda target, url, html: _from_json_ld(html),
    "jazzhr": lambda target, url, html: _from_json_ld(html),
    "workday": _read_workday,
}
