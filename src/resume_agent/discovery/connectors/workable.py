
from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig


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
    company = payload.get("name") or account
    return [
        RawJob(
            source="workable",
            url=item.get("application_url") or item.get("url"),
            company=company,
            title=item.get("title"),
            location=_location(item),
            jd_text=html_to_markdown(_jd_html(item)),
            posted_at=parse_iso_datetime(item.get("published_on")),
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
