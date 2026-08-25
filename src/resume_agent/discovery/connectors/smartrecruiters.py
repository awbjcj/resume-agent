from dataclasses import dataclass


from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen, provenance_for
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import (
    html_to_markdown,
    primary_search_term,
    with_meta_lines,
)
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.smartrecruiters.com/v1/companies"
_PAGE_SIZE = 100
_MAX_OFFSET = 1000


@dataclass
class SmartRecruitersRow(RawJob):
    posting_id: str = ""


def postings_url(company: str) -> str:
    return f"{_BASE}/{company}/postings"


def detail_url(company: str, posting_id: str) -> str:
    return f"{postings_url(company)}/{posting_id}"


def list_params(search: SearchConfig, offset: int) -> dict[str, str | int]:
    params: dict[str, str | int] = {"limit": _PAGE_SIZE, "offset": offset}
    if term := primary_search_term(search):
        params["q"] = term
    return params


def smartrecruiters_location(location: dict | None) -> str | None:
    """The posting's location, preferring the provider's own rendered form.

    SmartRecruiters ships a ready-made ``fullLocation`` ("Colombo, Western
    Province, Sri Lanka") alongside the parts, and it spells the country out
    where ``country`` is a lowercase alpha-2 code ("lk"). Joining the parts
    ourselves therefore produced a country the taxonomy had to re-resolve from
    an abbreviation, so the field is used as given and the join is kept only as
    a fallback — with the code upper-cased, since that is how a country code
    renders everywhere else.
    """
    if not location:
        return None
    if full := (location.get("fullLocation") or "").strip():
        return full
    country = (location.get("country") or "").strip()
    parts = (location.get("city"), location.get("region"), country.upper() or None)
    return ", ".join(part for part in parts if part) or None


def parse_postings(payload: dict, company: str) -> list[SmartRecruitersRow]:
    rows = []
    for item in payload.get("content") or []:
        posting_id = str(item.get("id") or "")
        provider_company = (item.get("company") or {}).get("name")
        rows.append(
            SmartRecruitersRow(
                source="smartrecruiters",
                url=(
                    f"https://jobs.smartrecruiters.com/{company}/{posting_id}"
                    if posting_id
                    else None
                ),
                company=provider_company or company,
                title=item.get("name"),
                location=smartrecruiters_location(item.get("location")),
                jd_text="",
                posted_at=parse_iso_datetime(item.get("releasedDate")),
                posting_id=posting_id,
                company_provenance=provenance_for(provider_company),
            )
        )
    return rows


_META_FIELDS = (
    ("Employment Type", "typeOfEmployment"),
    ("Experience Level", "experienceLevel"),
    ("Department", "department"),
    ("Industry", "industry"),
)


def smartrecruiters_meta_lines(detail: dict) -> list[str]:
    """The facts SmartRecruiters renders above the description body.

    These live in dedicated API fields, never inside the description sections,
    so a connector that maps only the body drops them -- the same gap
    `parse_greenhouse` and `parse_lever` were fixed for.
    """
    lines = []
    if location := smartrecruiters_location(detail.get("location")):
        remote = (detail.get("location") or {}).get("remote")
        lines.append(f"Location: {location}{' (Remote)' if remote else ''}")
    for label, key in _META_FIELDS:
        if name := (detail.get(key) or {}).get("label"):
            lines.append(f"{label}: {name}")
    return lines


def apply_detail(row: SmartRecruitersRow, detail: dict) -> None:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    names = (
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    )
    body = html_to_markdown(
        "\n".join((sections.get(name) or {}).get("text") or "" for name in names)
    )
    row.jd_text = with_meta_lines(smartrecruiters_meta_lines(detail), body)
    row.url = detail.get("applyUrl") or detail.get("postingUrl") or row.url


def _list_pages(target: AtsTarget, search: SearchConfig):
    for offset in range(0, _MAX_OFFSET + 1, _PAGE_SIZE):
        response = board.get(
            postings_url(target.token), params=list_params(search, offset)
        )
        response.raise_for_status()
        payload = response.json()
        rows = parse_postings(payload, target.token)
        yield from rows
        total = payload.get("totalFound")
        if not rows or isinstance(total, int) and offset + _PAGE_SIZE >= total:
            break


def _fetch_detail(target: AtsTarget, row: SmartRecruitersRow) -> dict | None:
    if not row.posting_id:
        return None
    response = board.get(detail_url(target.token, row.posting_id))
    response.raise_for_status()
    return response.json()


def fetch_smartrecruiters(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    return harvest_detailed(
        _list_pages(target, search),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
