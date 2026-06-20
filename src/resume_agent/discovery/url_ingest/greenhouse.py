from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.url_ingest.models import ExtractedJob


def _text(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if not isinstance(node, Tag):
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def read_greenhouse_posting(html: str) -> ExtractedJob:
    """Read a single boards.greenhouse.io posting page into structured fields.

    Distinct from connectors.greenhouse.parse_greenhouse, which maps the board
    *API* JSON; this scrapes one rendered posting's HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    company = _text(soup, "span.company-name")
    if company and company.lower().startswith("at "):
        company = company[3:].strip() or None
    body = soup.select_one("div#content")
    jd_text = ""
    if isinstance(body, Tag):
        lines = [ln.strip() for ln in body.get_text("\n", strip=True).splitlines()]
        jd_text = "\n".join(ln for ln in lines if ln)
    return ExtractedJob(
        title=_text(soup, "h1.app-title"),
        company=company,
        location=_text(soup, "div.location"),
        jd_text=jd_text,
    )
