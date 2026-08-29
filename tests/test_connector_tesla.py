import json
from contextlib import nullcontext
from pathlib import Path

import resume_agent.discovery.connectors.tesla as tesla
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("tesla")
FIXTURES = Path(__file__).parent / "fixtures" / "tesla"
STATE = json.loads((FIXTURES / "state.json").read_text(encoding="utf-8"))
DETAILS = {
    listing_id: json.loads(
        (FIXTURES / f"detail-{listing_id}.json").read_text(encoding="utf-8")
    )
    for listing_id in ("1", "2")
}


class _FakePortal:
    def __init__(self, state=STATE, details=DETAILS, fail_ids=()):
        self.state = state
        self._details = details
        self._fail = set(fail_ids)
        self.detail_calls = []

    def job_detail(self, listing_id):
        self.detail_calls.append(listing_id)
        if listing_id in self._fail:
            raise RuntimeError("detail 403")
        return self._details[listing_id]


def _use(monkeypatch, portal):
    monkeypatch.setattr(tesla, "open_portal", lambda: nullcontext(portal))
    return portal


def test_parse_tesla_listings_to_partial_rawjobs():
    rows = tesla.parse_listings(STATE)
    assert [row.title for row in rows] == ["Software Engineer", "Welder"]
    assert rows[0].source == "tesla"
    assert rows[0].company == "Tesla"
    assert rows[0].location == "Palo Alto, California"  # resolved from lookup code
    assert rows[0].listing_id == "1"
    assert rows[0].jd_text == ""


def test_parse_tesla_listings_compact_keys():
    compact_state = {
        "listings": [{"id": "3", "t": "ML Engineer", "l": "Palo Alto, CA"}]
    }
    rows = tesla.parse_listings(compact_state)
    assert rows[0].title == "ML Engineer"
    assert rows[0].location == "Palo Alto, CA"


def test_fetch_tesla_gates_then_details(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(role_anchors=["Software Engineer"]))
    assert [job.title for job in jobs] == ["Software Engineer"]
    assert portal.detail_calls == ["1"]
    assert "Python" in jobs[0].jd_text


def test_fetch_tesla_applies_keyword_filter_after_detail(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(keywords=["Python"]))
    assert [job.title for job in jobs] == ["Software Engineer"]
    assert portal.detail_calls == ["1", "2"]


def test_fetch_tesla_isolates_failed_detail_fetch(monkeypatch):
    _use(monkeypatch, _FakePortal(fail_ids={"1"}))
    jobs = tesla.fetch_tesla(TARGET, SearchConfig())
    assert [job.title for job in jobs] == ["Welder"]


def test_fetch_tesla_respects_limit(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(), limit=1)
    assert len(jobs) == 1
    assert portal.detail_calls == ["1"]


def test_apply_tesla_detail_assembles_jd_and_absolutizes_url():
    row = tesla.TeslaRow(
        source="tesla",
        url=None,
        company="Tesla",
        title="SWE",
        location="Palo Alto, California",
        jd_text="",
        listing_id="1",
    )
    tesla.apply_tesla_detail(row, DETAILS["1"])
    assert "Python" in row.jd_text  # from jobDescription, not the empty description
    assert "shipping software" in row.jd_text  # jobRequirements folded in too
    assert row.url == "https://www.tesla.com/careers/search/job/software-engineer-1"


def test_capture_state_retries_past_transient_denial(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(tesla.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def flaky(_page):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Access Denied")
        return STATE

    monkeypatch.setattr(tesla, "_capture_once", flaky)
    assert tesla._capture_state(object(), attempts=3, backoff_s=0.1) is STATE
    assert calls["n"] == 3
    assert sleeps == [0.1, 0.1]  # backed off between the two failures


def test_capture_state_raises_isolable_error_when_exhausted(monkeypatch):
    monkeypatch.setattr(tesla.time, "sleep", lambda s: None)

    def always_denied(_page):
        raise RuntimeError("Access Denied")

    monkeypatch.setattr(tesla, "_capture_once", always_denied)
    try:
        tesla._capture_state(object(), attempts=2, backoff_s=0.0)
    except tesla.TeslaStateUnavailable as error:
        assert isinstance(error.__cause__, RuntimeError)
    else:  # pragma: no cover - failure path must raise
        raise AssertionError("expected TeslaStateUnavailable")


def test_tesla_block_is_isolated_not_fatal_to_the_pull():
    from resume_agent.discovery.connectors.companies import _failure_reason

    reason = _failure_reason(tesla.TeslaStateUnavailable("blocked"))
    assert reason is not None  # a reason string means harvest records, not re-raises
    assert "Akamai" in reason


def test_tesla_portal_runs_same_origin_detail_fetch():
    class _Page:
        def __init__(self):
            self.calls = []

        def evaluate(self, script, argument):
            self.calls.append((script, argument))
            return DETAILS["1"]

    page = _Page()
    portal = tesla.TeslaPortal(page, STATE)
    assert portal.job_detail("1") == DETAILS["1"]
    assert page.calls[0][1].endswith("/cua-api/careers/job/1")
    assert "fetch(url" in page.calls[0][0]
