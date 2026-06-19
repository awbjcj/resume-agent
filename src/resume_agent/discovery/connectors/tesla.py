from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_text, relevance_gate, title_relevance_gate
from resume_agent.discovery.search_config import SearchConfig

_STATE_URL = "https://www.tesla.com/cua-api/apps/careers/state"  # confirm at build time
_JOB_URL = "https://www.tesla.com/cua-api/apps/careers/job/{id}"  # confirm at build time


@dataclass
class TeslaRow(RawJob):
    listing_id: str = ""


def parse_listings(state: dict) -> list[TeslaRow]:
    rows: list[TeslaRow] = []
    for item in state.get("listings", []):
        rows.append(
            TeslaRow(
                source="tesla",
                url=None,
                company="Tesla",
                title=item.get("title"),
                location=item.get("region"),
                jd_text="",
                listing_id=str(item.get("id") or ""),
            )
        )
    return rows


def fetch_tesla(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    resp = httpx.get(_STATE_URL, timeout=30)
    resp.raise_for_status()
    jobs: list[RawJob] = []
    for row in parse_listings(resp.json()):
        if not title_relevance_gate([row], search):
            continue
        d = httpx.get(_JOB_URL.format(id=row.listing_id), timeout=30)
        d.raise_for_status()
        info = d.json()
        row.jd_text = html_to_text(info.get("description", ""))
        row.url = info.get("url") or row.url
        if relevance_gate([row], search):
            jobs.append(row)
            if limit is not None and len(jobs) >= limit:
                break
    return jobs
