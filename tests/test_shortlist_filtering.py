from datetime import datetime, timedelta, timezone

from resume_agent.services.shortlist_filtering import (
    FilterState,
    apply_filters,
    available_cities,
    available_countries,
    available_skill_cloud,
    available_states,
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
    sic_major: str | None = None,
    sic_label: str | None = None,
    sic_division: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    is_us: bool = False,
    company_size: str | None = None,
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
        company_size=company_size,
        posted_at=posted,
        skills=skills or [],
        sic_major=sic_major,
        sic_label=sic_label,
        sic_division=sic_division,
        location_country=country,
        location_region=region,
        location_city=city,
        is_us=is_us,
    )


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


def test_location_cascade_builders_narrow():
    rows = [
        _row(country="US", region="TX", city="Austin"),
        _row(country="US", region="CA", city="San Jose"),
        _row(country="GB", region=None, city="London"),
    ]
    assert available_countries(rows) == ["GB", "US"]
    assert available_states(rows, {"US"}) == ["CA", "TX"]
    assert available_cities(rows, {"US"}, {"TX"}) == ["Austin"]
