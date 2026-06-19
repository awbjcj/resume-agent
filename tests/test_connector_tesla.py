import resume_agent.discovery.connectors.tesla as tesla
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("tesla")
STATE = {"listings": [
    {"id": "1", "title": "Software Engineer", "department": "Software", "region": "Austin, TX"},
    {"id": "2", "title": "Welder", "department": "Manufacturing", "region": "Fremont, CA"},
]}
DETAIL = {"id": "1", "description": "<p>Build with Python.</p>",
          "url": "https://www.tesla.com/careers/search/job/1"}


def test_parse_tesla_listings_to_partial_rawjobs():
    rows = tesla.parse_listings(STATE)
    assert [r.title for r in rows] == ["Software Engineer", "Welder"]
    assert rows[0].source == "tesla"
    assert rows[0].company == "Tesla"
    assert rows[0].location == "Austin, TX"
    assert rows[0].listing_id == "1"
    assert rows[0].jd_text == ""


def test_fetch_tesla_gates_then_details(monkeypatch):
    detail_calls = []

    class _Resp:
        def __init__(self, p):
            self._p = p

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def fake_get(url, timeout):
        if "state" in url:
            return _Resp(STATE)
        detail_calls.append(url)
        return _Resp(DETAIL)

    monkeypatch.setattr(tesla.httpx, "get", fake_get)
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(role_anchors=["Software Engineer"]))
    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 1
    assert "Python" in jobs[0].jd_text
