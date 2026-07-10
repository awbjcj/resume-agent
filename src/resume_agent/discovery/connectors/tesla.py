"""Tesla Careers through a visible, persistent Playwright context.

Tesla's careers API is Akamai-gated for bare HTTP clients. A real careers tab
captures the state response and performs detail fetches inside the same origin
so its browser cookies and challenge state are preserved.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.tesla.com/careers/search/?site=US"
_STATE_MARKER = "cua-api/apps/careers/state"
_JOB_URL = "https://www.tesla.com/cua-api/apps/careers/job/{id}"
_STATE_TIMEOUT_MS = 45_000


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


class TeslaPortal:
    """One live careers tab and the state response captured from that tab."""

    def __init__(self, page: Any, state: dict):
        self._page = page
        self.state = state

    def job_detail(self, listing_id: str) -> dict:
        return self._page.evaluate(
            """async (url) => {
                const response = await fetch(url, {
                    headers: { accept: "application/json" },
                });
                if (!response.ok) throw new Error(`detail ${response.status}`);
                return await response.json();
            }""",
            _JOB_URL.format(id=listing_id),
        )


@contextmanager
def open_portal() -> Iterator[TeslaPortal]:
    """Open the canonical search page visibly and capture its state response."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            get_settings().linkedin_user_data_dir,
            headless=False,
        )
        try:
            page = context.new_page()
            with page.expect_response(
                lambda response: _STATE_MARKER in response.url,
                timeout=_STATE_TIMEOUT_MS,
            ) as captured:
                page.goto(_SEARCH_URL, wait_until="domcontentloaded")
            yield TeslaPortal(page, captured.value.json())
        finally:
            context.close()


def apply_tesla_detail(row: TeslaRow, info: dict) -> None:
    row.jd_text = html_to_markdown(info.get("description", ""))
    row.url = info.get("url") or row.url


def _fetch_detail(portal: TeslaPortal, row: TeslaRow) -> dict | None:
    try:
        return portal.job_detail(row.listing_id)
    except Exception:  # noqa: BLE001 - one portal detail failure skips only its row
        return None


def fetch_tesla(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    with open_portal() as portal:
        return harvest_detailed(
            parse_listings(portal.state),
            lambda row: _fetch_detail(portal, row),
            apply_tesla_detail,
            search=search,
            limit=limit,
            skip_seen=skip_seen,
        )
