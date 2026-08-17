"""Deterministic, browser-free single-job readers for every known ATS host.

``identify_host`` (detect.py) recognizes these hosts without any network call.
For each one there's a reader here that turns one already-fetched *static*
HTML page (plain httpx, never a browser) plus the resolved ``AtsTarget`` into
an ``ExtractedJob`` -- reusing the same parsing building blocks the board-level
connectors already rely on, so a single job's provenance is exactly as
reliable as a full-board pull.

**The ATS's own JSON API is tried first, the page's JSON-LD second.** A job
page shows more than its description body: location, workplace type,
employment type, department, and compensation live in a sidebar or top bar
that the ATS API exposes as dedicated fields. schema.org ``JobPosting`` markup
carries only a subset of those and many boards emit none of it, so preferring
JSON-LD (cheaper -- no extra request) silently dropped the very facts this
module exists to capture. The API result wins whenever it resolves; JSON-LD
fills any field the API left blank and takes over entirely when the API cannot
resolve the job.

Whichever source wins, the sidebar/top-bar facts are rendered as ``Label:
value`` lines prepended to ``jd_text`` -- the same shape ``ashby.parse_ashby``
already uses -- so the relevance gate, criteria extraction, and tailoring all
read them as part of the description.

A reader returns ``None`` -- never an ``ExtractedJob`` with an empty
``jd_text`` -- when it could not resolve the job at all. That is the contract
``service.job_from_url`` keys its LLM fallback on: an empty-but-present result
would silently suppress the fallback and fail the ingest.
"""

import json
import re
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.bamboohr import detail_url as bamboohr_detail_url
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget, workday_external_path
from resume_agent.discovery.connectors.greenhouse import (
    fetch_greenhouse_board_name,
    fetch_greenhouse_job,
    parse_greenhouse,
)
from resume_agent.discovery.connectors.lever import fetch_lever_posting, parse_lever
from resume_agent.discovery.connectors.personio import parse_personio
from resume_agent.discovery.connectors.personio import search_url as personio_search_url
from resume_agent.discovery.connectors.recruitee import offers_url, parse_recruitee
from resume_agent.discovery.connectors.smartrecruiters import (
    detail_url as sr_detail_url,
)
from resume_agent.discovery.connectors.text import html_to_markdown, jobposting_json_ld
from resume_agent.discovery.connectors.workable import (
    account_url as workable_account_url,
)
from resume_agent.discovery.connectors.workable import parse_workable
from resume_agent.discovery.connectors.workday import detail_company_name, fetch_job_detail
from resume_agent.discovery.url_ingest.greenhouse import read_greenhouse_posting
from resume_agent.discovery.url_ingest.models import ExtractedJob

Reader = Callable[[AtsTarget, str, str], ExtractedJob | None]

# Errors that mean "this ATS could not tell us about this job". A non-JSON body
# (a maintenance page, a bot interstitial, an HTML 404 served with status 200)
# raises ValueError out of ``.json()``, not httpx.HTTPError -- catching only the
# latter turned a routine bad response into a 500 on add-from-URL.
_API_ERRORS = (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError)


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


def _with_meta(lines: list[str], jd_text: str) -> str:
    """Prepend the sidebar/top-bar facts to a description body."""
    kept = [line for line in lines if line]
    if not kept:
        return jd_text
    return "\n".join(kept) + ("\n\n" + jd_text if jd_text else "")


