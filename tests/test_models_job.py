from resume_agent.models.job import (
    EmploymentType,
    JobCriteria,
    SalaryRange,
    Seniority,
    SponsorshipSignal,
)


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


def test_job_criteria_new_fields_default_empty():
    c = JobCriteria()
    assert c.seniority is None
    assert c.employment_type is None
    assert c.tech_stack == []
    assert c.industry is None
    assert c.company_size is None


def test_job_criteria_new_fields_roundtrip():
    c = JobCriteria(
        seniority=Seniority.senior,
        employment_type=EmploymentType.full_time,
        tech_stack=["python", "aws"],
        industry="fintech",
        company_size="scaleup",
    )
    dumped = c.model_dump(mode="json")
    restored = JobCriteria.model_validate(dumped)
    assert restored.seniority == Seniority.senior
    assert restored.employment_type == EmploymentType.full_time
    assert restored.tech_stack == ["python", "aws"]
    assert restored.industry == "fintech"
    assert restored.company_size == "scaleup"
