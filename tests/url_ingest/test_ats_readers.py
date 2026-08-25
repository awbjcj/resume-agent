import json
from pathlib import Path

import httpx

from resume_agent.discovery.connectors.detect import AtsTarget, identify_host
from resume_agent.discovery.url_ingest import ats_readers
from resume_agent.discovery.url_ingest.ats_readers import ATS_READERS, _from_json_ld

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")


def _fixture_json(*parts: str) -> dict:
    return json.loads(_fixture(*parts))


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fail(*a, **kw):
    raise AssertionError("network should not be reached")


# -- shared JSON-LD helper --------------------------------------------------


def test_from_json_ld_maps_core_fields():
    html = _fixture("jazzhr", "detail.html")
    extracted = _from_json_ld(html)
    assert extracted is not None
    assert extracted.title == "Application Engineer, Data Center Software"
    assert extracted.company == "Utilidata"
    assert extracted.location == "Remote"
    assert "data center software" in extracted.jd_text.lower()


def test_from_json_ld_reads_job_location_address():
    html = _fixture("breezy", "detail.html")
    extracted = _from_json_ld(html)
    assert extracted is not None
    assert extracted.location == "New York, NY"


def test_from_json_ld_keeps_every_job_location():
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
        '"description":"<p>Build things.</p>","jobLocation":['
        '{"address":{"addressLocality":"Austin","addressRegion":"TX",'
        '"addressCountry":"US"}},{"address":{"addressLocality":"New York",'
        '"addressRegion":"NY","addressCountry":"US"}}]}</script>'
    )

    extracted = _from_json_ld(html)

    assert extracted is not None
    assert extracted.location == "Austin, TX, US | New York, NY, US"


def test_from_json_ld_absent_returns_none():
    assert _from_json_ld("<html><body>nothing here</body></html>") is None


# -- greenhouse (delegates to the existing HTML reader) ---------------------


def test_greenhouse_reader_delegates_to_html_scraper():
    html = (
        '<html><body><h1 class="app-title">Dev</h1>'
        '<span class="company-name">at Hooli</span>'
        '<div class="location">SF</div>'
        '<div id="content"><p>Write code.</p></div></body></html>'
    )
    target = AtsTarget("greenhouse", token="hooli")
    extracted = ATS_READERS["greenhouse"](target, "https://boards.greenhouse.io/hooli/jobs/1", html)
    assert extracted is not None
    assert extracted.title == "Dev"
    assert extracted.company == "Hooli"


def test_greenhouse_reader_resolves_the_board_display_name(monkeypatch):
    # The board slug ("hooli") differs from the org's display name
    # ("Hooli, Inc"); the API path must resolve it the same way
    # GreenhouseConnector does so add-from-URL dedupes against board pulls.
    job = {"title": "Dev", "location": {"name": "SF"}, "content": "<p>Write code.</p>"}
    board = {"name": "Hooli, Inc"}

    def fake_get(url, **kw):
        return _Resp(board if url.endswith("/v1/boards/hooli") else job)

    monkeypatch.setattr(ats_readers.board, "get", fake_get)
    target = AtsTarget("greenhouse", token="hooli")
    extracted = ATS_READERS["greenhouse"](target, "https://boards.greenhouse.io/hooli/jobs/1", "<html></html>")
    assert extracted is not None
    assert extracted.company == "Hooli, Inc"


def test_greenhouse_reader_falls_back_to_token_when_board_name_lookup_fails(monkeypatch):
    job = {"title": "Dev", "location": {"name": "SF"}, "content": "<p>Write code.</p>"}

    def fake_get(url, **kw):
        if url.endswith("/v1/boards/hooli"):
            raise httpx.ConnectError("down")
        return _Resp(job)

    monkeypatch.setattr(ats_readers.board, "get", fake_get)
    target = AtsTarget("greenhouse", token="hooli")
    extracted = ATS_READERS["greenhouse"](target, "https://boards.greenhouse.io/hooli/jobs/1", "<html></html>")
    assert extracted is not None
    assert extracted.company == "hooli"


# -- ashby: JSON-LD fast path, then board-API fallback -----------------------


_ASHBY_JSON_LD = (
    '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
    '"description":"<p>Build things.</p>","hiringOrganization":{"name":"Acme"}}</script>'
)


