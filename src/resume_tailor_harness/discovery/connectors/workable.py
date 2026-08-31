from resume_tailor_harness.discovery.connectors import http as board

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen, provenance_for
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.text import html_to_markdown, with_meta_lines
from resume_tailor_harness.discovery.search_config import SearchConfig


def account_url(account: str) -> str:
    # Workable relocated the public account feed off www.workable.com/api/accounts
    # (which now 302-redirects) to the apply.workable.com widget API.
    return f"https://apply.workable.com/api/v1/widget/accounts/{account}"


def _location(item: dict) -> str | None:
    return (
        ", ".join(
            filter(None, (item.get("city"), item.get("state"), item.get("country")))
        )
        or None
    )


def _sidebar_lines(item: dict) -> list[str]:
    """The facts a Workable posting shows above its body.

    ``details=true`` returns employment type, department, industry, and the
    required experience and education as dedicated fields, plus a
    ``telecommuting`` flag that is the only place the remote policy is stated.
    Mapping the three description sections alone dropped all of them.
    """
    lines: list[str] = []
    if location := _location(item):
        lines.append(f"Location: {location}")
    if item.get("telecommuting"):
        lines.append("Workplace Type: Remote")
    for label, key in (
        ("Employment Type", "employment_type"),
        ("Experience Level", "experience"),
        ("Education", "education"),
        ("Department", "department"),
        ("Function", "function"),
        ("Industry", "industry"),
    ):
        if value := item.get(key):
            lines.append(f"{label}: {value}")
    return lines


def _jd_html(item: dict) -> str:
    """Workable splits a posting across three sibling fields; keep all of them.

    ``details=true`` returns ``requirements`` and ``benefits`` alongside
    ``description``. Dropping them loses the entire qualifications block --
    exactly the skill-bearing text the relevance gate and tailoring read.
    """
    sections = (
        item.get("description"),
        item.get("requirements"),
        item.get("benefits"),
    )
    return "\n".join(section for section in sections if section)


def parse_workable(payload: dict, account: str) -> list[RawJob]:
    provider_company = payload.get("name")
    company = provider_company or account
    return [
        RawJob(
            source="workable",
            url=item.get("application_url") or item.get("url"),
            company=company,
            title=item.get("title"),
            location=_location(item),
            jd_text=with_meta_lines(
                _sidebar_lines(item), html_to_markdown(_jd_html(item))
            ),
            posted_at=parse_iso_datetime(item.get("published_on")),
            company_provenance=provenance_for(provider_company),
        )
        for item in payload.get("jobs") or []
    ]


def fetch_workable(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(
        account_url(target.token),
        params={"details": "true"},
        follow_redirects=True,
    )
    response.raise_for_status()
    return parse_workable(response.json(), target.token)
