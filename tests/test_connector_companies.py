import httpx

import resume_tailor_harness.discovery.connectors.companies as companies
from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.companies import CompaniesConnector
from resume_tailor_harness.discovery.connectors.config import CompanyUrl
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.search_config import SearchConfig

_GH = {
    "jobs": [
        {"title": "AI Engineer", "absolute_url": "u1", "content": "build llm systems"},
        {
            "title": "Class A CDL Driver",
            "absolute_url": "u2",
            "content": "drive a truck",
        },
    ]
}

_LEVER = [
    {"text": "AI Engineer", "hostedUrl": "u3", "description": "build python systems"}
]

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
    result = conn.fetch(cfg)
    assert [j.title for j in result.jobs] == ["AI Engineer"]
    assert conn.name == "companies"
    assert result.filtered == 1
    assert result.failures == {}


def test_fetches_detected_lever(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("lever", "acme"),
        lever=lambda token, search=None: _LEVER,
    )
    conn = CompaniesConnector(["https://jobs.lever.co/acme"])
    result = conn.fetch(SearchConfig(keywords=["python"]))
    assert [(j.source, j.title, j.url) for j in result.jobs] == [
        ("lever", "AI Engineer", "u3")
    ]


def test_fetches_detected_ashby(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("ashby", "acme"),
        ashby=lambda token: _ASHBY,
    )
    conn = CompaniesConnector(["https://jobs.ashbyhq.com/acme"])
    result = conn.fetch(SearchConfig(keywords=["retrieval"]))
    assert [(j.source, j.title, j.url) for j in result.jobs] == [
        ("ashby", "AI Engineer", "u4")
    ]


def test_configured_label_is_canonical_company_name(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("ashby", "openai"),
        ashby=lambda token: _ASHBY,
    )
    conn = CompaniesConnector(
        [CompanyUrl(url="https://jobs.ashbyhq.com/openai", label="OpenAI")]
    )

    result = conn.fetch(SearchConfig(keywords=["retrieval"]))

    assert [job.company for job in result.jobs] == ["OpenAI"]


def test_undetectable_url_recorded_and_isolated(monkeypatch):
    def detect(url):
        return AtsTarget("greenhouse", "acme") if "acme" in url else None

    _patch(monkeypatch, detect=detect, gh=lambda token: _GH)
    conn = CompaniesConnector(["https://mystery.example", "https://careers.acme.com"])
    result = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert {j.title for j in result.jobs} == {"AI Engineer"}
    assert result.failures == {"https://mystery.example": "no known ATS detected"}


def test_companies_dispatches_workday(monkeypatch):
    calls = {}

    def fake_workday(target, search, limit=None, skip_seen=None):
        calls["target"] = target
        return [RawJob("workday", "u", "acme", "Software Engineer", "Austin", "jd")]

    monkeypatch.setattr(companies, "fetch_workday", fake_workday)
    monkeypatch.setattr(
        companies,
        "detect_ats",
        lambda url: AtsTarget(
            "workday", tenant="acme", datacenter="wd5", site="Careers"
        ),
    )
    conn = CompaniesConnector(["https://acme.wd5.myworkdayjobs.com/Careers"])
    result = conn.fetch(SearchConfig())
    assert calls["target"].tenant == "acme"
    assert [j.source for j in result.jobs] == ["workday"]


def test_companies_isolates_parser_error(monkeypatch):
    def boom(token):
        raise KeyError("unexpected payload shape")

    _patch(monkeypatch, detect=lambda url: AtsTarget("greenhouse", "acme"), gh=boom)
    conn = CompaniesConnector(["https://careers.acme.com"])
    result = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert result.jobs == []
    assert "parse error: KeyError" in result.failures["https://careers.acme.com"]


def test_companies_unsupported_ats_recorded(monkeypatch):
    monkeypatch.setattr(
        companies, "detect_ats", lambda url: AtsTarget("futureats", "x")
    )
    conn = CompaniesConnector(["https://careers.x.com"])
    result = conn.fetch(SearchConfig())
    assert result.failures == {
        "https://careers.x.com": "Futureats recognized, not yet supported"
    }


def test_http_error_on_one_board_is_isolated(monkeypatch):
    def gh(token):
        raise httpx.HTTPStatusError(
            "404",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(404),
        )

    _patch(monkeypatch, detect=lambda url: AtsTarget("greenhouse", "dead"), gh=gh)
    conn = CompaniesConnector(["https://careers.dead.com"])
    result = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert result.jobs == []
    assert "404" in result.failures["https://careers.dead.com"]


def test_limit_caps_results(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("greenhouse", "acme"),
        gh=lambda token: _GH,
    )
    conn = CompaniesConnector(["https://careers.acme.com"])
    result = conn.fetch(SearchConfig(keywords=["a"]), limit=1)
    assert len(result.jobs) == 1


def test_companies_forwards_skip_seen_to_backend(monkeypatch):
    captured = {}

    def backend(target, search, limit=None, skip_seen=None):
        captured["skip_seen"] = skip_seen
        return []

    monkeypatch.setattr(companies, "detect_ats", lambda url: AtsTarget("workday"))
    monkeypatch.setitem(companies._BACKENDS, "workday", backend)

    def marker(row):
        return False

    CompaniesConnector(["https://example.test/jobs"]).fetch(
        SearchConfig(), skip_seen=marker
    )

    assert captured["skip_seen"] is marker


def test_companies_remains_concurrent_without_browser_portals():
    connector = CompaniesConnector(["https://boards.greenhouse.io/acme"])
    assert connector.concurrent_fetch is True


def test_companies_serializes_when_tesla_is_present():
    connector = CompaniesConnector(
        [
            "https://boards.greenhouse.io/acme",
            "https://www.tesla.com/careers/search/?site=US",
        ]
    )
    assert connector.concurrent_fetch is False


def test_companies_coerces_strings_and_carries_limits():
    connector = CompaniesConnector(
        [
            "https://boards.greenhouse.io/acme",
            CompanyUrl(url="https://jobs.lever.co/beta", limit=3),
        ]
    )
    assert connector.urls[0].url == "https://boards.greenhouse.io/acme"
    assert connector.urls[0].limit is None
    assert connector.urls[1].limit == 3


def test_companies_resolves_and_enforces_each_url_limit(monkeypatch):
    received_limits = []

    def backend(target, search, limit=None, skip_seen=None):
        received_limits.append(limit)
        return [
            RawJob(
                source="fake",
                url=f"https://x/{target.token}/{index}",
                company=target.token,
                title=f"Engineer {index}",
                location=None,
                jd_text="Python",
            )
            for index in range(3)
        ]

    monkeypatch.setattr(
        companies,
        "detect_ats",
        lambda url: AtsTarget("fake", token="alpha" if "alpha" in url else "beta"),
    )
    monkeypatch.setitem(companies._BACKENDS, "fake", backend)
    connector = CompaniesConnector(
        [
            CompanyUrl(url="https://alpha.example/careers", limit=1),
            CompanyUrl(url="https://beta.example/careers"),
        ]
    )
    result = connector.fetch(SearchConfig(role_anchors=["Engineer"]), limit=2)
    assert received_limits == [1, 2]
    assert [job.company for job in result.jobs] == ["alpha", "beta", "beta"]
