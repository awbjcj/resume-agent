from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.connectors.text import (
    clean_job_description_text,
    html_to_markdown,
)
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.recipe import ScrapeRecipe

_MIN_JOB_LINKS = 3
_JOB_PATH_TOKENS = ("job", "career", "position", "opening")


def _selected_text(card: Tag, selector: str | None) -> str | None:
    if selector is None:
        return None
    node = card.select_one(selector)
    if node is None:
        return None
    return node.get_text(" ", strip=True) or None


def _selected_href(card: Tag, selector: str | None) -> str | None:
    if selector is None:
        return None
    node = card.select_one(selector)
    if not isinstance(node, Tag):
        return None
    href = node.get("href")
    return href.strip() if isinstance(href, str) and href.strip() else None


def parse_cards(html: str, recipe: ScrapeRecipe) -> list[ScrapedCard]:
    """Parse list cards without performing I/O or resolving relative URLs."""
    soup = BeautifulSoup(html, "html.parser")
    return [
        ScrapedCard(
            job_id=None,
            title=_selected_text(card, recipe.title_sel),
            company=None,
            location=_selected_text(card, recipe.location_sel),
            url=_selected_href(card, recipe.url_sel),
            detail_html=str(card) if recipe.detail_mode == "inline" else None,
        )
        for card in soup.select(recipe.card_container)
        if isinstance(card, Tag)
    ]


def parse_detail(html: str, recipe: ScrapeRecipe) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(recipe.jd_container)
    if not isinstance(node, Tag):
        return ""
    return clean_job_description_text(html_to_markdown(node.decode_contents()))


def has_job_like_content(html: str) -> bool:
    """Return whether a page has enough job-like links to justify one relearn."""
    soup = BeautifulSoup(html, "html.parser")
    matching_links = 0
    for anchor in soup.find_all("a"):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        if any(token in href.casefold() for token in _JOB_PATH_TOKENS):
            matching_links += 1
            if matching_links >= _MIN_JOB_LINKS:
                return True
    return False