def test_ashby_falls_back_to_json_ld_when_the_board_api_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        ats_readers, "fetch_ashby_board",
        lambda token: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    target = AtsTarget("ashby", token="acme")
    extracted = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/abc-123", _ASHBY_JSON_LD)
    assert extracted is not None
    assert extracted.title == "Eng"
    assert extracted.company == "Acme"
    assert "Build things." in extracted.jd_text


def test_ashby_prefers_the_board_api_over_json_ld_for_its_sidebar_facts(monkeypatch):
    # The board API is the ONLY source carrying compensation, workplace type,
    # employment type, and department -- the job page's sidebar. JSON-LD has a
    # description and nothing else, so preferring it silently dropped them.
    payload = {
        "jobs": [
            {
                "id": "abc-123",
                "title": "Senior ML Engineer",
                "location": "New York",
                "workplaceType": "Hybrid",
                "employmentType": "FullTime",
                "department": "Engineering",
                "compensation": {"compensationTierSummary": "$200K - $250K"},
                "descriptionPlain": "Build LLM systems.",
            }
        ]
    }
    monkeypatch.setattr(ats_readers, "fetch_ashby_board", lambda token: payload)
    target = AtsTarget("ashby", token="acme")
    extracted = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/abc-123", _ASHBY_JSON_LD)
    assert extracted is not None
    assert extracted.title == "Senior ML Engineer"
    assert "Compensation: $200K - $250K" in extracted.jd_text
    assert "Workplace Type: Hybrid" in extracted.jd_text
    assert "Employment Type: Full time" in extracted.jd_text
    assert "Department: Engineering" in extracted.jd_text


def test_ashby_falls_back_to_board_api_and_matches_by_id(monkeypatch):
    payload = {
        "jobs": [
            {"id": "abc-123", "title": "Senior ML Engineer", "location": "Remote - US",
             "descriptionPlain": "Build LLM systems.", "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123"},
            {"id": "def-456", "title": "Other role", "descriptionPlain": "Other.",
             "jobUrl": "https://jobs.ashbyhq.com/acme/def-456"},
        ]
    }
    monkeypatch.setattr(ats_readers, "fetch_ashby_board", lambda token: payload)
    target = AtsTarget("ashby", token="acme")
    extracted = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/abc-123", "<html></html>")
    assert extracted is not None
    assert extracted.title == "Senior ML Engineer"
    assert "Build LLM systems." in extracted.jd_text


def test_ashby_returns_none_when_id_not_found(monkeypatch):
    monkeypatch.setattr(ats_readers, "fetch_ashby_board", lambda token: {"jobs": []})
    target = AtsTarget("ashby", token="acme")
    extracted = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/missing", "<html></html>")
    assert extracted is None


# -- lever: single-posting endpoint ------------------------------------------


def test_lever_falls_back_to_single_posting_endpoint(monkeypatch):
    posting = {
        "id": "abc-123",
        "text": "Senior Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "categories": {"location": "Remote - US"},
        "description": "<p>Build payment systems.</p>",
        "lists": [],
        "additional": "",
    }
    monkeypatch.setattr(ats_readers, "fetch_lever_posting", lambda token, pid: posting)
    target = AtsTarget("lever", token="acme")
    extracted = ATS_READERS["lever"](target, "https://jobs.lever.co/acme/abc-123", "<html></html>")
    assert extracted is not None
    assert extracted.title == "Senior Backend Engineer"
    assert "payment systems" in extracted.jd_text


# -- smartrecruiters: direct detail endpoint ---------------------------------


