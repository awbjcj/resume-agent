import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ashby" / "job_board.json").read_text(encoding="utf-8")
)


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


def test_parse_ashby_prepends_sidebar_metadata_to_jd_text():
    jobs = parse_ashby(FIXTURE, company="Acme")
    jd_text = jobs[0].jd_text
    assert "Location: Remote - US (also: New York City, Seattle)" in jd_text
    assert "Workplace Type: Remote" in jd_text
    assert "Employment Type: Full time" in jd_text
    assert "Department: Engineering (ML Platform)" in jd_text
    assert "Compensation: $150K – $200K • Offers Equity" in jd_text
    # Sidebar comes before the JD body.
    assert jd_text.index("Compensation:") < jd_text.index("Build LLM systems")


def test_parse_ashby_normalizes_employment_type():
    jobs = parse_ashby(FIXTURE, company="Acme")
    assert "Employment Type: Part time" in jobs[1].jd_text


def test_parse_ashby_omits_missing_sidebar_fields():
    jobs = parse_ashby(FIXTURE, company="Acme")
    jd_text = jobs[1].jd_text
    assert "Workplace Type:" not in jd_text
    assert "Department:" not in jd_text
    assert "Compensation:" not in jd_text
    assert jd_text.startswith("Location: Detroit, MI\nEmployment Type: Part time\n\nDrive a truck.")


def test_parse_ashby_no_sidebar_when_no_metadata_present():
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
        "url": "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true",
        "timeout": 30,
    }
