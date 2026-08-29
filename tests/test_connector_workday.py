import json
from datetime import datetime, timezone
from pathlib import Path

import json as json_module

import httpx
import pytest

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
FACETED_PAGE = json.loads(
    (Path(__file__).parent / "fixtures" / "workday" / "faceted-page.json").read_text(
        encoding="utf-8"
    )
)

LIST_PAGE = {
    "total": 2,
    "jobPostings": [
        {
            "title": "Software Engineer",
            "externalPath": "/job/Austin/Software-Engineer_R-1",
            "locationsText": "Austin, TX",
            "postedOn": "Posted Today",
        },
        {
            "title": "Data Scientist",
            "externalPath": "/job/Remote/Data-Scientist_R-2",
            "locationsText": "Remote",
            "postedOn": "Posted 3 Days Ago",
        },
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


def test_default_facets_dir_falls_back_without_context():
    assert workday.default_facets_dir() == workday._FACETS_DIR


def test_default_facets_dir_resolves_per_tenant_workspace(tmp_path):
    from resume_agent.config import Settings
    from resume_agent.tenancy.context import UserContext, use_context
    from resume_agent.tenancy.workspace import WorkspacePaths

    root = tmp_path / "users" / "abc123def456"
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(root),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    with use_context(context):
        assert workday.default_facets_dir() == root / "workday_facets"


def test_cxs_jobs_url_is_built_from_triple():
    assert (
        cxs_jobs_url(TARGET)
        == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    )


def test_list_request_body_shapes_search_text():
    body = list_request_body(SearchConfig(titles=["Software Engineer"]), offset=20)
    assert body == {
        "appliedFacets": {},
        "limit": 20,
        "offset": 20,
        "searchText": "Software Engineer",
    }


def test_list_request_body_empty_search_text_when_no_terms():
    assert list_request_body(SearchConfig(), offset=0)["searchText"] == ""


def test_parse_list_rows_yields_partial_rawjobs():
    rows = parse_list_rows(TARGET, LIST_PAGE)
    assert [r.title for r in rows] == ["Software Engineer", "Data Scientist"]
    first = rows[0]
    assert first.source == "workday"
    assert first.company == "acme"
    assert first.location == "Austin, TX"
    assert (
        first.url
        == "https://acme.wd5.myworkdayjobs.com/job/Austin/Software-Engineer_R-1"
    )
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


def test_apply_detail_keeps_every_workday_location():
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    detail = {
        **DETAIL,
        "jobPostingInfo": {
            **DETAIL["jobPostingInfo"],
            "additionalLocations": [
                {"descriptor": "Chicago, IL"},
                {"descriptor": "Austin, TX"},
                "Remote - US",
            ],
        },
    }

    apply_detail(row, detail)

    assert row.location == "Austin, TX | Chicago, IL | Remote - US"


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

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        return _Resp(
            LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []}
        )

    def fake_get(url: str, **kwargs: object) -> _Resp:
        detail_calls.append(url)
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", fake_get)
    search = SearchConfig(role_anchors=["Software Engineer"])
    jobs = workday.fetch_workday(TARGET, search)

    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 1
    assert "Python" in jobs[0].jd_text


def test_fetch_workday_applies_keyword_filter_after_detail(monkeypatch):
    detail_calls = []

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        return _Resp(
            LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []}
        )

    def fake_get(url: str, **kwargs: object) -> _Resp:
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

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", fake_get)
    jobs = workday.fetch_workday(TARGET, SearchConfig(keywords=["Python"]))

    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 2


def test_fetch_workday_request_is_search_shaped(monkeypatch):
    sent = {}

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        sent.setdefault("searchText", json["searchText"])
        return _Resp(
            LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []}
        )

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    workday.fetch_workday(
        TARGET, SearchConfig(titles=["Software Engineer"], role_anchors=["Engineer"])
    )
    assert sent["searchText"] == "Software Engineer"


def test_fetch_workday_honors_limit(monkeypatch):
    page = {"total": 2, "jobPostings": LIST_PAGE["jobPostings"]}

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        return _Resp(page if json["offset"] == 0 else {"total": 2, "jobPostings": []})

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    jobs = workday.fetch_workday(TARGET, SearchConfig(), limit=1)
    assert len(jobs) == 1


def test_fetch_workday_isolates_failed_detail_fetch(monkeypatch):
    """A failing detail (N+1) fetch skips only that row, not the whole company."""
    second_detail = {
        "jobPostingInfo": {
            "jobDescription": "<p>Analyze data.</p>",
            "externalUrl": "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-2",
        }
    }

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        return _Resp(
            LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []}
        )

    def fake_get(url: str, **kwargs: object) -> _Resp:
        if "Software-Engineer" in url:
            raise httpx.HTTPStatusError(
                "500", request=httpx.Request("GET", url), response=httpx.Response(500)
            )
        return _Resp(second_detail)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", fake_get)
    jobs = workday.fetch_workday(TARGET, SearchConfig())
    assert [j.title for j in jobs] == ["Data Scientist"]


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Neutralize retry backoff so throttle-retry paths don't slow the suite."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def _response(status: int, *, headers=None, payload=None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        json=payload if payload is not None else {},
        request=httpx.Request("POST", "https://acme.wd5.myworkdayjobs.com/x"),
    )


