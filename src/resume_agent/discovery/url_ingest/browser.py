import shutil
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings
from resume_agent.discovery.url_ingest.models import PageContent
from resume_agent.security.outbound import Resolver, resolve_host, validate_public_url

# Pure disk caches Chrome migrates into a "<profile>.CHROME_DELETE" staging
# folder when the profile's recorded version differs from the launching
# binary's (e.g. after a Playwright browser upgrade). Safe to delete --
# Chrome regenerates them -- but on Windows the migration rename can itself
# fail with Access Denied, which aborts the whole browser launch.
_STALE_PROFILE_CACHE_DIRS = (
    "GPUPersistentCache",
    "ShaderCache",
    "GrShaderCache",
    "GraphiteDawnCache",
)


def _clear_stale_profile_cache(data_dir: str) -> bool:
    """Remove leftover Chrome version-migration artifacts from a profile dir.

    Returns True when anything was found and removed, so the caller knows a
    retry is worth attempting rather than surfacing the original error.
    """
    root = Path(data_dir)
    cleared = False
    delete_staging = root / f"{root.name}.CHROME_DELETE"
    if delete_staging.exists():
        shutil.rmtree(delete_staging, ignore_errors=True)
        cleared = True
    for name in _STALE_PROFILE_CACHE_DIRS:
        candidate = root / name
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
            cleared = True
    return cleared


def _launch_persistent_context(chromium, data_dir: str, *, headless: bool):
    """launch_persistent_context, retried once past a stale-cache migration failure.

    See _clear_stale_profile_cache: a Chromium version bump leaves the profile
    stale, and Chrome's startup migration of its GPU/shader caches can hit a
    transient Windows Access Denied that aborts the launch entirely. Retrying
    once after clearing those directories resolves it; any other failure (no
    migration artifacts present) propagates unchanged.
    """
    try:
        return chromium.launch_persistent_context(
            data_dir,
            headless=headless,
            service_workers="block",
        )
    except PlaywrightError:
        if not _clear_stale_profile_cache(data_dir):
            raise
        return chromium.launch_persistent_context(
            data_dir,
            headless=headless,
            service_workers="block",
        )


def _guard_public_request(
    route: Route,
    *,
    resolver: Resolver,
    blocked: list[ValueError],
) -> None:
    """Allow only public HTTP(S) requests from the browser context."""
    try:
        validate_public_url(route.request.url, resolver)
    except ValueError as error:
        blocked.append(error)
        route.abort("blockedbyclient")
        return
    route.continue_()


def fetch_rendered(
    url: str,
    *,
    user_data_dir: str | None = None,
    wait_selector: str | None = None,
    headless: bool = False,
    render_timeout_ms: int = 8000,
    pace_seconds: float = 1.0,
    resolver: Resolver = resolve_host,
) -> str:
    """Render one URL in the logged-in persistent browser and return its HTML.

    A one-shot lifecycle (launch, navigate, close) distinct from the scraper's
    reused session: this fetches a single page, optionally waiting for a content
    selector. Reuses the same ``user_data_dir`` so a LinkedIn login carries over.
    """
    validate_public_url(url, resolver)
    data_dir = user_data_dir or get_settings().linkedin_user_data_dir
    with sync_playwright() as p:
        context = _launch_persistent_context(p.chromium, data_dir, headless=headless)
        try:
            blocked: list[ValueError] = []
            context.route(
                "**/*",
                partial(_guard_public_request, resolver=resolver, blocked=blocked),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            if blocked:
                raise ValueError(
                    "browser request was blocked by public URL policy"
                ) from blocked[0]
            validate_public_url(page.url, resolver)
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
    resolver: Resolver = resolve_host,
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
        context = _launch_persistent_context(p.chromium, data_dir, headless=headless)
        try:
            blocked: list[ValueError] = []
            context.route(
                "**/*",
                partial(_guard_public_request, resolver=resolver, blocked=blocked),
            )
            for url in dict.fromkeys(
                urls
            ):  # dedupe, preserve order; re-clicks boomerang
                page = context.new_page()
                try:
                    blocked.clear()
                    validate_public_url(url, resolver)
                    page.goto(
                        url, wait_until="domcontentloaded", timeout=goto_timeout_ms
                    )
                    if settle_ms:
                        page.wait_for_timeout(settle_ms)  # let JS/meta redirect settle
                    if blocked:
                        raise ValueError(
                            "browser request was blocked by public URL policy"
                        ) from blocked[0]
                    validate_public_url(page.url, resolver)
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
