import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings


def fetch_rendered(
    url: str,
    *,
    user_data_dir: str | None = None,
    wait_selector: str | None = None,
    headless: bool = False,
    render_timeout_ms: int = 8000,
    pace_seconds: float = 1.0,
) -> str:
    """Render one URL in the logged-in persistent browser and return its HTML.

    A one-shot lifecycle (launch, navigate, close) distinct from the scraper's
    reused session: this fetches a single page, optionally waiting for a content
    selector. Reuses the same ``user_data_dir`` so a LinkedIn login carries over.
    """
    data_dir = user_data_dir or get_settings().linkedin_user_data_dir
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(data_dir, headless=headless)
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            if wait_selector is not None:
                try:
                    page.wait_for_selector(wait_selector, timeout=render_timeout_ms)
                except PlaywrightTimeoutError:
                    pass
            time.sleep(pace_seconds)
            return page.content()
        finally:
            context.close()
