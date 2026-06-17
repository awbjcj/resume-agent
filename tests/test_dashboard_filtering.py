from datetime import datetime, timedelta, timezone

from resume_agent.dashboard.filtering import (
    FilterState,
    apply_filters,
    available_skill_cloud,
    composite_score,
    sort_rows,
)
from resume_agent.tracking.queries import ShortlistRow, SkillTag

NOW = datetime(2026, 6, 16, tzinfo=timezone.utc)


def _row(
    job_id: int = 1,
    fit: int | None = 80,
    salary_min: int | None = None,
    salary_max: int | None = None,
    remote: str | None = None,
    seniority: str | None = None,
    emp: str | None = None,
    industry: str | None = None,
    sponsorship: str | None = None,
    posted: datetime | None = None,
    skills: list[SkillTag] | None = None,
    currency: str | None = "USD",
) -> ShortlistRow:
    return ShortlistRow(
        job_id=job_id,
        company="C",
        title="T",
        location="L",
        fit_score=fit,
        fit_rationale="r",
        sponsorship_signal=sponsorship,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        remote_policy=remote,
        seniority=seniority,
        employment_type=emp,
        industry=industry,
        company_size=None,
        posted_at=posted,
        skills=skills or [],
    )


def test_salary_floor_excludes_only_known_below():
    rows = [
        _row(job_id=1, salary_max=100000),
        _row(job_id=2, salary_max=200000),
        _row(job_id=3, salary_max=None),
    ]
    out = apply_filters(rows, FilterState(salary_min=150000))
    assert {r.job_id for r in out} == {2, 3}


def test_salary_floor_skips_non_usd_currencies():
    # A USD min-salary threshold can't be compared against a raw non-USD amount,
    # so non-USD rows are kept (neutral) rather than excluded on a bogus compare.
    rows = [
        _row(job_id=1, salary_max=100000, currency="USD"),   # below, USD -> excluded
        _row(job_id=2, salary_max=100000, currency="EUR"),   # below in EUR -> kept
        _row(job_id=3, salary_max=100000, currency=None),    # unknown -> USD -> excluded
    ]
    out = apply_filters(rows, FilterState(salary_min=150000))
    assert {r.job_id for r in out} == {2}


def test_remote_and_seniority_and_together():
    rows = [
        _row(job_id=1, remote="remote", seniority="senior"),
        _row(job_id=2, remote="onsite", seniority="senior"),
    ]
    out = apply_filters(rows, FilterState(remote={"remote"}, seniority={"senior"}))
    assert {r.job_id for r in out} == {1}


def test_unknown_categorical_values_pass_filters():
    rows = [_row(job_id=1, remote=None), _row(job_id=2, remote="onsite")]
    out = apply_filters(rows, FilterState(remote={"remote"}))
    assert {r.job_id for r in out} == {1}


def test_skills_use_or_semantics():
    rows = [
        _row(job_id=1, skills=[SkillTag("python", True, True)]),
        _row(job_id=2, skills=[SkillTag("go", False, True)]),
        _row(job_id=3, skills=[SkillTag("rust", False, True)]),
    ]
    out = apply_filters(rows, FilterState(skills={"python", "go"}))
    assert {r.job_id for r in out} == {1, 2}


def test_fit_min_filter():
    rows = [_row(job_id=1, fit=60), _row(job_id=2, fit=90)]
    out = apply_filters(rows, FilterState(fit_min=80))
    assert {r.job_id for r in out} == {2}


def test_sort_by_salary_desc_nulls_last():
    rows = [
        _row(job_id=1, salary_max=100000),
        _row(job_id=2, salary_max=None),
        _row(job_id=3, salary_max=200000),
    ]
    out = sort_rows(rows, FilterState(sort="salary"), now=NOW)
    assert [r.job_id for r in out] == [3, 1, 2]


def test_sort_by_recency_desc_nulls_last():
    rows = [
        _row(job_id=1, posted=NOW - timedelta(days=10)),
        _row(job_id=2, posted=None),
        _row(job_id=3, posted=NOW - timedelta(days=1)),
    ]
    out = sort_rows(rows, FilterState(sort="recency"), now=NOW)
    assert [r.job_id for r in out] == [3, 1, 2]


def test_composite_neutral_for_missing_factors():
    score = composite_score(_row(fit=None, salary_max=None, posted=None), "balanced", now=NOW)
    assert score == 50.0


def test_composite_pay_first_prefers_salary():
    high_pay = _row(job_id=1, fit=50, salary_max=250000, posted=None)
    high_fit = _row(job_id=2, fit=100, salary_max=0, posted=None)
    assert composite_score(high_pay, "pay_first", now=NOW) > composite_score(
        high_fit, "pay_first", now=NOW
    )


def test_composite_salary_capped_at_ceiling():
    capped = _row(salary_max=250000)
    over = _row(salary_max=900000)
    assert composite_score(capped, "pay_first", now=NOW) == composite_score(
        over, "pay_first", now=NOW
    )


def test_composite_recency_clamped_for_future_posting():
    # A future-dated / clock-skewed posting must not out-rank a brand-new one:
    # recency is clamped at 100, so both score identically under any preset.
    future = _row(job_id=1, fit=None, salary_max=None, posted=NOW + timedelta(days=10))
    fresh = _row(job_id=2, fit=None, salary_max=None, posted=NOW)
    assert composite_score(future, "freshest", now=NOW) == composite_score(
        fresh, "freshest", now=NOW
    )


def test_available_skill_cloud_is_deduped_union():
    rows = [
        _row(job_id=1, skills=[SkillTag("python", True, True), SkillTag("go", False, True)]),
        _row(job_id=2, skills=[SkillTag("python", True, False)]),
    ]
    cloud = available_skill_cloud(rows)
    assert {t.name for t in cloud} == {"python", "go"}
    py = next(t for t in cloud if t.name == "python")
    assert py.covered is True
    assert py.required is True


def test_empty_result_returns_empty_list():
    assert apply_filters([], FilterState(fit_min=90)) == []
