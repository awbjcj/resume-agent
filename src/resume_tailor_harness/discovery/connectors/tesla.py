"""Tesla Careers through a visible, real-Chrome Playwright context.

Tesla's careers site is gated by Akamai Bot Manager. It fingerprints the
browser: bundled Chromium and any context reporting ``navigator.webdriver`` are
served an "Access Denied" page, so the careers ``state`` XHR never fires. A
visible real Chrome (``channel="chrome"``) with the automation flag stripped
presents a genuine fingerprint that passes; a fresh non-persistent context
avoids a poisoned Akamai cookie from a prior denied session. The tab then
performs detail fetches inside the same origin.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.harvest import harvest_detailed
from resume_tailor_harness.discovery.connectors.text import html_to_markdown
from resume_tailor_harness.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.tesla.com/careers/search/?site=US"
_STATE_MARKER = "cua-api/apps/careers/state"
_JOB_URL = "https://www.tesla.com/cua-api/careers/job/{id}"
# JD prose is split across these HTML fields (the plain "description" is empty).
_JD_FIELDS = (
    "description",
    "jobDescription",
    "jobResponsibilities",
    "jobRequirements",
    "jobCompensationAndBenefits",
)
_STATE_TIMEOUT_MS = 45_000
# Akamai occasionally throttles a cold hit before the state XHR fires; retry a
# few times so one denial does not drop the whole Tesla pull.
_CAPTURE_ATTEMPTS = 3
_RETRY_BACKOFF_S = 5.0


class TeslaStateUnavailable(Exception):
    """The careers state response never arrived (Akamai bot gate / timeout).

    A dedicated type so ``CompaniesConnector`` can isolate this to the Tesla URL
    instead of re-raising and aborting every other company in the pull.
    """


@dataclass
class TeslaRow(RawJob):
    listing_id: str = ""


def parse_listings(state: dict) -> list[TeslaRow]:
    # Listings carry a location code ("l"); the human-readable name lives in the
    # shared lookup table. Fall back to the raw value when it is already a name.
    locations = (state.get("lookup") or {}).get("locations") or {}
    rows: list[TeslaRow] = []
    for item in state.get("listings", []):
        raw_location = item.get("region") or item.get("l")
        rows.append(
            TeslaRow(
                source="tesla",
                url=None,
                company="Tesla",
                title=item.get("title") or item.get("t"),
                location=locations.get(str(raw_location), raw_location),
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


# Strips the flag that sets navigator.webdriver=true, which Akamai rejects.
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def _launch(playwright: Any) -> Any:
    """Launch the visible browser Tesla's Akamai gate accepts; return a context.

    The real installed Chrome (``channel="chrome"``) presents a genuine browser
    fingerprint the gate passes; the bundled Chromium build is fingerprinted as a
    bot. Fall back to bundled Chromium where Chrome is absent (e.g. cloud) so the
    run degrades cleanly via ``TeslaStateUnavailable`` rather than crashing at
    launch. A fresh non-persistent context avoids a poisoned Akamai cookie left
    by a prior denied session.
    """
    try:
        browser = playwright.chromium.launch(
            headless=False, channel="chrome", args=_LAUNCH_ARGS
        )
    except Exception:  # noqa: BLE001 - Chrome channel unavailable; use bundled build
        browser = playwright.chromium.launch(headless=False, args=_LAUNCH_ARGS)
    return browser.new_context()


def _capture_once(page: Any) -> dict:
    """One navigate-and-capture of the careers state response."""
    with page.expect_response(
        lambda response: _STATE_MARKER in response.url,
        timeout=_STATE_TIMEOUT_MS,
    ) as captured:
        page.goto(_SEARCH_URL, wait_until="domcontentloaded")
    return captured.value.json()


def _capture_state(
    page: Any,
    *,
    attempts: int = _CAPTURE_ATTEMPTS,
    backoff_s: float = _RETRY_BACKOFF_S,
) -> dict:
    """Capture the state response, retrying past a throttled cold denial."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return _capture_once(page)
        except Exception as error:  # noqa: BLE001 - retry Akamai denial/timeout
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(backoff_s)
    raise TeslaStateUnavailable(
        "Tesla careers state was not returned (Akamai bot gate)"
    ) from last_error


@contextmanager
def open_portal() -> Iterator[TeslaPortal]:
    """Open the canonical search page visibly and capture its state response."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = _launch(playwright)
        try:
            page = context.new_page()
            yield TeslaPortal(page, _capture_state(page))
        finally:
            browser = context.browser
            context.close()
            if browser is not None:
                browser.close()


def _absolute_url(url: str | None) -> str | None:
    if url and url.startswith("/"):
        return "https://www.tesla.com" + url
    return url


def apply_tesla_detail(row: TeslaRow, info: dict) -> None:
    html = "\n".join(str(info.get(field) or "") for field in _JD_FIELDS).strip()
    row.jd_text = html_to_markdown(html)
    row.url = _absolute_url(info.get("url")) or row.url


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
