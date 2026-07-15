import json

from resume_agent.discovery.source_scout import (
    MAX_CANDIDATES,
    ScoutReport,
    make_check_source_tool,
)


def test_check_source_tool_reports_probe_result(monkeypatch):
    from resume_agent.discovery import source_scout
    from resume_agent.services.sources import SourcePreview

    seen = {}

    def fake_preview(url, *, search_path, limit, browser):
        seen.update(url=url, search_path=search_path, limit=limit, browser=browser)
        return SourcePreview(
            ok=True, url=url, kind="greenhouse", token="acme", role_count=4
        )

    monkeypatch.setattr(source_scout, "preview_source", fake_preview)
    payload = json.loads(make_check_source_tool("cfg/search.yaml")("https://jobs/acme"))

    assert payload == {
        "ok": True,
        "ats": "greenhouse",
        "token": "acme",
        "role_count": 4,
        "error": None,
        "error_code": None,
    }
    assert seen == {
        "url": "https://jobs/acme",
        "search_path": "cfg/search.yaml",
        "limit": source_scout._PROBE_LIMIT,
        "browser": False,
    }


def test_check_source_tool_returns_bounded_json_when_probe_raises(monkeypatch):
    from resume_agent.discovery import source_scout

    monkeypatch.setattr(
        source_scout,
        "preview_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret details")),
    )

    payload = json.loads(make_check_source_tool("search.yaml")("https://jobs/acme"))

    assert payload["ok"] is False
    assert payload["error_code"] == "PROBE_ERROR"
    assert payload["error"] == "Source probe failed (RuntimeError)."


def test_scout_report_caps_are_constants():
    assert MAX_CANDIDATES == 12
    assert ScoutReport(candidates=[]).candidates == []
