from pathlib import Path

import pytest

from resume_agent.discovery.source_resolution.crawler import FirstPartyCrawler
from resume_agent.discovery.source_resolution.resolver import CompanySourceResolver
from resume_agent.services.sources import SourcePreview


FIXTURES = Path(__file__).parent / "fixtures" / "scout_resolution"


@pytest.mark.parametrize(
    ("company", "official_url", "expected_ats", "expected_board"),
    [
        (
            "Intuitive Surgical",
            "https://careers.intuitive.com/en/",
            "smartrecruiters",
            "https://careers.smartrecruiters.com/intuitive",
        ),
        (
            "Tempus",
            "https://www.tempus.com/careers/",
            "workday",
            "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
        ),
    ],
)
def test_golden_company_resolves_the_expected_board(
    company, official_url, expected_ats, expected_board
):
    html = (FIXTURES / f"{expected_ats}.html").read_text(encoding="utf-8")
    crawler = FirstPartyCrawler(
        fetcher=lambda url: _response(url, html), validator=lambda url: None
    )
    resolver = CompanySourceResolver(
        "search.yaml",
        crawler=crawler.crawl,
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True, url=url, kind=expected_ats
        ),
    )

    result = resolver.resolve(company, official_url)

    assert result.status == "verified"
    assert result.ats == expected_ats
    assert result.canonical_board_url == expected_board


def _response(url: str, html: str):
    from resume_agent.security.outbound import PublicTextResponse

    return PublicTextResponse(final_url=url, text=html, content_type="text/html")
