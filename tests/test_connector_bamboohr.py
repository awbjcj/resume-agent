import json
from pathlib import Path

from resume_tailor_harness.discovery.connectors.bamboohr import (
    apply_detail,
    fetch_bamboohr,
    parse_bamboohr,
)
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "bamboohr"


def test_bamboohr_maps_list_then_nested_detail():
    rows = parse_bamboohr(json.loads((FIXTURES / "list.json").read_text()), "eleven")
    apply_detail(rows[0], json.loads((FIXTURES / "detail.json").read_text()))

    assert rows[0].company == "eleven"
    assert rows[0].url == "https://eleven.bamboohr.com/careers/132"
    assert "Design cloud-native systems" in rows[0].jd_text


def test_bamboohr_detail_metadata_replaces_stale_list_metadata():
    [row] = parse_bamboohr(
        {
            "result": [
                {
                    "id": "132",
                    "departmentLabel": "Old department",
                    "isRemote": True,
                }
            ]
        },
        "eleven",
    )

    apply_detail(
        row,
        {
            "result": {
                "jobOpening": {
                    "description": "<p>Build systems.</p>",
                    "employmentStatusLabel": "Full-time",
                    "departmentLabel": "Engineering",
                    "compensation": "$150,000 - $180,000",
                }
            }
        },
    )

    assert "Employment Type: Full-time" in row.jd_text
    assert "Department: Engineering" in row.jd_text
    assert "Department: Old department" not in row.jd_text
    assert "Compensation: $150,000 - $180,000" in row.jd_text
    assert "Workplace Type: Remote" in row.jd_text


def test_bamboohr_detail_can_clear_stale_remote_list_metadata():
    [row] = parse_bamboohr(
        {"result": [{"id": "132", "isRemote": True}]},
        "eleven",
    )

    apply_detail(
        row,
        {
            "result": {
                "jobOpening": {
                    "description": "<p>Work from the office.</p>",
                    "isRemote": False,
                }
            }
        },
    )

    assert row.location is None
    assert "Workplace Type: Remote" not in row.jd_text
    assert "Location: Remote" not in row.jd_text


def test_bamboohr_skip_seen_prevents_detail_request(monkeypatch):
    payload = json.loads((FIXTURES / "list.json").read_text())

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import resume_tailor_harness.discovery.connectors.bamboohr as connector

    monkeypatch.setattr(connector.board, "get", lambda *args, **kwargs: Response())
    jobs = fetch_bamboohr(
        AtsTarget("bamboohr", "eleven"), SearchConfig(), skip_seen=lambda row: True
    )

    assert jobs == []
