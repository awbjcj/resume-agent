import httpx
import pytest

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.harvest import (
    FetchResult,
    gate_and_limit,
    harvest,
    harvest_detailed,
)
from resume_tailor_harness.discovery.search_config import SearchConfig

_ANCHORED = SearchConfig(role_anchors=["engineer"])


def _job(title: str, url: str = "u") -> RawJob:
    return RawJob(
        source="x", url=url, company="Acme", title=title, location=None, jd_text="jd"
    )


def test_harvest_fans_out_and_concatenates_in_order():
    result = harvest(
        ["a", "b"],
        lambda unit: [_job(f"{unit} Engineer")],
        search=_ANCHORED,
        limit=None,
        key=lambda unit: unit,
        on_error=lambda exc: None,
    )
    assert isinstance(result, FetchResult)
    assert [j.title for j in result.jobs] == ["a Engineer", "b Engineer"]
    assert result.failures == {}
    assert result.filtered == 0


def test_harvest_gates_the_union_and_counts_filtered():
    result = harvest(
        ["only"],
        lambda unit: [_job("AI Engineer"), _job("CDL Driver")],
        search=_ANCHORED,
        limit=None,
        key=lambda unit: unit,
        on_error=lambda exc: None,
    )
    assert [j.title for j in result.jobs] == ["AI Engineer"]
    assert result.filtered == 1


def test_harvest_caps_results_to_limit_after_gating():
    result = harvest(
        ["only"],
        lambda unit: [_job("First Engineer"), _job("Second Engineer")],
        search=_ANCHORED,
        limit=1,
        key=lambda unit: unit,
        on_error=lambda exc: None,
    )
    assert [j.title for j in result.jobs] == ["First Engineer"]


def test_harvest_isolates_a_failing_unit_and_records_the_reason():
    def produce(unit):
        if unit == "dead":
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404),
            )
        return [_job("Live Engineer")]

    result = harvest(
        ["dead", "live"],
        produce,
        search=_ANCHORED,
        limit=None,
        key=lambda unit: unit,
        on_error=lambda exc: "HTTP 404",
    )
    assert [j.title for j in result.jobs] == ["Live Engineer"]
    assert result.failures == {"dead": "HTTP 404"}


def test_harvest_reraises_when_on_error_returns_none():
    def produce(unit):
        raise ValueError("unexpected")

    with pytest.raises(ValueError):
        harvest(
            ["boom"],
            produce,
            search=_ANCHORED,
            limit=None,
            key=lambda unit: unit,
            on_error=lambda exc: None,
        )


def test_harvest_caps_each_unit_instead_of_the_union():
    result = harvest(
        ["a", "b"],
        lambda unit: [
            _job(f"{unit} Engineer {index}", url=f"{unit}/{index}")
            for index in range(3)
        ],
        search=_ANCHORED,
        limit=2,
        key=str,
        on_error=lambda exc: None,
    )
    assert [job.url for job in result.jobs] == ["a/0", "a/1", "b/0", "b/1"]


def test_harvest_unit_limit_overrides_the_global_fallback():
    result = harvest(
        ["a", "b"],
        lambda unit: [
            _job(f"{unit} Engineer {index}", url=f"{unit}/{index}")
            for index in range(5)
        ],
        search=_ANCHORED,
        limit=2,
        key=str,
        on_error=lambda exc: None,
        unit_limit=lambda unit: 4 if unit == "a" else None,
    )
    assert [job.url for job in result.jobs] == [
        "a/0",
        "a/1",
        "a/2",
        "a/3",
        "b/0",
        "b/1",
    ]


def test_harvest_applies_skip_seen_before_each_unit_cap():
    result = harvest(
        ["a", "b"],
        lambda unit: [
            _job(f"{unit} Engineer {index}", url=f"{unit}/{index}")
            for index in range(3)
        ],
        search=_ANCHORED,
        limit=1,
        key=str,
        on_error=lambda exc: None,
        skip_seen=lambda job: job.url in {"a/0", "b/0"},
    )
    assert [job.url for job in result.jobs] == ["a/1", "b/1"]


def test_gate_and_limit_returns_kept_jobs_and_dropped_count():
    jobs = [_job("AI Engineer"), _job("CDL Driver"), _job("Staff Engineer")]
    kept, filtered = gate_and_limit(jobs, _ANCHORED, limit=None)
    assert [j.title for j in kept] == ["AI Engineer", "Staff Engineer"]
    assert filtered == 1


def test_gate_and_limit_applies_limit_after_gating():
    jobs = [_job("AI Engineer"), _job("CDL Driver"), _job("Staff Engineer")]
    kept, filtered = gate_and_limit(jobs, _ANCHORED, limit=1)
    assert [j.title for j in kept] == ["AI Engineer"]
    # filtered counts the gate drop, independent of the limit truncation.
    assert filtered == 1


def _detailed(row: RawJob, jd: str) -> None:
    row.jd_text = jd