def test_smartrecruiters_falls_back_to_detail_endpoint(monkeypatch):
    detail = {
        "name": "Senior Product Manager (Career Sites)",
        "company": {"name": "SmartRecruiters Inc"},
        "location": {"city": "United States", "region": "REMOTE", "country": "us"},
        "jobAd": {"sections": {"jobDescription": {"text": "<p>Build a great product.</p>"}}},
    }
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("smartrecruiters", token="smartrecruiters")
    url = "https://jobs.smartrecruiters.com/smartrecruiters/744000134902606-senior-product-manager"
    extracted = ATS_READERS["smartrecruiters"](target, url, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Senior Product Manager (Career Sites)"
    assert extracted.company == "SmartRecruiters Inc"
    assert "great product" in extracted.jd_text


# -- workable: account listing filtered by shortcode -------------------------


# The bare "apply.workable.com/j/{code}" form carries no account slug, so
# detect._l1 deliberately refuses it (there is no token to call the widget API
# with) and it never reaches this reader. Drive the account-qualified form,
# which is what detect actually resolves to a workable target.
_WORKABLE_URL = "https://apply.workable.com/acme/j/5656BF6FBE"


def test_workable_url_form_under_test_is_one_detect_actually_resolves():
    target = identify_host(_WORKABLE_URL)
    assert target is not None
    assert (target.ats, target.token) == ("workable", "acme")
    # ...and the bare form is refused, so no reader runs for it.
    assert identify_host("https://apply.workable.com/j/5656BF6FBE") is None


def test_workable_falls_back_to_account_listing_by_shortcode(monkeypatch):
    payload = _fixture_json("workable", "account.json")
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("workable", token="acme")
    extracted = ATS_READERS["workable"](target, _WORKABLE_URL, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Senior Software Engineer"
    assert "Python" in extracted.jd_text


def test_workable_keeps_requirements_and_benefits_sections(monkeypatch):
    # `details=true` returns these as fields siblings of `description`; mapping
    # only `description` dropped the entire qualifications block.
    payload = {
        "name": "Acme",
        "jobs": [
            {
                "title": "Engineer",
                "shortcode": "5656BF6FBE",
                "description": "<p>Build services.</p>",
                "requirements": "<p>5 years of Python.</p>",
                "benefits": "<p>Full health cover.</p>",
                "employment_type": "Full-time",
                "department": "Engineering",
            }
        ],
    }
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("workable", token="acme")
    extracted = ATS_READERS["workable"](target, _WORKABLE_URL, "<html></html>")
    assert extracted is not None
    assert "5 years of Python." in extracted.jd_text
    assert "Full health cover." in extracted.jd_text
    assert "Employment Type: Full-time" in extracted.jd_text
    assert extracted.jd_text.count("Employment Type: Full-time") == 1
    assert extracted.jd_text.count("Department: Engineering") == 1


def test_workable_returns_none_when_shortcode_not_found(monkeypatch):
    payload = _fixture_json("workable", "account.json")
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("workable", token="acme")
    url = "https://apply.workable.com/acme/j/NOTREAL"
    assert ATS_READERS["workable"](target, url, "<html></html>") is None


# -- personio: full-list filtered by position id -----------------------------


def test_personio_falls_back_to_search_filtered_by_id(monkeypatch):
    payload_text = _fixture("personio", "search.json")

    class _TextResp:
        def raise_for_status(self):
            return None

        @property
        def text(self):
            return payload_text

    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _TextResp())
    target = AtsTarget("personio", token="pitch", country="com")
    url = "https://pitch.jobs.personio.com/job/160959"
    extracted = ATS_READERS["personio"](target, url, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Frontend Performance Engineer"
    assert "React performance profiling" in extracted.jd_text


# -- bamboohr: detail endpoint keyed by opening id ---------------------------


def test_bamboohr_falls_back_to_detail_endpoint(monkeypatch):
    detail = _fixture_json("bamboohr", "detail.json")
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("bamboohr", token="eleven")
    url = "https://eleven.bamboohr.com/careers/132"
    extracted = ATS_READERS["bamboohr"](target, url, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Senior AI Engineer"
    assert "AI-powered engineering workflows" in extracted.jd_text


# -- recruitee / breezy / jazzhr: JSON-LD only -------------------------------


def test_recruitee_reads_json_ld_from_the_pasted_page():
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Support Eng",'
        '"description":"<p>Help customers.</p>","hiringOrganization":{"name":"Channable"}}</script>'
    )
    target = AtsTarget("recruitee", token="channable")
    extracted = ATS_READERS["recruitee"](target, "https://channable.recruitee.com/o/x", html)
    assert extracted is not None
    assert extracted.title == "Support Eng"
    assert extracted.company == "Channable"


def test_breezy_reads_json_ld_fixture():
    html = _fixture("breezy", "detail.html")
    target = AtsTarget("breezy", token="masterworks")
    extracted = ATS_READERS["breezy"](target, "https://masterworks.breezy.hr/p/x", html)
    assert extracted is not None
    assert extracted.title == "Art Tour Guide"


def test_jazzhr_reads_json_ld_fixture():
    html = _fixture("jazzhr", "detail.html")
    target = AtsTarget("jazzhr", token="utilidata")
    extracted = ATS_READERS["jazzhr"](target, "https://utilidata.applytojob.com/apply/x", html)
    assert extracted is not None
    assert extracted.title == "Application Engineer, Data Center Software"


# -- workday: cxs detail endpoint from a derived external_path ---------------


def test_workday_falls_back_to_cxs_detail_endpoint(monkeypatch):
    detail = {
        "jobPostingInfo": {
            "title": "Software Engineer",
            "jobDescription": "<p>Build vehicle software.</p>",
            "location": "Detroit, Michigan",
        }
    }
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM")
    url = "https://generalmotors.wd5.myworkdayjobs.com/en-US/Careers_GM/job/Detroit-Michigan/Software-Engineer_R123"
    extracted = ATS_READERS["workday"](target, url, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Software Engineer"
    assert extracted.company == "generalmotors"
    assert "vehicle software" in extracted.jd_text


def test_workday_returns_none_when_url_has_no_matching_site():
    target = AtsTarget("workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM")
    url = "https://generalmotors.wd5.myworkdayjobs.com/en-US/OtherSite/job/x"
    assert ATS_READERS["workday"](target, url, "<html></html>") is None


_WORKDAY_TARGET = AtsTarget(
    "workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM"
)
_WORKDAY_URL = (
    "https://generalmotors.wd5.myworkdayjobs.com/en-US/Careers_GM"
    "/job/Detroit-Michigan/Software-Engineer_R123"
)


def test_workday_prefers_the_payload_company_name_over_the_tenant_slug(monkeypatch):
    # target.tenant is a URL slug ("generalmotors"); storing it as the company
    # breaks dedup against the same requisition pulled by the board connector,
    # whose dedup_key is normalize(company)|normalize_title(title).
    detail = {
        "jobPostingInfo": {
            "title": "Software Engineer",
            "companyName": "General Motors",
            "jobDescription": "<p>Build vehicle software.</p>",
        }
    }
    monkeypatch.setattr(ats_readers, "fetch_job_detail", lambda target, path: detail)
    extracted = ATS_READERS["workday"](_WORKDAY_TARGET, _WORKDAY_URL, "<html></html>")
    assert extracted is not None
    assert extracted.company == "General Motors"


def test_workday_carries_the_header_strip_into_jd_text(monkeypatch):
    detail = {
        "jobPostingInfo": {
            "title": "Software Engineer",
            "location": "Detroit, Michigan",
            "additionalLocations": [{"descriptor": "Chicago, Illinois"}],
            "timeType": "Full time",
            "remoteType": "Hybrid",
            "jobReqId": "JR-12345",
            "postedOn": "Posted 3 Days Ago",
            "jobDescription": "<p>Build vehicle software.</p>",
        }
    }
    monkeypatch.setattr(ats_readers, "fetch_job_detail", lambda target, path: detail)
    extracted = ATS_READERS["workday"](_WORKDAY_TARGET, _WORKDAY_URL, "<html></html>")
    assert extracted is not None
    assert extracted.location == "Detroit, Michigan | Chicago, Illinois"
    assert "Location: Detroit, Michigan" in extracted.jd_text
    assert "Additional Locations: Chicago, Illinois" in extracted.jd_text
    assert "Employment Type: Full time" in extracted.jd_text
    assert "Workplace Type: Hybrid" in extracted.jd_text
    assert "Requisition ID: JR-12345" in extracted.jd_text
    assert "Build vehicle software." in extracted.jd_text


def test_workday_reader_uses_the_throttle_retrying_fetch(monkeypatch):
    # Workday boards throttle hard; a bare httpx.get would drop a pasted URL on
    # the first 429 while the same job pulled from the board would retry.
    calls: list[str] = []

    def _detail(target, external_path):
        calls.append(external_path)
        return {"jobPostingInfo": {"title": "X", "jobDescription": "<p>Body.</p>"}}

    monkeypatch.setattr(ats_readers, "fetch_job_detail", _detail)
    monkeypatch.setattr(ats_readers.board, "get", _fail)
    assert ATS_READERS["workday"](_WORKDAY_TARGET, _WORKDAY_URL, "<html></html>") is not None
    assert calls == ["/job/Detroit-Michigan/Software-Engineer_R123"]


# -- the null contract every reader owes service.job_from_url ----------------


def test_readers_return_none_rather_than_an_empty_job_when_the_api_fails(monkeypatch):
    # service.job_from_url falls back to the LLM only on None. An ExtractedJob
    # carrying company/title but no jd_text suppressed that fallback, so the
    # add-from-URL failed even though the JD sat in the static HTML.
    json_ld_without_description = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
        '"hiringOrganization":{"name":"Acme"}}</script>'
    )
    monkeypatch.setattr(
        ats_readers, "fetch_ashby_board",
        lambda token: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    target = AtsTarget("ashby", token="acme")
    result = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/abc", json_ld_without_description)
    assert result is None


def test_a_non_json_api_response_is_a_miss_not_an_exception(monkeypatch):
    # A maintenance page or bot interstitial served with status 200 raises
    # ValueError out of .json() -- not httpx.HTTPError -- which propagated out
    # of job_from_url as a 500 on add-from-URL.
    class _HtmlResp:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _HtmlResp())
    target = AtsTarget("smartrecruiters", token="acme")
    url = "https://jobs.smartrecruiters.com/acme/744000134902606-engineer"
    assert ATS_READERS["smartrecruiters"](target, url, "<html></html>") is None


# -- JSON-LD top-bar fields --------------------------------------------------


def test_json_ld_renders_the_pay_band_and_employment_type():
    # schema.org carries these as dedicated fields; mapping only `description`
    # lost the salary and employment type for every JSON-LD-backed board.
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
        '"description":"<p>Build things.</p>","hiringOrganization":{"name":"Acme"},'
        '"employmentType":"FULL_TIME","jobLocationType":"TELECOMMUTE",'
        '"applicantLocationRequirements":{"@type":"Country","name":"USA"},'
        '"occupationalCategory":"Engineering",'
        '"baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":'
        '{"@type":"QuantitativeValue","minValue":200000,"maxValue":250000,"unitText":"YEAR"}}}'
        "</script>"
    )
    extracted = _from_json_ld(html)
    assert extracted is not None
    assert "Employment Type: Full time" in extracted.jd_text
    assert "Workplace Type: Remote (USA)" in extracted.jd_text
    assert "Department: Engineering" in extracted.jd_text
    assert "Compensation: USD 200,000 - 250,000 per year" in extracted.jd_text
    assert "Build things." in extracted.jd_text


def test_json_ld_without_extras_still_yields_a_bare_description():
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
        '"description":"<p>Build things.</p>"}</script>'
    )
    extracted = _from_json_ld(html)
    assert extracted is not None
    assert extracted.jd_text == "Build things."


