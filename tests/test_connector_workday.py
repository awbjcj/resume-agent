from datetime import datetime, timezone

import resume_agent.discovery.connectors.workday as workday
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.workday import (
    apply_detail,
    cxs_detail_url,
    cxs_jobs_url,
    list_request_body,
    parse_list_rows,
)
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers")

LIST_PAGE = {
    "total": 2,
    "jobPostings": [
        {"title": "Software Engineer", "externalPath": "/job/Austin/Software-Engineer_R-1",
         "locationsText": "Austin, TX", "postedOn": "Posted Today"},
        {"title": "Data Scientist", "externalPath": "/job/Remote/Data-Scientist_R-2",
         "locationsText": "Remote", "postedOn": "Posted 3 Days Ago"},
    ],
}

DETAIL = {
    "jobPostingInfo": {
        "jobDescription": "<p>Build <b>things</b> with Python.</p>",
        "location": "Austin, TX",
        "startDate": "2026-06-01",
        "externalUrl": "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1",
    }
}


def test_cxs_jobs_url_is_built_from_triple():
    assert cxs_jobs_url(TARGET) == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"


def test_list_request_body_shapes_search_text():
    body = list_request_body(SearchConfig(titles=["Software Engineer"]), offset=20)
    assert body == {"appliedFacets": {}, "limit": 20, "offset": 20, "searchText": "Software Engineer"}


def test_list_request_body_empty_search_text_when_no_terms():
    assert list_request_body(SearchConfig(), offset=0)["searchText"] == ""


def test_parse_list_rows_yields_partial_rawjobs():
    rows = parse_list_rows(TARGET, LIST_PAGE)
    assert [r.title for r in rows] == ["Software Engineer", "Data Scientist"]
    first = rows[0]
    assert first.source == "workday"
    assert first.company == "acme"
    assert first.location == "Austin, TX"
    assert first.url == "https://acme.wd5.myworkdayjobs.com/job/Austin/Software-Engineer_R-1"
    assert first.jd_text == ""
    assert first.external_path == "/job/Austin/Software-Engineer_R-1"


def test_cxs_detail_url_joins_site_and_path():
    assert cxs_detail_url(TARGET, "/job/Austin/Software-Engineer_R-1") == (
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/Austin/Software-Engineer_R-1"
    )


def test_apply_detail_fills_jd_url_posted_at():
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    apply_detail(row, DETAIL)
    assert "Python" in row.jd_text
    assert row.url == "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1"
    assert row.posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_workday_list_gates_before_detail(monkeypatch):
    """Only the title-matching row triggers a detail call (C: list-gate before N+1)."""
    detail_calls = []

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            return _Resp(LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        detail_calls.append(url)
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    search = SearchConfig(role_anchors=["Software Engineer"])
    jobs = workday.fetch_workday(TARGET, search)

    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 1
    assert "Python" in jobs[0].jd_text


def test_fetch_workday_applies_keyword_filter_after_detail(monkeypatch):
    detail_calls = []

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            return _Resp(LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        detail_calls.append(url)
        if "Software-Engineer" in url:
            return _Resp(DETAIL)
        return _Resp(
            {
                "jobPostingInfo": {
                    "jobDescription": "<p>Analyze dashboards.</p>",
                    "externalUrl": "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-2",
                }
            }
        )

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    jobs = workday.fetch_workday(TARGET, SearchConfig(keywords=["Python"]))

    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 2


def test_fetch_workday_request_is_search_shaped(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            sent.setdefault("searchText", json["searchText"])
            return _Resp(LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    workday.fetch_workday(TARGET, SearchConfig(titles=["Software Engineer"], role_anchors=["Engineer"]))
    assert sent["searchText"] == "Software Engineer"


def test_fetch_workday_honors_limit(monkeypatch):
    page = {"total": 2, "jobPostings": LIST_PAGE["jobPostings"]}

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            return _Resp(page if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    jobs = workday.fetch_workday(TARGET, SearchConfig(), limit=1)
    assert len(jobs) == 1