def test_checked_raises_when_the_pool_exhausted_its_retries():
    """The retry policy itself is shared; what stays here is the raise.

    ``BoardSession`` returns the last transient response rather than raising,
    so a persistently throttled board has to surface as an HTTPStatusError here
    for the companies connector to isolate it per URL. Policy coverage (backoff,
    Retry-After, bounded attempts, no retry on 404) lives in
    tests/test_board_session.py.
    """
    with pytest.raises(httpx.HTTPStatusError):
        workday._checked(_response(429))


def test_checked_raises_on_a_non_transient_status():
    with pytest.raises(httpx.HTTPStatusError):
        workday._checked(_response(404))


def test_checked_passes_a_successful_response_through():
    response = _response(200, payload={"ok": True})
    assert workday._checked(response) is response


def test_workday_inherits_the_shared_retry_constants():
    from resume_agent.discovery.connectors import http as board

    assert workday._RETRY_STATUSES is board.RETRY_STATUSES
    assert workday._RETRY_ATTEMPTS == board.RETRY_ATTEMPTS


def test_fetch_workday_recovers_when_list_page_throttled(monkeypatch):
    """A transient 429 on the list POST is retried, not fatal to the pull.

    Driven through a real BoardSession over a scripted transport: the retry now
    lives in the pool, so patching ``board.post`` would replace the very layer
    under test.
    """
    from resume_agent.discovery.connectors.http import BoardSession, board_session

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    attempts: list[str] = []

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            attempts.append(request.method)
            if request.method == "GET":
                return httpx.Response(200, json=DETAIL, request=request)
            if attempts.count("POST") == 1:
                return httpx.Response(429, request=request)
            offset = json_module.loads(request.content.decode())["offset"]
            payload = LIST_PAGE if offset == 0 else {"total": 2, "jobPostings": []}
            return httpx.Response(200, json=payload, request=request)

    with board_session(BoardSession(transport=_Transport())):
        jobs = workday.fetch_workday(TARGET, SearchConfig())

    assert [j.title for j in jobs] == ["Software Engineer", "Data Scientist"]
    assert attempts.count("POST") >= 2  # first POST throttled, retried to success


def test_apply_detail_updates_company_name(monkeypatch):
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    assert row.company == "acme"
    apply_detail(
        row,
        {
            **DETAIL,
            "jobPostingInfo": {**DETAIL["jobPostingInfo"], "companyName": "Acme Corp"},
        },
    )
    assert row.company == "Acme Corp"


def test_resolve_location_facets_matches_location_descriptors():
    assert workday.resolve_location_facets(FACETED_PAGE, ["Austin, TX"]) == {
        "locations": ["loc-austin"]
    }


def test_resolve_location_facets_requires_every_requested_location():
    assert (
        workday.resolve_location_facets(FACETED_PAGE, ["Austin, TX", "Boston, MA"])
        == {}
    )


def test_resolve_location_facets_ignores_non_location_facets():
    assert workday.resolve_location_facets(FACETED_PAGE, ["Engineering"]) == {}
    assert workday.resolve_location_facets(FACETED_PAGE, []) == {}


def test_resolve_location_facets_rejects_short_ambiguous_substrings():
    """A 2-letter wanted location must not fuzzy-match an unrelated descriptor
    just because it happens to appear inside it (e.g. "us" inside "Austin")."""
    assert workday.resolve_location_facets(FACETED_PAGE, ["us"]) == {}


def test_facet_cache_roundtrip_and_location_invalidation(tmp_path):
    applied = {"locations": ["loc-austin"]}
    workday.save_cached_facets(TARGET, ["Austin, TX"], applied, base_dir=tmp_path)
    assert (
        workday.load_cached_facets(TARGET, ["Austin, TX"], base_dir=tmp_path) == applied
    )
    assert (
        workday.load_cached_facets(TARGET, ["Detroit, MI"], base_dir=tmp_path) is None
    )


