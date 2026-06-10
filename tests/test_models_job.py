from resume_agent.models.job import JobCriteria, SalaryRange, SponsorshipSignal


def test_sponsorship_defaults_to_silent():
    c = JobCriteria()
    assert c.sponsorship_signal == SponsorshipSignal.silent


def test_full_criteria_round_trips():
    c = JobCriteria(
        sponsorship_signal=SponsorshipSignal.offered,
        yoe_min=3,
        salary_range=SalaryRange(minimum=120000, maximum=160000),
        remote_policy="hybrid",
        location="Seattle, WA",
        must_have_skills=["Python", "AWS"],
    )
    dumped = c.model_dump(mode="json")
    restored = JobCriteria.model_validate(dumped)
    assert restored.sponsorship_signal == SponsorshipSignal.offered
    assert restored.salary_range is not None
    assert restored.salary_range.minimum == 120000
    assert restored.must_have_skills == ["Python", "AWS"]


def test_salary_range_defaults():
    s = SalaryRange(minimum=100000)
    assert s.currency == "USD"
    assert s.period == "year"
    assert s.maximum is None