def test_harvest_detailed_title_gates_before_fetching_detail():
    fetched: list[str] = []

    def fetch_detail(row):
        fetched.append(row.title)
        return {"jd": "jd"}

    jobs = harvest_detailed(
        [_job("AI Engineer"), _job("CDL Driver")],
        fetch_detail,
        lambda row, detail: _detailed(row, detail["jd"]),
        search=_ANCHORED,
        limit=None,
    )
    # Only the title-matching row triggers the N+1 detail fetch.
    assert fetched == ["AI Engineer"]
    assert [j.title for j in jobs] == ["AI Engineer"]


def test_harvest_detailed_isolates_a_failed_detail_fetch():
    def fetch_detail(row):
        if row.title == "Dead Engineer":
            raise httpx.HTTPStatusError(
                "500",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(500),
            )
        return {"jd": "jd"}

    jobs = harvest_detailed(
        [_job("Dead Engineer"), _job("Live Engineer")],
        fetch_detail,
        lambda row, detail: _detailed(row, detail["jd"]),
        search=_ANCHORED,
        limit=None,
    )
    assert [j.title for j in jobs] == ["Live Engineer"]


def test_harvest_detailed_skips_rows_with_no_detail():
    jobs = harvest_detailed(
        [_job("First Engineer"), _job("Second Engineer")],
        lambda row: None if row.title == "First Engineer" else {"jd": "jd"},
        lambda row, detail: _detailed(row, detail["jd"]),
        search=_ANCHORED,
        limit=None,
    )
    assert [j.title for j in jobs] == ["Second Engineer"]


def test_harvest_detailed_applies_full_gate_after_detail():
    # No anchors: the title gate passes everything, and the post-detail gate falls
    # back to a keyword search over title + jd.
    jobs = harvest_detailed(
        [_job("Engineer One"), _job("Engineer Two")],
        lambda row: {"jd": "python" if row.title == "Engineer One" else "java"},
        lambda row, detail: _detailed(row, detail["jd"]),
        search=SearchConfig(keywords=["python"]),
        limit=None,
    )
    assert [j.title for j in jobs] == ["Engineer One"]


def test_harvest_detailed_stops_at_limit():
    fetched: list[str] = []

    def fetch_detail(row):
        fetched.append(row.title)
        return {"jd": "jd"}

    jobs = harvest_detailed(
        [_job("First Engineer"), _job("Second Engineer"), _job("Third Engineer")],
        fetch_detail,
        lambda row, detail: _detailed(row, detail["jd"]),
        search=_ANCHORED,
        limit=1,
    )
    assert [j.title for j in jobs] == ["First Engineer"]
    # Stops fetching details once the limit is met.
    assert fetched == ["First Engineer"]


def test_detail_fetches_run_concurrently_per_host(monkeypatch):
    """The detail fetches are independent; serialising them was the whole cost."""
    import time
    from resume_tailor_harness.config import Settings, env_settings

    delay = 0.05
    survivors = 20

    def fetch_detail(row):
        time.sleep(delay)
        return {"jd": "engineer work"}

    def apply_detail(row, detail):
        row.jd_text = detail["jd"]

    rows = [
        RawJob(
            source="x",
            url=f"u{i}",
            company="C",
            title="AI Engineer",
            location="Remote",
            jd_text="",
        )
        for i in range(survivors)
    ]

    env_settings.cache_clear()
    monkeypatch.setattr(
        "resume_tailor_harness.config.get_settings",
        lambda: Settings(_env_file=None, detail_fetch_concurrency=4),  # type: ignore[call-arg]
    )

    started = time.monotonic()
    jobs = harvest_detailed(
        rows,
        fetch_detail,
        apply_detail,
        search=SearchConfig(role_anchors=["ai engineer"]),
        limit=None,
    )
    elapsed = time.monotonic() - started

    assert len(jobs) == survivors
    serial = delay * survivors
    assert elapsed < serial / 2, f"{elapsed:.3f}s looks serialised (serial={serial}s)"


def test_a_limit_still_bounds_how_many_details_are_fetched(monkeypatch):
    """Concurrency must not turn `limit=5` into "fetch every candidate first"."""
    from resume_tailor_harness.config import Settings

    calls: list[str] = []

    def fetch_detail(row):
        calls.append(row.url or "")
        return {"jd": "engineer work"}

    def apply_detail(row, detail):
        row.jd_text = detail["jd"]

    rows = [
        RawJob(
            source="x",
            url=f"u{i}",
            company="C",
            title="AI Engineer",
            location="Remote",
            jd_text="",
        )
        for i in range(20)
    ]
    monkeypatch.setattr(
        "resume_tailor_harness.config.get_settings",
        lambda: Settings(_env_file=None, detail_fetch_concurrency=4),  # type: ignore[call-arg]
    )

    jobs = harvest_detailed(
        rows,
        fetch_detail,
        apply_detail,
        search=SearchConfig(role_anchors=["ai engineer"]),
        limit=5,
    )

    assert len(jobs) == 5
    # At most the limit plus one in-flight chunk, never the whole candidate set.
    assert len(calls) <= 8, calls
