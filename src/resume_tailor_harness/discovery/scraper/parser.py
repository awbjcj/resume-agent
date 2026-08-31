from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_tailor_harness.discovery.connectors.dates import (
    parse_iso_datetime,
    parse_relative_posted_at,
)
from resume_tailor_harness.discovery.scraper.models import DetailMeta, ScrapedCard


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
    href = urljoin("https://www.linkedin.com", href)
    parsed = urlsplit(href)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _job_id(card: Tag, url: str | None) -> str | None:
    for attr in ("data-job-id", "data-occludable-job-id"):
        value = card.get(attr)
        if isinstance(value, str) and value:
            return value
    urn = card.get("data-entity-urn", "")
    if isinstance(urn, str) and urn:
        return urn.split(":")[-1]
    if not url:
        return None
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    return parts[-1] if parts and parts[-1].isdigit() else None


def parse_search_cards(html: str, now: datetime | None = None) -> list[ScrapedCard]:
    """Parse a LinkedIn job-search results page into structured cards."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ScrapedCard] = []
    card_nodes = [
        *soup.select("div.base-card"),
        *soup.select("div.job-card-container[data-job-id]"),
    ]
    for card in card_nodes:
        link = card.select_one(
            "a.base-card__full-link, "
            "a.job-card-list__title--link, "
            "a[href*='/jobs/view/']"
        )
        url = _strip_query(_href(link))
        posted_at = None
        date_node = card.select_one(
            "time.job-search-card__listdate, time.job-search-card__listdate--new, time"
        )
        if date_node is not None:
            date_value = date_node.get("datetime")
            if isinstance(date_value, str):
                posted_at = parse_iso_datetime(date_value)
            if posted_at is None:
                posted_at = parse_relative_posted_at(_text(date_node), now=now)
        cards.append(
            ScrapedCard(
                job_id=_job_id(card, url),
                title=_text(
                    card.select_one(
                        "h3.base-search-card__title, a.job-card-list__title--link"
                    )
                ),
                company=_text(
                    card.select_one(
                        "h4.base-search-card__subtitle, "
                        ".artdeco-entity-lockup__subtitle, "
                        ".job-card-container__primary-description"
                    )
                ),
                location=_text(
                    card.select_one(
                        "span.job-search-card__location, "
                        ".artdeco-entity-lockup__caption, "
                        ".job-card-container__metadata-item"
                    )
                ),
                url=url,
                posted_at=posted_at,
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
    markup = (
        soup.select_one("div.show-more-less-html__markup")
        or soup.select_one(".description__text")
        or soup.select_one(".jobs-box__html-content")
        or soup.select_one(".jobs-description__container")
        or soup.select_one("[data-sdui-component*='aboutTheJob']")
        or soup.select_one("[componentkey^='JobDetails_AboutTheJob']")
    )
    if markup is None:
        return ""
    lines = [line.strip() for line in markup.get_text("\n", strip=True).splitlines()]
    return "\n".join(line for line in lines if line)


def _title_company_from_page_title(
    soup: BeautifulSoup,
) -> tuple[str | None, str | None]:
    """Fall back to ``<title>Job Title | Company | LinkedIn</title>``.

    The authenticated flagship3 job-details view renders its top card through
    atomic/hashed CSS classes with no stable selector, so title/company can't
    be read from markup there the way the legacy public "topcard" layout
    allows. The page ``<title>`` keeps this stable "title | company | LinkedIn"
    format in both layouts, so it's used only when the legacy markup is absent.
    """
    text = _text(soup.title)
    if not text:
        return None, None
    parts = [part.strip() for part in text.split(" | ")]
    if len(parts) < 3 or parts[-1] != "LinkedIn":
        return None, None
    return parts[0] or None, " | ".join(parts[1:-1]) or None


def parse_detail_meta(html: str) -> DetailMeta:
    """Read title/company/location from a LinkedIn job-detail page's top card."""
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("h1.top-card-layout__title"))
    company = _text(soup.select_one("a.topcard__org-name-link"))
    location = _text(soup.select_one("span.topcard__flavor--bullet"))
    if title is None and company is None:
        title, company = _title_company_from_page_title(soup)
    return DetailMeta(title=title, company=company, location=location)