# -- recruitee: the offers feed carries the requirements block ---------------


def test_recruitee_prefers_the_offers_api_which_keeps_requirements(monkeypatch):
    # Recruitee splits qualifications into a `requirements` field; the page's
    # JSON-LD `description` alone omits the whole section.
    payload = {
        "offers": [
            {
                "careers_url": "https://channable.recruitee.com/o/support-engineer",
                "title": "Support Eng",
                "company_name": "Channable",
                "location": "Utrecht",
                "description": "<p>Help customers.</p>",
                "requirements": "<p>3 years of SQL.</p>",
            }
        ]
    }
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("recruitee", token="channable")
    url = "https://channable.recruitee.com/o/support-engineer"
    extracted = ATS_READERS["recruitee"](target, url, "<html></html>")
    assert extracted is not None
    assert "Help customers." in extracted.jd_text
    assert "3 years of SQL." in extracted.jd_text


def test_recruitee_matches_the_offer_slug_exactly_not_as_a_substring(monkeypatch):
    # "/o/engineer" is a substring of "/o/senior-engineer", so a naive `in`
    # check must not let the longer offer's slug shadow the requested one.
    payload = {
        "offers": [
            {
                "careers_url": "https://channable.recruitee.com/o/senior-engineer",
                "title": "Senior Engineer",
                "company_name": "Channable",
                "description": "<p>Lead the team.</p>",
            },
            {
                "careers_url": "https://channable.recruitee.com/o/engineer",
                "title": "Engineer",
                "company_name": "Channable",
                "description": "<p>Write code.</p>",
            },
        ]
    }
    monkeypatch.setattr(ats_readers.board, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("recruitee", token="channable")
    url = "https://channable.recruitee.com/o/engineer"
    extracted = ATS_READERS["recruitee"](target, url, "<html></html>")
    assert extracted is not None
    assert extracted.title == "Engineer"
    assert "Write code." in extracted.jd_text


def test_recruitee_falls_back_to_json_ld_when_the_offers_feed_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        ats_readers.board, "get",
        lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Support Eng",'
        '"description":"<p>Help customers.</p>","hiringOrganization":{"name":"Channable"}}</script>'
    )
    target = AtsTarget("recruitee", token="channable")
    extracted = ATS_READERS["recruitee"](target, "https://channable.recruitee.com/o/x", html)
    assert extracted is not None
    assert extracted.title == "Support Eng"


