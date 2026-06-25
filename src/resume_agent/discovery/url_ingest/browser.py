import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings
from resume_agent.discovery.url_ingest.models import PageContent


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


def render_pages(
    urls: list[str],
    *,
    user_data_dir: str | None = None,
    headless: bool = False,
    goto_timeout_ms: int = 30000,
    settle_ms: int = 6000,
    pace_seconds: float = 1.0,
) -> dict[str, PageContent]:
    """Render each URL through ONE shared browser context, returning post-redirect pages.

    Adzuna's redirect links are bot-gated click-trackers: a bare httpx GET is met with
    403 and a *headless* browser is challenged ("suspicious behaviour"), but a real
    (non-headless) browser follows the redirect chain to the employer posting. One
    context is reused across the batch -- re-clicking the *same* ad boomerangs to a
    search page, but distinct ads in a shared context resolve normally.

    Returns ``{url: PageContent}`` keyed by the input url, with the *post-redirect*
    ``final_url`` captured. URLs whose render fails are omitted (best-effort); only a
    failure to launch the browser propagates.
    """
    results: dict[str, PageContent] = {}
    if not urls:
        return results
    data_dir = user_data_dir or get_settings().linkedin_user_data_dir
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(data_dir, headless=headless)
        try:
            for url in dict.fromkeys(urls):  # dedupe, preserve order; re-clicks boomerang
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
                    if settle_ms:
                        page.wait_for_timeout(settle_ms)  # let JS/meta redirect settle
                    results[url] = PageContent(
                        html=page.content(), final_url=page.url, rendered=True
                    )
                except Exception:  # noqa: BLE001 - one bad ad must not kill the batch
                    pass
                finally:
                    page.close()
                if pace_seconds:
                    time.sleep(pace_seconds)
        finally:
            context.close()
    return results
