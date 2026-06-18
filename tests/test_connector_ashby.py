import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ashby" / "job_board.json").read_text())


def test_parse_ashby_maps_fields():
    jobs = parse_ashby(FIXTURE, company="Acme")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "ashby"
    assert first.company == "Acme"
    assert first.title == "Senior ML Engineer"
    assert first.location == "Remote - US"
    assert first.url == "https://jobs.ashbyhq.com/acme/abc-123"
    assert "Python" in first.jd_text
    assert first.posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_parse_ashby_posted_at_none_when_absent():
    jobs = parse_ashby(FIXTURE, company="Acme")
    assert jobs[1].posted_at is None


def test_parse_ashby_falls_back_to_html_description():
    payload = {"jobs": [{"title": "Eng", "jobUrl": "u", "descriptionHtml": "<p>hello</p>"}]}
    jobs = parse_ashby(payload, "Acme")
    assert jobs[0].jd_text == "hello"


def test_fetch_ashby_board_hits_posting_api(monkeypatch):
    import resume_agent.discovery.connectors.ashby as ashby

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return FIXTURE

    def fake_get(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(ashby.httpx, "get", fake_get)
    assert fetch_ashby_board("acme") == FIXTURE
    assert captured == {
        "url": "https://api.ashbyhq.com/posting-api/job-board/acme",
        "timeout": 30,
    }