def read_employer_hosted_greenhouse(html: str) -> ExtractedJob | None:
    """Read a Greenhouse-backed listing rendered on an employer's own site.

    Some employers keep their page-only sections outside both Greenhouse's job
    API and schema.org ``description``. Stripe identifies the underlying row as
    ``listing.greenhouseId`` in Next.js data while server-rendering the complete
    posting in semantic body blocks. Prefer those blocks so in-office, pay, and
    benefits sections are not reduced to the shorter JSON-LD/API description.
    """
    soup = BeautifulSoup(html, "html.parser")
    script = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if not isinstance(script, Tag):
        return None
    try:
        payload = json.loads(script.get_text())
        listing = payload["props"]["pageProps"]["listing"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(listing, dict) or not listing.get("greenhouseId"):
        return None

    nodes = soup.select(
        ".careers-detail-layout__main > .careers-listing-details__body, "
        ".careers-detail-layout__main > .careers-listing-closing"
    )
    body = "\n\n".join(html_to_markdown(str(node)) for node in nodes)
    if not body:
        content = listing.get("contentMarkdown")
        body = content.strip() if isinstance(content, str) else ""
    if not body:
        return None

    raw_location = listing.get("location")
    location = None
    if isinstance(raw_location, dict):
        location_parts = [raw_location.get("name"), raw_location.get("countryCode")]
        location = ", ".join(str(part) for part in location_parts if part) or None
        if raw_location.get("remote") and not location:
            location = "Remote"

    employment_type = listing.get("employmentType")
    meta = [
        f"Location: {location}" if location else "",
        f"Employment Type: {employment_type}"
        if isinstance(employment_type, str) and employment_type.strip()
        else "",
    ]
    scalars = _from_json_ld(html)
    return ExtractedJob(
        company=scalars.company if scalars is not None else None,
        title=listing.get("title") if isinstance(listing.get("title"), str) else None,
        location=location,
        jd_text=_with_meta(meta, body),
    )


def _api(call: Callable[[], ExtractedJob | None]) -> ExtractedJob | None:
    """Run an ATS API lookup, treating any failure as 'could not resolve'."""
    try:
        return call()
    except _API_ERRORS:
        return None


def _prefer(*candidates: ExtractedJob | None) -> ExtractedJob | None:
    """First candidate carrying a description wins; the rest fill its blanks.

    Ordered most-authoritative first. Only a description makes a candidate
    usable -- a result with company/title but no ``jd_text`` cannot become a
    job -- but its scalar fields are still worth harvesting into the winner.
    """
    usable = [candidate for candidate in candidates if candidate is not None]
    winner = next((candidate for candidate in usable if candidate.jd_text), None)
    if winner is None:
        return None
    gaps = {
        field: value
        for field in ("company", "title", "location")
        if getattr(winner, field) is None
        and (value := next((getattr(o, field) for o in usable if getattr(o, field)), None))
    }
    return winner.model_copy(update=gaps) if gaps else winner


# -- schema.org JobPosting ---------------------------------------------------

_JSON_LD_EMPLOYMENT_LABELS = {
    "FULL_TIME": "Full time",
    "PART_TIME": "Part time",
    "CONTRACTOR": "Contract",
    "TEMPORARY": "Temporary",
    "INTERN": "Internship",
    "VOLUNTEER": "Volunteer",
    "PER_DIEM": "Per diem",
    "OTHER": "Other",
}
_JSON_LD_PERIODS = {
    "HOUR": "per hour",
    "DAY": "per day",
    "WEEK": "per week",
    "MONTH": "per month",
    "YEAR": "per year",
}


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


def _names(value) -> list[str]:
    """Flatten a schema.org field that may be a string, an object, or a list of either."""
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def _amount(value) -> str | None:
    if isinstance(value, int | float):
        return f"{value:,.0f}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _json_ld_salary(posting: dict) -> str | None:
    """Render ``baseSalary`` (a MonetaryAmount) the way the page's pay band reads."""
    salary = posting.get("baseSalary") or posting.get("estimatedSalary")
    if isinstance(salary, list):
        salary = next((item for item in salary if isinstance(item, dict)), None)
    if not isinstance(salary, dict):
        return None
    value = salary.get("value")
    if not isinstance(value, dict):
        return _amount(value)
    low = _amount(value.get("minValue"))
    high = _amount(value.get("maxValue"))
    exact = _amount(value.get("value"))
    span = f"{low} - {high}" if low and high else (low or high or exact)
    if not span:
        return None
    currency = salary.get("currency") or value.get("currency")
    period = _JSON_LD_PERIODS.get(str(value.get("unitText") or "").upper())
    return " ".join(part for part in (currency, span, period) if part)


def _json_ld_meta_lines(posting: dict) -> list[str]:
    """The sidebar/top-bar facts schema.org markup carries beyond the body text.

    ``description`` alone loses the pay band, employment type, and remote
    status that a posting renders in its header -- fields the fit scorer and
    tailoring rely on. Labels match ``ashby._sidebar_lines`` so a job read
    through either path produces the same text shape.
    """
    lines = []
    if location := _json_ld_location(posting):
        lines.append(f"Location: {location}")

    remote = posting.get("jobLocationType") == "TELECOMMUTE"
    regions = _names(posting.get("applicantLocationRequirements"))
    if remote and regions:
        lines.append(f"Workplace Type: Remote ({', '.join(regions)})")
    elif remote:
        lines.append("Workplace Type: Remote")

    types = [
        _JSON_LD_EMPLOYMENT_LABELS.get(str(item).upper().replace("-", "_"), str(item))
        for item in _names(posting.get("employmentType"))
    ]
    if types:
        lines.append(f"Employment Type: {', '.join(types)}")

    if departments := _names(posting.get("occupationalCategory")):
        lines.append(f"Department: {', '.join(departments)}")

    if salary := _json_ld_salary(posting):
        lines.append(f"Compensation: {salary}")

    return lines


def _from_json_ld(html: str) -> ExtractedJob | None:
    """The page's own schema.org ``JobPosting`` markup, when present."""
    posting = jobposting_json_ld(html)
    if posting is None:
        return None
    organization = posting.get("hiringOrganization")
    company = organization.get("name") if isinstance(organization, dict) else None
    body = html_to_markdown(posting.get("description") or "")
    return ExtractedJob(
        company=company,
        title=posting.get("title"),
        location=_json_ld_location(posting),
        jd_text=_with_meta(_json_ld_meta_lines(posting), body),
    )


def with_json_ld_meta(extracted: ExtractedJob | None, html: str) -> ExtractedJob | None:
    """Enrich a body sourced elsewhere with the page's own schema.org facts.

    ``_prefer`` cannot do this: it merges only *scalar* fields, so a candidate
    that wins on ``jd_text`` keeps its own meta lines and every other
    candidate's are discarded. Two callers need the opposite -- the richer body
    plus the markup's sidebar facts:

    - **Greenhouse**, whose board API carries the description but none of the
      pay band, employment type, or workplace type an employer's posting page
      renders beside it (verified live: Stripe's job API returns
      ``location: {"name": "N/A"}`` and no compensation, while the page's
      JSON-LD carries Toronto/FULL_TIME/CAD 208,000-312,000).
    - **The LLM fallback on an unrecognized host**, which is instructed to drop
      "generic site chrome" and therefore discards the sidebar -- those facts
      reach it as bare, colon-less lines positioned *after* the apply button.

    Only labels the body does not already carry are added, so a reader that
    renders its own sidebar is unchanged. ``None`` passes through as ``None``:
    that is the "could not resolve" contract ``service.job_from_url`` keys its
    fallback on.
    """
    if extracted is None or not extracted.jd_text:
        return extracted
    posting = jobposting_json_ld(html)
    if posting is None:
        return extracted
    existing = extracted.jd_text
    lines = [
        line
        for line in _json_ld_meta_lines(posting)
        if line.split(":", 1)[0] + ":" not in existing
    ]
    update = {
        field: value
        for field in ("company", "title", "location")
        if getattr(extracted, field) is None
        and (value := getattr(_from_json_ld_scalars(posting), field))
    }
    if lines:
        update["jd_text"] = _with_meta(lines, existing)
    return extracted.model_copy(update=update) if update else extracted


def _from_json_ld_scalars(posting: dict) -> ExtractedJob:
    """The markup's scalar fields only -- no body, so it can never win a body."""
    organization = posting.get("hiringOrganization")
    return ExtractedJob(
        company=organization.get("name") if isinstance(organization, dict) else None,
        title=posting.get("title"),
        location=_json_ld_location(posting),
        jd_text="",
    )


# -- per-ATS API lookups -----------------------------------------------------


def _get_json(url: str, **kwargs) -> dict:
    resp = board.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _greenhouse_job_id(url: str) -> str | None:
    if gh_jid := parse_qs(urlsplit(url).query).get("gh_jid"):
        return gh_jid[0]
    return _segment_after(url, "jobs") or None


def _greenhouse_company_name(token: str) -> str:
    # The board slug (e.g. "hooli") is rarely the org's display name; resolve
    # it from the board endpoint so add-from-URL matches the company/title
    # dedupe key GreenhouseConnector produces from the same board.
    try:
        return fetch_greenhouse_board_name(token) or token
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return token


def _read_greenhouse(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        job_id = _greenhouse_job_id(url)
        if job_id is None or not target.token:
            return None
        item = fetch_greenhouse_job(target.token, job_id)
        rows = parse_greenhouse({"jobs": [item]}, _greenhouse_company_name(target.token))
        return _extracted_from_row(rows[0]) if rows else None

    return _prefer(_api(api), _from_json_ld(html), read_greenhouse_posting(html))


def _read_ashby(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        job_id = _last_segment(url)
        payload = fetch_ashby_board(target.token)
        item = next((job for job in payload.get("jobs", []) if job.get("id") == job_id), None)
        if item is None:
            return None
        return _extracted_from_row(parse_ashby({"jobs": [item]}, target.token)[0])

    return _prefer(_api(api), _from_json_ld(html))


def _read_lever(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        payload = fetch_lever_posting(target.token, _last_segment(url))
        rows = parse_lever([payload], target.token)
        return _extracted_from_row(rows[0]) if rows else None

    return _prefer(_api(api), _from_json_ld(html))


def _smartrecruiters_company(target: AtsTarget, url: str) -> str:
    # The oneclick-ui URL form nests the company deeper than the first path
    # segment detect.py reads, so the token would otherwise be "oneclick-ui".
    return _segment_after(url, "company") or target.token


def _smartrecruiters_posting_id(url: str) -> str | None:
    """The posting id from any of SmartRecruiters' three public URL shapes.

    ``/{company}/{id}-{slug}`` and ``/{company}/{id}`` put a numeric id first;
    ``/oneclick-ui/company/{co}/publication/{uuid}`` uses a dashed UUID that a
    naive split on "-" would truncate.
    """
    if publication := _segment_after(url, "publication"):
        return publication
    segments = _path_segments(url)
    if len(segments) < 2:
        return None
    candidate = segments[-1]
    leading_digits = re.match(r"^(\d+)", candidate)
    return leading_digits.group(1) if leading_digits else candidate or None


def _smartrecruiters_location(location: dict | None) -> str | None:
    if not location:
        return None
    parts = (location.get("city"), location.get("region"), location.get("country"))
    return ", ".join(part for part in parts if part) or None


def _smartrecruiters_meta(detail: dict) -> list[str]:
    """The facts SmartRecruiters renders above the description body."""
    lines = []
    if location := _smartrecruiters_location(detail.get("location")):
        remote = (detail.get("location") or {}).get("remote")
        lines.append(f"Location: {location}{' (Remote)' if remote else ''}")
    for label, key in (("Employment Type", "typeOfEmployment"), ("Experience Level", "experienceLevel")):
        if name := (detail.get(key) or {}).get("label"):
            lines.append(f"{label}: {name}")
    if department := (detail.get("department") or {}).get("label"):
        lines.append(f"Department: {department}")
    if industry := (detail.get("industry") or {}).get("label"):
        lines.append(f"Industry: {industry}")
    return lines


def _read_smartrecruiters(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        posting_id = _smartrecruiters_posting_id(url)
        if posting_id is None:
            return None
        company = _smartrecruiters_company(target, url)
        detail = _get_json(sr_detail_url(company, posting_id))
        sections = ((detail.get("jobAd") or {}).get("sections")) or {}
        names = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
        body = html_to_markdown(
            "\n".join((sections.get(name) or {}).get("text") or "" for name in names)
        )
        return ExtractedJob(
            company=(detail.get("company") or {}).get("name") or company,
            title=detail.get("name"),
            location=_smartrecruiters_location(detail.get("location")),
            jd_text=_with_meta(_smartrecruiters_meta(detail), body),
        )

    return _prefer(_api(api), _from_json_ld(html))


def _workable_shortcode(url: str) -> str | None:
    # Both "apply.workable.com/{company}/j/{code}" and the bare
    # "apply.workable.com/j/{code}" share the /j/ marker.
    return _segment_after(url, "j") or None


def _read_workable(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        shortcode = _workable_shortcode(url)
        if shortcode is None or not target.token:
            return None
        payload = _get_json(
            workable_account_url(target.token),
            params={"details": "true"},
            follow_redirects=True,
        )
        item = next(
            (job for job in payload.get("jobs") or [] if job.get("shortcode") == shortcode), None
        )
        if item is None:
            return None
        row = parse_workable({"name": payload.get("name"), "jobs": [item]}, target.token)[0]
        extracted = _extracted_from_row(row)
        meta = []
        if row.location:
            meta.append(f"Location: {row.location}")
        if employment := item.get("employment_type"):
            meta.append(f"Employment Type: {employment}")
        if department := item.get("department"):
            meta.append(f"Department: {department}")
        return extracted.model_copy(update={"jd_text": _with_meta(meta, extracted.jd_text)})

    return _prefer(_api(api), _from_json_ld(html))


def _read_personio(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        position_id = _segment_after(url, "job")
        if position_id is None:
            return None
        resp = board.get(
            personio_search_url(target.token, target.country), follow_redirects=True
        )
        resp.raise_for_status()
        rows = parse_personio(resp.text, target.token, target.country)
        match = next(
            (row for row in rows if row.url and _last_segment(row.url) == position_id), None
        )
        return _extracted_from_row(match) if match is not None else None

    return _prefer(_api(api), _from_json_ld(html))


def _recruitee_slug(url: str) -> str | None:
    return _segment_after(url, "o") or _last_segment(url)


def _read_recruitee(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        # Recruitee keeps the qualifications in a `requirements` field separate
        # from `description`; parse_recruitee concatenates both, so the public
        # offers feed carries a JD the page's JSON-LD `description` truncates.
        slug = _recruitee_slug(url)
        payload = _get_json(offers_url(target.token), follow_redirects=True)
        rows = parse_recruitee(payload, target.token)
        match = next(
            (row for row in rows if row.url and slug and _recruitee_slug(row.url) == slug), None
        )
        return _extracted_from_row(match) if match is not None else None

    return _prefer(_api(api), _from_json_ld(html))


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
    def api() -> ExtractedJob | None:
        opening_id = _segment_after(url, "careers")
        if opening_id is None:
            return None
        detail = _get_json(bamboohr_detail_url(target.token, opening_id))
        opening = ((detail.get("result") or {}).get("jobOpening")) or {}
        if not opening:
            return None
        location = _bamboohr_location(opening)
        meta = []
        if location:
            meta.append(f"Location: {location}")
        for label, key in (("Employment Type", "employmentStatusLabel"), ("Department", "departmentLabel")):
            if value := opening.get(key):
                meta.append(f"{label}: {value}")
        if pay := opening.get("compensation"):
            meta.append(f"Compensation: {pay}")
        return ExtractedJob(
            company=target.token,
            title=opening.get("jobOpeningName"),
            location=location,
            jd_text=_with_meta(meta, html_to_markdown(opening.get("description") or "")),
        )

    return _prefer(_api(api), _from_json_ld(html))


def _workday_meta(info: dict) -> list[str]:
    """Workday's header strip: locations, time type, req id, posted date."""
    lines = []
    location = info.get("location") or info.get("jobRequisitionLocation")
    if isinstance(location, dict):
        location = location.get("descriptor")
    if location:
        lines.append(f"Location: {location}")
    if additional := info.get("additionalLocations"):
        names = [
            item.get("descriptor") if isinstance(item, dict) else item for item in additional
        ]
        if joined := ", ".join(str(name) for name in names if name):
            lines.append(f"Additional Locations: {joined}")
    if remote := info.get("remoteType"):
        lines.append(f"Workplace Type: {remote}")
    if time_type := info.get("timeType"):
        lines.append(f"Employment Type: {time_type}")
    if job_family := info.get("jobFamily"):
        lines.append(f"Department: {job_family}")
    if req_id := info.get("jobReqId"):
        lines.append(f"Requisition ID: {req_id}")
    if posted := info.get("postedOn"):
        lines.append(f"Posted: {posted}")
    return lines


def _read_workday(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    def api() -> ExtractedJob | None:
        external_path = workday_external_path(target, url)
        if external_path is None:
            return None
        detail = fetch_job_detail(target, external_path)
        info = detail.get("jobPostingInfo") or {}
        if not info:
            return None
        location = info.get("location")
        return ExtractedJob(
            # Prefer the payload's own company name; target.tenant is a URL slug
            # ("generalmotors"), and a slug as the company breaks dedup against
            # the same requisition ingested by the board connector. The name is
            # read from the whole payload, not just jobPostingInfo -- Workday
            # now serves companyName as null and carries the real name at the
            # top level (see workday.detail_company_name).
            company=detail_company_name(detail) or target.tenant,
            title=info.get("title"),
            location=location if isinstance(location, str) else None,
            jd_text=_with_meta(
                _workday_meta(info), html_to_markdown(info.get("jobDescription") or "")
            ),
        )

    return _prefer(_api(api), _from_json_ld(html))


def _json_ld_only(target: AtsTarget, url: str, html: str) -> ExtractedJob | None:
    """Boards with no usable public single-job API: the page's own markup only."""
    return _prefer(_from_json_ld(html))


ATS_READERS: dict[str, Reader] = {
    "greenhouse": _read_greenhouse,
    "ashby": _read_ashby,
    "lever": _read_lever,
    "smartrecruiters": _read_smartrecruiters,
    "workable": _read_workable,
    "personio": _read_personio,
    "bamboohr": _read_bamboohr,
    "recruitee": _read_recruitee,
    "breezy": _json_ld_only,
    "jazzhr": _json_ld_only,
    "workday": _read_workday,
}
