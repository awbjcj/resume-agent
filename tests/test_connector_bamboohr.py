import json
from pathlib import Path

from resume_agent.discovery.connectors.bamboohr import (
    apply_detail,
    fetch_bamboohr,
    parse_bamboohr,
)
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "bamboohr"


def test_bamboohr_maps_list_then_nested_detail():
    rows = parse_bamboohr(json.loads((FIXTURES / "list.json").read_text()), "eleven")
    apply_detail(rows[0], json.loads((FIXTURES / "detail.json").read_text()))

    assert rows[0].company == "eleven"
    assert rows[0].url == "https://eleven.bamboohr.com/careers/132"
    assert "Design cloud-native systems" in rows[0].jd_text


def test_bamboohr_skip_seen_prevents_detail_request(monkeypatch):
    payload = json.loads((FIXTURES / "list.json").read_text())

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import resume_agent.discovery.connectors.bamboohr as connector

    monkeypatch.setattr(connector.board, "get", lambda *args, **kwargs: Response())
    jobs = fetch_bamboohr(
        AtsTarget("bamboohr", "eleven"), SearchConfig(), skip_seen=lambda row: True
    )

    assert jobs == []
