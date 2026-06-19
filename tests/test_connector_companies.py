import httpx

import resume_agent.discovery.connectors.companies as companies
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

_GH = {
    "jobs": [
        {"title": "AI Engineer", "absolute_url": "u1", "content": "build llm systems"},
        {"title": "Class A CDL Driver", "absolute_url": "u2", "content": "drive a truck"},
    ]
}

_LEVER = [{"text": "AI Engineer", "hostedUrl": "u3", "description": "build python systems"}]

_ASHBY = {
    "jobs": [
        {
            "title": "AI Engineer",
            "jobUrl": "u4",
            "descriptionPlain": "build retrieval systems",
        }
    ]
}


def _patch(monkeypatch, *, detect, gh=None, lever=None, ashby=None):
    monkeypatch.setattr(companies, "detect_ats", detect)
    if gh is not None:
        monkeypatch.setattr(companies, "fetch_greenhouse_board", gh)
    if lever is not None:
        monkeypatch.setattr(companies, "fetch_lever_board", lever)
    if ashby is not None:
        monkeypatch.setattr(companies, "fetch_ashby_board", ashby)


def test_fetches_detected_greenhouse_and_gates(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("greenhouse", "acme"),
        gh=lambda token: _GH,
    )
    conn = CompaniesConnector(["https://careers.acme.com"])
    cfg = SearchConfig(role_anchors=["engineer", "ai"], exclude_terms=["driver", "cdl"])
    jobs = conn.fetch(cfg)
    assert [j.title for j in jobs] == ["AI Engineer"]
    assert conn.name == "companies"
    assert conn.filtered == 1
    assert conn.failures == {}


def test_fetches_detected_lever(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("lever", "acme"),
        lever=lambda token: _LEVER,
    )
    conn = CompaniesConnector(["https://jobs.lever.co/acme"])
    jobs = conn.fetch(SearchConfig(keywords=["python"]))
    assert [(j.source, j.title, j.url) for j in jobs] == [("lever", "AI Engineer", "u3")]


def test_fetches_detected_ashby(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("ashby", "acme"),
        ashby=lambda token: _ASHBY,
    )
    conn = CompaniesConnector(["https://jobs.ashbyhq.com/acme"])
    jobs = conn.fetch(SearchConfig(keywords=["retrieval"]))
    assert [(j.source, j.title, j.url) for j in jobs] == [("ashby", "AI Engineer", "u4")]


def test_undetectable_url_recorded_and_isolated(monkeypatch):
    def detect(url):
        return AtsTarget("greenhouse", "acme") if "acme" in url else None

    _patch(monkeypatch, detect=detect, gh=lambda token: _GH)
    conn = CompaniesConnector(["https://mystery.example", "https://careers.acme.com"])
    jobs = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert {j.title for j in jobs} == {"AI Engineer"}
    assert "https://mystery.example" in conn.failures
    assert "no known ATS" in conn.failures["https://mystery.example"]


def test_companies_dispatches_workday(monkeypatch):
    calls = {}

    def fake_workday(target, search, limit=None):
        calls["target"] = target
        return [RawJob("workday", "u", "acme", "Software Engineer", "Austin", "jd")]

    monkeypatch.setattr(companies, "fetch_workday", fake_workday)
    monkeypatch.setattr(
        companies,
        "detect_ats",
        lambda url: AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers"),
    )
    conn = CompaniesConnector(["https://acme.wd5.myworkdayjobs.com/Careers"])
    jobs = conn.fetch(SearchConfig())
    assert calls["target"].tenant == "acme"
    assert [j.source for j in jobs] == ["workday"]


def test_companies_unsupported_ats_recorded(monkeypatch):
    monkeypatch.setattr(
        companies, "detect_ats", lambda url: AtsTarget("smartrecruiters", "x")
    )
    conn = CompaniesConnector(["https://careers.x.com"])
    conn.fetch(SearchConfig())
    assert "https://careers.x.com" in conn.failures
    assert "not yet supported" in conn.failures["https://careers.x.com"]


def test_http_error_on_one_board_is_isolated(monkeypatch):
    def gh(token):
        raise httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
        )

    _patch(monkeypatch, detect=lambda url: AtsTarget("greenhouse", "dead"), gh=gh)
    conn = CompaniesConnector(["https://careers.dead.com"])
    jobs = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert jobs == []
    assert "404" in conn.failures["https://careers.dead.com"]


def test_limit_caps_results(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("greenhouse", "acme"),
        gh=lambda token: _GH,
    )
    conn = CompaniesConnector(["https://careers.acme.com"])
    jobs = conn.fetch(SearchConfig(keywords=["a"]), limit=1)
    assert len(jobs) == 1
