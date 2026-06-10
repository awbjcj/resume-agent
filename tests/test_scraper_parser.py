from pathlib import Path

from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def test_scraped_card_fields():
    card = ScrapedCard(
        job_id="3700000001",
        title="Senior Backend Engineer",
        company="Acme Corp",
        location="Remote, US",
        url="https://www.linkedin.com/jobs/view/3700000001/",
    )
    assert card.job_id == "3700000001"
    assert card.company == "Acme Corp"


def test_parse_search_cards_extracts_each_posting():
    html = (FIXTURES / "search.html").read_text(encoding="utf-8")
    cards = parse_search_cards(html)
    assert len(cards) == 2

    first = cards[0]
    assert first.job_id == "3700000001"
    assert first.title == "Senior Backend Engineer"
    assert first.company == "Acme Corp"
    assert first.location == "Remote, United States"
    assert first.url == "https://www.linkedin.com/jobs/view/3700000001/"

    second = cards[1]
    assert second.job_id == "3700000002"


def test_parse_job_detail_returns_clean_text():
    html = (FIXTURES / "job.html").read_text(encoding="utf-8")
    text = parse_job_detail(html)
    assert "backend engineer" in text.lower()
    assert "5+ years of Python." in text
    assert "Kubernetes" in text
    assert "<li>" not in text


def test_parse_job_detail_returns_empty_when_container_missing():
    # No recognized JD container: must not dump whole-page chrome as the JD.
    html = "<html><body><nav>People also viewed</nav><footer>About</footer></body></html>"
    assert parse_job_detail(html) == ""