def test_fetch_workday_resolves_then_restarts_with_facets(monkeypatch, tmp_path):
    bodies = []

    def fake_post(url, json=None, **kwargs):
        bodies.append(json)
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    jobs = workday.fetch_workday(
        TARGET,
        SearchConfig(locations=["Austin, TX"]),
        facets_dir=tmp_path,
    )
    assert bodies == [
        {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
        {
            "appliedFacets": {"locations": ["loc-austin"]},
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    ]
    assert [job.title for job in jobs] == ["Software Engineer"]


def test_fetch_workday_cached_miss_stays_plain(monkeypatch, tmp_path):
    bodies = []
    workday.save_cached_facets(TARGET, ["Boston, MA"], {}, base_dir=tmp_path)

    def fake_post(url, json=None, **kwargs):
        bodies.append(json)
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    jobs = workday.fetch_workday(
        TARGET,
        SearchConfig(locations=["Boston, MA"]),
        facets_dir=tmp_path,
    )
    assert len(bodies) == 1
    assert bodies[0]["appliedFacets"] == {}
    assert len(jobs) == 1


def test_fetch_workday_empty_faceted_restart_reuses_plain_page(monkeypatch, tmp_path):
    bodies = []

    def fake_post(url: str, json: dict[str, object], **kwargs: object) -> _Resp:
        bodies.append(json)
        if json["appliedFacets"]:
            return _Resp({"total": 0, "jobPostings": []})
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    jobs = workday.fetch_workday(
        TARGET,
        SearchConfig(locations=["Austin, TX"]),
        facets_dir=tmp_path,
    )
    assert len(bodies) == 2
    assert [job.title for job in jobs] == ["Software Engineer"]
    assert workday.load_cached_facets(TARGET, ["Austin, TX"], base_dir=tmp_path) == {}


def test_fetch_workday_cache_write_failure_falls_back_plain(monkeypatch, tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("x", encoding="utf-8")
    bodies = []

    def fake_post(url, json=None, **kwargs):
        bodies.append(json)
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.board, "post", fake_post)
    monkeypatch.setattr(workday.board, "get", lambda url, **kwargs: _Resp(DETAIL))
    jobs = workday.fetch_workday(
        TARGET,
        SearchConfig(locations=["Austin, TX"]),
        facets_dir=blocking_file,
    )
    assert len(bodies) == 1
    assert bodies[0]["appliedFacets"] == {}
    assert len(jobs) == 1


def test_apply_detail_reads_top_level_hiring_organization():
    """Workday moved the employer name out of ``jobPostingInfo``.

    Measured live on four tenants (generalmotors, phinia, toyota, nvidia):
    ``jobPostingInfo.companyName`` is ``null`` on every one, and the real name
    sits at the payload's top level under ``hiringOrganization.name``. Reading
    only the old key left every row's company as the URL slug with
    ``company_provenance == "token"`` -- which is what Scout's board
    verification keys ownership on, so no Workday board could ever verify.
    """
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    assert row.company == "acme"
    apply_detail(
        row, {**DETAIL, "hiringOrganization": {"name": "Acme Corp LLC", "url": ""}}
    )
    assert row.company == "Acme Corp LLC"
    assert row.company_provenance == "provider"
    assert row.stale_company == "acme"


def test_apply_detail_prefers_company_name_when_a_tenant_still_sets_it():
    """The old key wins when present -- the fallback must not override a
    tenant that still populates ``companyName``."""
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    apply_detail(
        row,
        {
            **DETAIL,
            "jobPostingInfo": {**DETAIL["jobPostingInfo"], "companyName": "Acme Corp"},
            "hiringOrganization": {"name": "Acme Holdings International"},
        },
    )
    assert row.company == "Acme Corp"
    assert row.company_provenance == "provider"


def test_apply_detail_ignores_a_blank_hiring_organization():
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    apply_detail(row, {**DETAIL, "hiringOrganization": {"name": "   ", "url": ""}})
    assert row.company == "acme"
    assert row.company_provenance == "token"


def test_workday_detail_renders_time_and_remote_type():
    """`timeType` and `remoteType` are the only statement of the employment and
    workplace types -- neither appears in `jobDescription`."""
    from resume_agent.discovery.connectors.workday import WorkdayRow, apply_detail

    row = WorkdayRow(
        source="workday",
        url=None,
        company="GM",
        title="Engineer",
        location="2 Locations",
        jd_text="",
    )
    apply_detail(
        row,
        {
            "jobPostingInfo": {
                "jobDescription": "<p>Build cars.</p>",
                "location": "Warren, Michigan, United States of America",
                "additionalLocations": [{"descriptor": "Austin, Texas"}],
                "timeType": "Full time",
                "remoteType": "Hybrid",
                "jobFamily": "Engineering",
                "jobReqId": "JR-42",
                "postedOn": "Posted Today",
            }
        },
    )
    header = row.jd_text.split("\n\n")[0].splitlines()

    assert "Location: Warren, Michigan, United States of America" in header
    assert "Workplace Type: Hybrid" in header
    assert "Employment Type: Full time" in header
    assert "Additional Locations: Austin, Texas" in header
    assert "Department: Engineering" in header
    assert "Requisition ID: JR-42" in header
    assert "Posted: Posted Today" in header
    assert "Build cars." in row.jd_text
