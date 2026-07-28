import json
from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
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
    assert extracted.title == "Dev"
    assert extracted.company == "Hooli"


# -- ashby: JSON-LD fast path, then board-API fallback -----------------------


def test_ashby_uses_json_ld_when_present(monkeypatch):
    monkeypatch.setattr(ats_readers, "fetch_ashby_board", _fail)
    target = AtsTarget("ashby", token="acme")
    html = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Eng",'
        '"description":"<p>Build things.</p>","hiringOrganization":{"name":"Acme"}}</script>'
    )
    extracted = ATS_READERS["ashby"](target, "https://jobs.ashbyhq.com/acme/abc-123", html)
    assert extracted.title == "Eng"
    assert extracted.company == "Acme"


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
    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("smartrecruiters", token="smartrecruiters")
    url = "https://jobs.smartrecruiters.com/smartrecruiters/744000134902606-senior-product-manager"
    extracted = ATS_READERS["smartrecruiters"](target, url, "<html></html>")
    assert extracted.title == "Senior Product Manager (Career Sites)"
    assert extracted.company == "SmartRecruiters Inc"
    assert "great product" in extracted.jd_text


# -- workable: account listing filtered by shortcode -------------------------


def test_workable_falls_back_to_account_listing_by_shortcode(monkeypatch):
    payload = _fixture_json("workable", "account.json")
    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("workable", token="acme")
    url = "https://apply.workable.com/j/5656BF6FBE"
    extracted = ATS_READERS["workable"](target, url, "<html></html>")
    assert extracted.title == "Senior Software Engineer"
    assert "Python" in extracted.jd_text


def test_workable_returns_none_when_shortcode_not_found(monkeypatch):
    payload = _fixture_json("workable", "account.json")
    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _Resp(payload))
    target = AtsTarget("workable", token="acme")
    url = "https://apply.workable.com/j/NOTREAL"
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

    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _TextResp())
    target = AtsTarget("personio", token="pitch", country="com")
    url = "https://pitch.jobs.personio.com/job/160959"
    extracted = ATS_READERS["personio"](target, url, "<html></html>")
    assert extracted.title == "Frontend Performance Engineer"
    assert "React performance profiling" in extracted.jd_text


# -- bamboohr: detail endpoint keyed by opening id ---------------------------


def test_bamboohr_falls_back_to_detail_endpoint(monkeypatch):
    detail = _fixture_json("bamboohr", "detail.json")
    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("bamboohr", token="eleven")
    url = "https://eleven.bamboohr.com/careers/132"
    extracted = ATS_READERS["bamboohr"](target, url, "<html></html>")
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
    assert extracted.title == "Support Eng"
    assert extracted.company == "Channable"


def test_breezy_reads_json_ld_fixture():
    html = _fixture("breezy", "detail.html")
    target = AtsTarget("breezy", token="masterworks")
    extracted = ATS_READERS["breezy"](target, "https://masterworks.breezy.hr/p/x", html)
    assert extracted.title == "Art Tour Guide"


def test_jazzhr_reads_json_ld_fixture():
    html = _fixture("jazzhr", "detail.html")
    target = AtsTarget("jazzhr", token="utilidata")
    extracted = ATS_READERS["jazzhr"](target, "https://utilidata.applytojob.com/apply/x", html)
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
    monkeypatch.setattr(ats_readers.httpx, "get", lambda url, **kw: _Resp(detail))
    target = AtsTarget("workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM")
    url = "https://generalmotors.wd5.myworkdayjobs.com/en-US/Careers_GM/job/Detroit-Michigan/Software-Engineer_R123"
    extracted = ATS_READERS["workday"](target, url, "<html></html>")
    assert extracted.title == "Software Engineer"
    assert extracted.company == "generalmotors"
    assert "vehicle software" in extracted.jd_text


def test_workday_returns_none_when_url_has_no_matching_site():
    target = AtsTarget("workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM")
    url = "https://generalmotors.wd5.myworkdayjobs.com/en-US/OtherSite/job/x"
    assert ATS_READERS["workday"](target, url, "<html></html>") is None
