from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.scraper.recipe import Pagination, ScrapeRecipe
from resume_agent.discovery.scraper.recipe_parse import (
    has_job_like_content,
    parse_cards,
    parse_detail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _recipe(**overrides):
    values = {
        "learned_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "card_container": "li.job",
        "jd_container": "div.jd",
        "title_sel": "a",
        "location_sel": "span.loc",
        "url_sel": "a",
        "detail_mode": "link",
        "pagination": Pagination(pattern="next", control_sel="a.next"),
    }
    values.update(overrides)
    return ScrapeRecipe(**values)


def test_parse_cards_extracts_fields_and_urls_verbatim():
    html = (FIXTURES / "board_list.html").read_text(encoding="utf-8")
    cards = parse_cards(html, _recipe())
    assert [card.title for card in cards] == [
        "Backend Engineer",
        "Data Scientist",
        "Product Manager",
    ]
    assert cards[0].location == "Remote"
    assert cards[0].url == "/jobs/1"


def test_inline_cards_retain_their_detail_fragment():
    html = """
    <article class='job'>
      <h2>Backend Engineer</h2><span class='location'>Remote</span>
      <div class='description'><p>Build Python services.</p></div>
    </article>
    """
    recipe = _recipe(
        card_container="article.job",
        title_sel="h2",
        location_sel=".location",
        url_sel=None,
        jd_container=".description",
        detail_mode="inline",
    )
    card = parse_cards(html, recipe)[0]
    assert card.url is None
    assert "Build Python services" in (card.detail_html or "")
    assert "Build Python services" in parse_detail(card.detail_html or "", recipe)


def test_parse_detail_returns_markdown_without_page_chrome():
    html = (FIXTURES / "board_detail.html").read_text(encoding="utf-8")
    jd = parse_detail(html, _recipe())
    assert "services" in jd
    assert "Python" in jd
    assert "Home About" not in jd
    assert "Acme" not in jd


def test_parse_detail_absent_container_returns_empty():
    assert parse_detail("<html><body><p>nothing</p></body></html>", _recipe()) == ""


def test_has_job_like_content_true_for_multiple_job_links():
    html = (FIXTURES / "board_list.html").read_text(encoding="utf-8")
    assert has_job_like_content(html) is True


def test_has_job_like_content_false_for_empty_page():
    assert has_job_like_content("<html><body><p>No results found.</p></body></html>") is False
