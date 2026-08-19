from __future__ import annotations

from resume_agent.models.job import EmploymentType, JobCriteria


def _criteria() -> JobCriteria:
    return JobCriteria(
        tech_stack=["Python"],
        yoe_min=5,
        remote_policy="remote",
        location="New York",
        must_have_skills=[
            "AWS Certified Solutions Architect",
            "work authorization",
        ],
        nice_to_have_skills=["Leadership"],
    )


def _jd() -> str:
    return (
        "Candidates need an AWS Certified Solutions Architect credential, "
        "Python, five years of experience, and work authorization. "
        "This remote role is based in New York. Leadership is preferred."
    )


def test_new_requirements_retain_exact_spans_types_and_strictness():
    from resume_agent.discovery.requirements import bind_job_requirements

    jd = _jd()
    bound = bind_job_requirements(
        _criteria(),
        job_id=42,
        jd_text=jd,
        taxonomy_revision="a" * 64,
    )

    assert bound.job_extraction_revision
    assert bound.extraction_policy_revision == "job-requirements-v1"
    assert bound.typed_requirements
    for requirement in bound.typed_requirements:
        if requirement.provenance == "exact_span":
            assert requirement.source_start is not None
            assert requirement.source_end is not None
            assert jd[requirement.source_start : requirement.source_end] == (
                requirement.source_text
            )

    by_text = {item.source_text.casefold(): item for item in bound.typed_requirements}
    credential = by_text["aws certified solutions architect"]
    assert credential.concept_type == "credential"
    assert credential.requirement_kind == "credential_required"
    assert credential.strictness == "credential"
    assert credential.evidence_expectation == "verified_fact"

    python = by_text["python"]
    assert python.concept_type == "tool_technology"
    assert python.strictness == "exact_product"
    assert python.legacy_source == "tech"

    experience = by_text["five years of experience"]
    assert experience.requirement_kind == "experience_required"
    assert experience.minimum_proficiency is None

    authorization = by_text["work authorization"]
    assert authorization.requirement_kind == "availability_or_location"
    assert authorization.strictness == "contextual"

    leadership = by_text["leadership"]
    assert leadership.concept_type == "unknown"
    assert leadership.failure_reason == "ambiguous"


def test_requirement_ids_are_deterministic_and_legacy_lists_round_trip():
    from resume_agent.discovery.requirements import (
        bind_job_requirements,
        project_legacy_criteria,
    )

    first = bind_job_requirements(
        _criteria(), job_id=42, jd_text=_jd(), taxonomy_revision="a" * 64
    )
    second = bind_job_requirements(
        _criteria(), job_id=42, jd_text=_jd(), taxonomy_revision="a" * 64
    )

    assert [item.id for item in first.typed_requirements] == [
        item.id for item in second.typed_requirements
    ]
    projection = project_legacy_criteria(first.typed_requirements)
    assert projection == {
        "must_have_skills": [
            "AWS Certified Solutions Architect",
            "work authorization",
        ],
        "nice_to_have_skills": ["Leadership"],
        "tech_stack": ["Python"],
    }
    assert first.requirement_reconciliation_issues == []


def test_legacy_criteria_are_adapted_without_fabricated_offsets():
    from resume_agent.discovery.requirements import adapt_legacy_requirements

    adapted = adapt_legacy_requirements(
        _criteria(),
        job_id=42,
        taxonomy_revision="a" * 64,
    )

    assert adapted
    assert all(item.provenance == "legacy_list_item" for item in adapted)
    assert all(item.source_start is None and item.source_end is None for item in adapted)
    assert all(item.source_text for item in adapted)


def test_unlocated_extracted_item_is_preserved_and_surfaced():
    from resume_agent.discovery.requirements import bind_job_requirements

    criteria = JobCriteria(must_have_skills=["Paraphrased capability"])
    bound = bind_job_requirements(
        criteria,
        job_id=42,
        jd_text="The source uses different wording.",
        taxonomy_revision="a" * 64,
    )

    requirement = bound.typed_requirements[0]
    assert requirement.provenance == "unlocated_extraction"
    assert requirement.source_start is None
    assert len(bound.requirement_reconciliation_issues) == 1
    issue = bound.requirement_reconciliation_issues[0]
    assert issue.code == "source_span_not_found"
    assert issue.requirement_id == requirement.id
    assert issue.message == (
        "Could not locate extracted criterion in the job description"
    )


def test_requirement_lanes_keep_education_physical_schedule_and_standards_separate():
    from resume_agent.discovery.requirements import bind_job_requirements

    jd = (
        "A Bachelor's degree and ISO 27001 knowledge are required. "
        "Candidates must lift 50 pounds. AWS experience is required. "
        "This is a full-time hybrid role."
    )
    criteria = JobCriteria(
        employment_type=EmploymentType.full_time,
        remote_policy="hybrid",
        tech_stack=["AWS"],
        must_have_skills=["Bachelor's degree", "ISO 27001", "lift 50 pounds"],
    )

    bound = bind_job_requirements(
        criteria,
        job_id=7,
        jd_text=jd,
        taxonomy_revision="c" * 64,
    )
    by_text = {item.source_text.casefold(): item for item in bound.typed_requirements}

    assert by_text["bachelor's degree"].requirement_kind == "education_required"
    assert by_text["iso 27001"].strictness == "method_or_standard"
    assert by_text["lift 50 pounds"].requirement_kind == (
        "physical_or_environmental"
    )
    assert by_text["aws"].strictness == "product_family"
    assert by_text["full-time"].requirement_kind == "context"
    assert by_text["hybrid"].requirement_kind == "availability_or_location"
