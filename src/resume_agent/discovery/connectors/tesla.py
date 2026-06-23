from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown
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
                title=item.get("title") or item.get("t"),
                location=item.get("region") or item.get("l"),
                jd_text="",
                listing_id=str(item.get("id") or ""),
            )
        )
    return rows


def _fetch_detail(row: TeslaRow) -> dict:
    d = httpx.get(_JOB_URL.format(id=row.listing_id), timeout=30)
    d.raise_for_status()
    return d.json()


def apply_tesla_detail(row: TeslaRow, info: dict) -> None:
    row.jd_text = html_to_markdown(info.get("description", ""))
    row.url = info.get("url") or row.url


def fetch_tesla(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    resp = httpx.get(_STATE_URL, timeout=30)
    resp.raise_for_status()
    return harvest_detailed(
        parse_listings(resp.json()),
        _fetch_detail,
        apply_tesla_detail,
        search=search,
        limit=limit,
    )
