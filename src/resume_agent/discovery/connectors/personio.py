import json

import httpx

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig


def search_url(token: str, country: str = "com") -> str:
    # Personio's legacy /xml feed is gone for companies on the new careers
    # platform (bare 404); /search.json is the universal JSON endpoint and
    # serves the full job description inline, so no per-job detail fetch.
    return f"https://{token}.jobs.personio.{country}/search.json?language=en"


def job_url(token: str, country: str, position_id: str) -> str:
    return f"https://{token}.jobs.personio.{country}/job/{position_id}"


def parse_personio(payload: str, token: str, country: str = "com") -> list[RawJob]:
    positions = json.loads(payload)
    rows = []
    for position in positions:
        position_id = position.get("id")
        rows.append(
            RawJob(
                source="personio",
                url=job_url(token, country, str(position_id))
                if position_id is not None
                else None,
                company=position.get("subcompany") or token,
                title=position.get("name"),
                location=position.get("office") or None,
                jd_text=html_to_markdown(position.get("description") or ""),
                posted_at=None,
            )
        )
    return rows


def fetch_personio(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = httpx.get(
        search_url(target.token, target.country), timeout=30, follow_redirects=True
    )
    response.raise_for_status()
    return parse_personio(response.text, target.token, target.country)