# -- smartrecruiters URL shapes ----------------------------------------------


def test_smartrecruiters_posting_id_handles_every_public_url_shape():
    parse = ats_readers._smartrecruiters_posting_id
    assert parse("https://jobs.smartrecruiters.com/acme/744000134902606-engineer") == "744000134902606"
    assert parse("https://careers.smartrecruiters.com/acme/744000134902606") == "744000134902606"
    # A dashed UUID id must not be truncated at its first "-".
    assert (
        parse("https://jobs.smartrecruiters.com/oneclick-ui/company/acme/publication/8f1e-4b2c-9d3a")
        == "8f1e-4b2c-9d3a"
    )


def test_smartrecruiters_oneclick_url_resolves_the_real_company(monkeypatch):
    # detect.py reads the first path segment as the token, which is the literal
    # "oneclick-ui" for this form; the company sits after /company/.
    seen: list[str] = []

    def _get(url, **kw):
        seen.append(url)
        return _Resp({"name": "Engineer", "jobAd": {"sections": {"jobDescription": {"text": "<p>Body.</p>"}}}})

    monkeypatch.setattr(ats_readers.board, "get", _get)
    target = AtsTarget("smartrecruiters", token="oneclick-ui")
    url = "https://jobs.smartrecruiters.com/oneclick-ui/company/acme/publication/8f1e-4b2c"
    extracted = ATS_READERS["smartrecruiters"](target, url, "<html></html>")
    assert extracted is not None
    assert "/companies/acme/postings/8f1e-4b2c" in seen[0]


