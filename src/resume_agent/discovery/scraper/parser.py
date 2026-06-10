from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.scraper.models import ScrapedCard


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _href(node: Tag | None) -> str | None:
    if node is None:
        return None
    href = node.get("href")
    return href if isinstance(href, str) else None


def _strip_query(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlsplit(href)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _job_id(card: Tag, url: str | None) -> str | None:
    urn = card.get("data-entity-urn", "")
    if isinstance(urn, str) and urn:
        return urn.split(":")[-1]
    if not url:
        return None
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    return parts[-1] if parts and parts[-1].isdigit() else None


def parse_search_cards(html: str) -> list[ScrapedCard]:
    """Parse a LinkedIn job-search results page into structured cards."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ScrapedCard] = []
    for card in soup.select("div.base-card"):
        link = card.select_one("a.base-card__full-link")
        url = _strip_query(_href(link))
        cards.append(
            ScrapedCard(
                job_id=_job_id(card, url),
                title=_text(card.select_one("h3.base-search-card__title")),
                company=_text(card.select_one("h4.base-search-card__subtitle")),
                location=_text(card.select_one("span.job-search-card__location")),
                url=url,
            )
        )
    return cards


def parse_job_detail(html: str) -> str:
    """Extract the job-description text from a LinkedIn job-detail page.

    Returns ``""`` when no recognized JD container is present, so a layout
    change yields an empty (and therefore skipped) JD rather than the entire
    page's navigation/chrome text being ingested as a bogus description.
    """
    soup = BeautifulSoup(html, "html.parser")
    markup = soup.select_one("div.show-more-less-html__markup") or soup.select_one(
        ".description__text"
    )
    if markup is None:
        return ""
    lines = [line.strip() for line in markup.get_text("\n", strip=True).splitlines()]
    return "\n".join(line for line in lines if line)
