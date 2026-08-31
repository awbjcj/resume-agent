from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_tailor_harness.discovery.url_ingest.models import ExtractedJob

# Greenhouse serves two different layouts under two hosts detect.py both accept:
# the legacy ``boards.greenhouse.io`` markup and the modern
# ``job-boards.greenhouse.io`` rewrite. Each field is looked up across both
# vocabularies so a posting from either host reads the same.
_TITLE_SELECTORS = ("h1.app-title", "h1.section-header", "h1.job__title", "h1")
_COMPANY_SELECTORS = ("span.company-name", ".job__company-name")
_LOCATION_SELECTORS = ("div.location", ".job__location", ".location")
_BODY_SELECTORS = ("div#content", "div.job__description", "#job-description")


def _text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag) and (value := node.get_text(" ", strip=True)):
            return value
    return None


def _body(soup: BeautifulSoup) -> str:
    for selector in _BODY_SELECTORS:
        node = soup.select_one(selector)
        if not isinstance(node, Tag):
            continue
        lines = [ln.strip() for ln in node.get_text("\n", strip=True).splitlines()]
        if text := "\n".join(ln for ln in lines if ln):
            return text
    return ""


def read_greenhouse_posting(html: str) -> ExtractedJob | None:
    """Read a single Greenhouse posting page into structured fields.

    Distinct from connectors.greenhouse.parse_greenhouse, which maps the board
    *API* JSON; this scrapes one rendered posting's HTML. Returns ``None`` when
    the page yields no description text, so the caller can fall back rather
    than treat an empty scrape as a successful read.
    """
    soup = BeautifulSoup(html, "html.parser")
    company = _text(soup, _COMPANY_SELECTORS)
    if company and company.lower().startswith("at "):
        company = company[3:].strip() or None
    jd_text = _body(soup)
    if not jd_text:
        return None
    return ExtractedJob(
        title=_text(soup, _TITLE_SELECTORS),
        company=company,
        location=_text(soup, _LOCATION_SELECTORS),
        jd_text=jd_text,
    )
