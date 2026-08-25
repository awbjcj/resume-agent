import json


from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen, provenance_for
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import (
    html_to_markdown,
    join_locations,
    with_meta_lines,
)
from resume_agent.discovery.search_config import SearchConfig


def search_url(token: str, country: str = "com") -> str:
    # Personio's legacy /xml feed is gone for companies on the new careers
    # platform (bare 404); /search.json is the universal JSON endpoint and
    # serves the full job description inline, so no per-job detail fetch.
    return f"https://{token}.jobs.personio.{country}/search.json?language=en"


def job_url(token: str, country: str, position_id: str) -> str:
    return f"https://{token}.jobs.personio.{country}/job/{position_id}"


def _offices(position: dict) -> list[str]:
    """Every office, from the array rather than the joined scalar.

    Personio's ``office`` scalar joins several offices with a bare comma and
    no space ("Madrid,Madrid (Remote)"), which reads to the taxonomy as one
    "City, Region" pair and misparses; 7 of 9 postings on one live board carry
    more than one office. The ``offices`` array is the same data, already
    split.
    """
    offices = [
        office.strip()
        for office in position.get("offices") or []
        if isinstance(office, str) and office.strip()
    ]
    return offices or [str(position.get("office") or "").strip()]


def _sidebar_lines(position: dict) -> list[str]:
    """The facts a Personio posting lists above its body.

    Employment type, seniority, schedule and department are dedicated fields
    in ``search.json``; mapping only ``description`` dropped all four.
    """
    lines: list[str] = []
    if location := join_locations(_offices(position)):
        lines.append(f"Location: {location}")
    for label, key in (
        ("Employment Type", "employment_type"),
        ("Schedule", "schedule"),
        ("Experience Level", "seniority"),
        ("Department", "department"),
    ):
        if value := position.get(key):
            lines.append(f"{label}: {value}")
    return lines


def parse_personio(payload: str, token: str, country: str = "com") -> list[RawJob]:
    positions = json.loads(payload)
    rows = []
    for position in positions:
        position_id = position.get("id")
        provider_company = position.get("subcompany")
        rows.append(
            RawJob(
                source="personio",
                url=job_url(token, country, str(position_id))
                if position_id is not None
                else None,
                company=provider_company or token,
                title=position.get("name"),
                location=join_locations(_offices(position)),
                jd_text=with_meta_lines(
                    _sidebar_lines(position),
                    html_to_markdown(position.get("description") or ""),
                ),
                posted_at=None,
                company_provenance=provenance_for(provider_company),
            )
        )
    return rows


def fetch_personio(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(
        search_url(target.token, target.country), follow_redirects=True
    )
    response.raise_for_status()
    return parse_personio(response.text, target.token, target.country)
