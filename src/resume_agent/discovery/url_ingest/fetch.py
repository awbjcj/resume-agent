from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from resume_agent.discovery.url_ingest.browser import fetch_rendered
from resume_agent.discovery.url_ingest.models import PageContent

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; resume-agent/1.0)"}
_LINKEDIN_DETAIL_SELECTOR = "div.show-more-less-html__markup, .description__text"
_SHELL_TEXT_THRESHOLD = 200


def _is_linkedin(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _looks_like_js_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    return len(body.get_text(" ", strip=True)) < _SHELL_TEXT_THRESHOLD


def fetch_page(url: str, *, allow_browser: bool = True) -> PageContent:
    """Fetch a posting page. HTTP-first; render in-browser for LinkedIn or JS shells."""
    host = urlsplit(url).netloc.lower()
    if allow_browser and _is_linkedin(host):
        html = fetch_rendered(url, wait_selector=_LINKEDIN_DETAIL_SELECTOR)
        return PageContent(html=html, final_url=url, rendered=True)
    resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=20.0)
    resp.raise_for_status()
    html = resp.text
    final_url = str(resp.url)
    if allow_browser and _looks_like_js_shell(html):
        rendered = fetch_rendered(url)
        return PageContent(html=rendered, final_url=final_url, rendered=True)
    return PageContent(html=html, final_url=final_url, rendered=False)
