
from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig


def offers_url(token: str) -> str:
    return f"https://{token}.recruitee.com/api/offers/"


def _translated(item: dict, field: str):
    if value := item.get(field):
        return value
    for translation in (item.get("translations") or {}).values():
        if value := translation.get(field):
            return value
    return None


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
                location=item.get("location")
                or item.get("city")
                or item.get("country_code"),
                jd_text=html_to_markdown(f"{description}\n{requirements}"),
                posted_at=parse_iso_datetime(
                    str(item.get("published_at") or "").replace(" UTC", "+00:00")
                ),
                company_provenance="provider" if provider_company else "token",
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
