import json
from pathlib import Path

from resume_tailor_harness.discovery.connectors.breezy import (
    apply_detail,
    fetch_breezy,
    parse_breezy,
)
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "breezy"


def test_breezy_maps_list_then_jsonld_detail():
    rows = parse_breezy(json.loads((FIXTURES / "list.json").read_text()), "masterworks")
    apply_detail(rows[0], {"html": (FIXTURES / "detail.html").read_text()})

    assert rows[0].company == "Masterworks"
    assert rows[0].location == "New York, NY"
    assert "Explain market trends" in rows[0].jd_text


def test_breezy_detail_keeps_every_jsonld_location():
    rows = parse_breezy(json.loads((FIXTURES / "list.json").read_text()), "masterworks")
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Engineer","description":"<p>Build things.</p>",
     "jobLocation":[{"address":{"addressLocality":"Austin","addressRegion":"TX"}},
                    {"address":{"addressLocality":"New York","addressRegion":"NY"}}]}
    </script>
    """

    apply_detail(rows[0], {"html": html})

    assert rows[0].location == "Austin, TX | New York, NY"


def test_breezy_skip_seen_prevents_detail_request(monkeypatch):
    payload = json.loads((FIXTURES / "list.json").read_text())

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import resume_tailor_harness.discovery.connectors.breezy as connector

    monkeypatch.setattr(connector.board, "get", lambda *args, **kwargs: Response())
    jobs = fetch_breezy(
        AtsTarget("breezy", "masterworks"),
        SearchConfig(),
        skip_seen=lambda row: True,
    )

    assert jobs == []
