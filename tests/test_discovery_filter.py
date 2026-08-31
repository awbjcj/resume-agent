from resume_tailor_harness.discovery.filter import apply_filters
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.models.job import JobCriteria, SalaryRange, SponsorshipSignal


def test_sponsorship_denied_is_rejected():
    cfg = SearchConfig(sponsorship_required=True)
    decision = apply_filters(
        JobCriteria(sponsorship_signal=SponsorshipSignal.denied), cfg
    )
    assert decision.keep is False
    assert decision.reject_reason is not None
    assert "sponsorship" in decision.reject_reason


def test_sponsorship_silent_is_kept_and_flagged():
    cfg = SearchConfig(sponsorship_required=True)
    decision = apply_filters(
        JobCriteria(sponsorship_signal=SponsorshipSignal.silent), cfg
    )
    assert decision.keep is True
    assert "sponsorship_uncertain" in decision.flags


def test_salary_below_minimum_is_rejected():
    cfg = SearchConfig(min_salary=120000)
    criteria = JobCriteria(salary_range=SalaryRange(minimum=80000, maximum=100000))
    decision = apply_filters(criteria, cfg)
    assert decision.keep is False
    assert decision.reject_reason is not None
    assert "salary" in decision.reject_reason


def test_too_much_experience_required_is_rejected():
    cfg = SearchConfig(yoe_max=5)
    decision = apply_filters(JobCriteria(yoe_min=8), cfg)
    assert decision.keep is False
    assert decision.reject_reason is not None
    assert "experience" in decision.reject_reason


def test_clean_match_is_kept():
    cfg = SearchConfig(sponsorship_required=True, min_salary=100000, yoe_max=5)
    criteria = JobCriteria(
        sponsorship_signal=SponsorshipSignal.offered,
        salary_range=SalaryRange(minimum=120000, maximum=160000),
        yoe_min=3,
    )
    decision = apply_filters(criteria, cfg)
    assert decision.keep is True
    assert decision.reject_reason is None
    assert decision.flags == []
