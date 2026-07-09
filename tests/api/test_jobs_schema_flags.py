from resume_agent.api.schemas.jobs import JobDetail, PipelineItem


def test_pipeline_item_exposes_attention_flags_camelcase():
    item = PipelineItem.model_validate(
        {
            "job_id": 1,
            "company": "Acme",
            "title": "Eng",
            "status": "tailored",
            "fit_score": 80,
            "jd_text": "x",
            "critique_json": [],
            "pdf_path": None,
            "application_status": None,
            "salary_min": None,
            "salary_max": None,
            "remote_policy": None,
            "seniority": None,
            "has_progress": True,
            "needs_attention": True,
            "regressed": False,
        }
    )
    dumped = item.model_dump(by_alias=True)
    assert dumped["needsAttention"] is True
    assert dumped["regressed"] is False


def test_pipeline_item_accepts_fractional_hourly_salary():
    """Hourly-rate JDs (e.g. $41.75/hr) yield fractional salary values.

    These are preserved verbatim from JD extraction, not normalized to
    annual ints, so the API schema must accept floats.
    """
    item = PipelineItem.model_validate(
        {
            "job_id": 1,
            "company": "Acme",
            "title": "Eng",
            "status": "tailored",
            "fit_score": 80,
            "jd_text": "x",
            "critique_json": [],
            "pdf_path": None,
            "application_status": None,
            "salary_min": 41.75,
            "salary_max": 66.75,
            "remote_policy": None,
            "seniority": None,
            "has_progress": True,
        }
    )
    dumped = item.model_dump(by_alias=True)
    assert dumped["salaryMin"] == 41.75
    assert dumped["salaryMax"] == 66.75


def test_job_detail_exposes_best_version_camelcase():
    detail = JobDetail.model_validate(
        {
            "id": 1,
            "source": "url",
            "url": None,
            "company": None,
            "title": None,
            "location": None,
            "jd_text": "x",
            "status": "tailored",
            "fit_score": None,
            "fit_rationale": None,
            "criteria_json": None,
            "posted_at": None,
            "archived_at": None,
            "created_at": "2026-06-30T00:00:00Z",
            "has_progress": True,
            "application": None,
            "resume_versions": [],
            "skills": [],
            "best_resume_version_id": 5,
            "needs_attention": False,
            "regressed": True,
        }
    )
    dumped = detail.model_dump(by_alias=True)
    assert dumped["bestResumeVersionId"] == 5
    assert dumped["regressed"] is True
