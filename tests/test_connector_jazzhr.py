from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.jazzhr import (
    apply_detail,
    fetch_jazzhr,
    parse_listing,
)
from resume_agent.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "jazzhr"


def test_jazzhr_maps_listing_then_jsonld_detail():
    rows = parse_listing((FIXTURES / "list.html").read_text(), "utilidata")
    apply_detail(rows[0], {"html": (FIXTURES / "detail.html").read_text()})

    assert rows[0].company == "Utilidata"
    assert rows[0].url is not None
    assert rows[0].url.endswith("Application-Engineer-Data-Center-Software")
    assert "Develop Python integration tooling" in rows[0].jd_text


def test_jazzhr_detail_keeps_every_jsonld_location():
    rows = parse_listing((FIXTURES / "list.html").read_text(), "utilidata")
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Engineer","description":"<p>Build things.</p>",
     "jobLocation":[{"address":{"addressLocality":"Austin","addressRegion":"TX"}},
                    {"address":{"addressLocality":"New York","addressRegion":"NY"}}]}
    </script>
    """

    apply_detail(rows[0], {"html": html})

    assert rows[0].location == "Austin, TX | New York, NY"


def test_jazzhr_deduplicates_desktop_and_mobile_listing_links():
    html = (FIXTURES / "list.html").read_text()

    assert len(parse_listing(html + html, "utilidata")) == 1


def test_jazzhr_skip_seen_prevents_detail_request(monkeypatch):
    html = (FIXTURES / "list.html").read_text()

    class Response:
        text = html

        def raise_for_status(self):
            pass

    import resume_agent.discovery.connectors.jazzhr as connector

    monkeypatch.setattr(connector.board, "get", lambda *args, **kwargs: Response())
    jobs = fetch_jazzhr(
        AtsTarget("jazzhr", "utilidata"), SearchConfig(), skip_seen=lambda row: True
    )

    assert jobs == []
