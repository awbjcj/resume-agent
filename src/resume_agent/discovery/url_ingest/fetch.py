from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from resume_agent.discovery.url_ingest.browser import fetch_rendered
from resume_agent.discovery.url_ingest.models import PageContent
from resume_agent.security.outbound import (
    Resolver,
    fetch_public_text,
    resolve_host,
    validate_public_url,
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; resume-agent/1.0)"}
_LINKEDIN_DETAIL_SELECTOR = "div.show-more-less-html__markup, .description__text"
_SHELL_TEXT_THRESHOLD = 200


def is_linkedin(host: str) -> bool:
    """The single LinkedIn host rule, shared by fetch (render) and service (route)."""
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _looks_like_js_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    return len(body.get_text(" ", strip=True)) < _SHELL_TEXT_THRESHOLD


def fetch_static(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_host,
) -> PageContent:
    """Plain, non-browser GET. Known-ATS hosts use only this -- never the browser."""
    response = fetch_public_text(
        url,
        client=client,
        resolver=resolver,
        max_bytes=2_000_000,
        timeout=20.0,
        headers=_HEADERS,
    )
    return PageContent(
        html=response.text,
        final_url=response.final_url,
        rendered=False,
    )


def upgrade_if_shell(page: PageContent, *, allow_browser: bool = True) -> PageContent:
    """Re-fetch an already-fetched page in a browser when it is a JS shell.

    Takes the ``PageContent`` the caller already holds rather than a URL, so a
    caller that has fetched statically to route the URL does not pay a second
    request against the same host just to apply the shell policy.
    """
    if not allow_browser or not _looks_like_js_shell(page.html):
        return page
    validate_public_url(page.final_url)
    return PageContent(
        html=fetch_rendered(page.final_url), final_url=page.final_url, rendered=True
    )


def fetch_page(url: str, *, allow_browser: bool = True) -> PageContent:
    """Fetch a posting page. HTTP-first; render in-browser for LinkedIn or JS shells."""
    host = urlsplit(url).netloc.lower()
    if allow_browser and is_linkedin(host):
        validate_public_url(url)
        html = fetch_rendered(url, wait_selector=_LINKEDIN_DETAIL_SELECTOR)
        return PageContent(html=html, final_url=url, rendered=True)
    return upgrade_if_shell(fetch_static(url), allow_browser=allow_browser)
