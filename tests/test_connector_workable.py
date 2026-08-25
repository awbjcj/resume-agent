import json
from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.workable import (
    account_url,
    fetch_workable,
    parse_workable,
)
from resume_agent.discovery.search_config import SearchConfig


def test_workable_maps_public_account_payload():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "workable" / "account.json").read_text()
    )
    jobs = parse_workable(payload, "careers")

    assert (
        account_url("careers")
        == "https://apply.workable.com/api/v1/widget/accounts/careers"
    )
    assert jobs[0].company == "Workable"
    assert jobs[0].location == "Athens, Attica, Greece"
    assert "Ship tested APIs" in jobs[0].jd_text


def test_workable_fetch_uses_details_endpoint(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "workable" / "account.json").read_text()
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    def fake_get(url, params=None, **kwargs):
        captured.update(url=url, params=params)
        return Response()

    import resume_agent.discovery.connectors.workable as connector

    monkeypatch.setattr(connector.board, "get", fake_get)
    jobs = fetch_workable(AtsTarget("workable", "careers"), SearchConfig())

    assert captured["params"] == {"details": "true"}
    assert jobs[0].title == "Senior Software Engineer"


def test_workable_renders_the_dedicated_metadata_fields():
    """`details=true` returns employment type, department, industry, experience
    and education as fields, plus the only statement of the remote policy.
    Mapping the three description sections alone dropped every one."""
    payload = {
        "name": "Acme",
        "jobs": [
            {
                "title": "Engineer",
                "city": "New York",
                "state": "New York",
                "country": "United States",
                "telecommuting": True,
                "employment_type": "Full-time",
                "experience": "Mid-Senior Level",
                "education": "Bachelor's Degree",
                "department": "Engineering",
                "industry": "Hospital & Health Care",
                "description": "<p>Build.</p>",
            }
        ],
    }

    [job] = parse_workable(payload, "acme")
    header = job.jd_text.split("\n\n")[0].splitlines()

    assert "Location: New York, New York, United States" in header
    assert "Workplace Type: Remote" in header
    assert "Employment Type: Full-time" in header
    assert "Experience Level: Mid-Senior Level" in header
    assert "Industry: Hospital & Health Care" in header
