import httpx
import pytest

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.harvest import FetchResult, gate_and_limit, harvest
from resume_agent.discovery.search_config import SearchConfig

_ANCHORED = SearchConfig(role_anchors=["engineer"])


def _job(title: str, url: str = "u") -> RawJob:
    return RawJob(source="x", url=url, company="Acme", title=title, location=None, jd_text="jd")


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
                "404", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
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
