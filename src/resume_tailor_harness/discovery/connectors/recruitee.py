from resume_tailor_harness.discovery.connectors import http as board

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen, provenance_for
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.text import (
    html_to_markdown,
    join_locations,
    with_meta_lines,
)
from resume_tailor_harness.discovery.search_config import SearchConfig


def offers_url(token: str) -> str:
    return f"https://{token}.recruitee.com/api/offers/"


def _translated(item: dict, field: str):
    if value := item.get(field):
        return value
    for translation in (item.get("translations") or {}).values():
        if value := translation.get(field):
            return value
    return None


def _address(source: dict) -> str | None:
    """One "City, Region, Country" string from Recruitee's structured fields."""
    parts = (
        source.get("city"),
        source.get("state_name") or source.get("state"),
        source.get("country") or source.get("country_code"),
    )
    return (
        ", ".join(part for part in parts if isinstance(part, str) and part.strip())
        or None
    )


def _location(item: dict) -> str | None:
    """The posting's real place, not the label the employer typed.

    ``location`` is free text and is very often a *status* rather than a place
    -- "Remote job" on 5 of 6 postings on one live board -- which resolves to
    nothing at all, so those rows reached the board with no city, region or
    country while the payload carried all three. The structured fields (and
    the ``locations`` array, which is what makes a multi-office posting more
    than one place) are authoritative; ``location`` is the fallback for a
    posting that fills in nothing else.
    """
    addresses = [
        _address(entry)
        for entry in item.get("locations") or []
        if isinstance(entry, dict)
    ]
    return join_locations([*addresses, _address(item)]) or item.get("location")


def _sidebar_lines(item: dict) -> list[str]:
    """The facts a Recruitee posting shows beside its body.

    Employment type, experience, education, department and the pay band live
    in dedicated fields rather than in ``description``/``requirements``, so
    mapping only the body dropped every one of them.
    """
    lines: list[str] = []
    if location := _location(item):
        lines.append(f"Location: {location}")
    if workplace := _workplace_type(item):
        lines.append(f"Workplace Type: {workplace}")
    for label, key in (
        ("Employment Type", "employment_type_code"),
        ("Experience Level", "experience_code"),
        ("Education", "education_code"),
    ):
        if value := item.get(key):
            lines.append(f"{label}: {str(value).replace('_', ' ').capitalize()}")
    if department := item.get("department"):
        lines.append(f"Department: {department}")
    if salary := _salary(item):
        lines.append(f"Compensation: {salary}")
    return lines


def _workplace_type(item: dict) -> str | None:
    """Recruitee models the three placements as independent booleans."""
    kinds = [
        name
        for name, flag in (
            ("Remote", "remote"),
            ("Hybrid", "hybrid"),
            ("On-site", "on_site"),
        )
        if item.get(flag)
    ]
    return ", ".join(kinds) or None


def _salary(item: dict) -> str | None:
    salary = item.get("salary")
    if not isinstance(salary, dict):
        return None
    low, high = salary.get("min"), salary.get("max")
    span = (
        f"{low:,.0f} - {high:,.0f}"
        if isinstance(low, int | float) and isinstance(high, int | float)
        else next(
            (f"{v:,.0f}" for v in (low, high) if isinstance(v, int | float)), None
        )
    )
    if not span:
        return None
    period = salary.get("period")
    return " ".join(
        str(part)
        for part in (salary.get("currency"), span, period and f"per {period}")
        if part
    )


def parse_recruitee(payload: dict, token: str) -> list[RawJob]:
    rows = []
    for item in payload.get("offers") or []:
        description = _translated(item, "description") or ""
        requirements = _translated(item, "requirements") or ""
        provider_company = item.get("company_name")
        rows.append(
            RawJob(
                source="recruitee",
                url=item.get("careers_apply_url") or item.get("careers_url"),
                company=provider_company or token,
                title=_translated(item, "title"),
                location=_location(item),
                jd_text=with_meta_lines(
                    _sidebar_lines(item),
                    html_to_markdown(f"{description}\n{requirements}"),
                ),
                posted_at=parse_iso_datetime(
                    str(item.get("published_at") or "").replace(" UTC", "+00:00")
                ),
                company_provenance=provenance_for(provider_company),
            )
        )
    return rows


def fetch_recruitee(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(offers_url(target.token))
    response.raise_for_status()
    return parse_recruitee(response.json(), target.token)