# -- JSON-LD meta enrichment of a body sourced elsewhere ---------------------

_JSON_LD_PAGE = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"Staff Engineer",
 "description":"<p>Short blurb.</p>",
 "hiringOrganization":{"@type":"Organization","name":"Stripe"},
 "employmentType":"FULL_TIME",
 "jobLocation":[{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"Toronto","addressCountry":"CA"}}],
 "baseSalary":{"@type":"MonetaryAmount","currency":"CAD","value":
   {"@type":"QuantitativeValue","minValue":208000,"maxValue":312000,"unitText":"YEAR"}}}
</script></head><body>page</body></html>
"""


def test_with_json_ld_meta_adds_sidebar_facts_to_foreign_body():
    body = ats_readers.ExtractedJob(company=None, title=None, location=None, jd_text="Full body prose.")
    merged = ats_readers.with_json_ld_meta(body, _JSON_LD_PAGE)
    assert merged is not None
    assert "Location: Toronto, CA" in merged.jd_text
    assert "Employment Type: Full time" in merged.jd_text
    assert "Compensation: CAD 208,000 - 312,000 per year" in merged.jd_text
    # the richer body is kept, not replaced by the JSON-LD description
    assert "Full body prose." in merged.jd_text
    assert "Short blurb." not in merged.jd_text
    # scalar gaps fill from the markup
    assert merged.company == "Stripe"
    assert merged.location == "Toronto, CA"


def test_with_json_ld_meta_does_not_duplicate_labels_the_body_already_has():
    body = ats_readers.ExtractedJob(
        company="Stripe", title="Staff Engineer", location="Toronto",
        jd_text="Location: Toronto, ON\n\nFull body prose.",
    )
    merged = ats_readers.with_json_ld_meta(body, _JSON_LD_PAGE)
    assert merged is not None
    assert merged.jd_text.count("Location:") == 1
    assert "Toronto, ON" in merged.jd_text
    assert "Employment Type: Full time" in merged.jd_text
    assert merged.location == "Toronto"


def test_with_json_ld_meta_passes_through_when_page_has_no_markup():
    body = ats_readers.ExtractedJob(company=None, title=None, location=None, jd_text="Body.")
    assert ats_readers.with_json_ld_meta(body, "<html><body>no markup</body></html>") is body


def test_with_json_ld_meta_keeps_none_none():
    """None is the 'could not resolve' contract service.job_from_url keys on."""
    assert ats_readers.with_json_ld_meta(None, _JSON_LD_PAGE) is None
