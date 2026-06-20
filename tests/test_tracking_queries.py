from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.base import Source
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.repository import save_application, save_job, save_resume_version
from resume_agent.tracking.queries import pipeline_rows, shortlist_rows
from resume_agent.tracking.tables import Application, ApplicationStatus, Job, JobStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _facts_with_python() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"lang": [Skill(name="Python", source=Source.resume)]},
    )


def test_shortlist_rows_only_shortlisted_with_fit_and_sponsorship():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=82,
                        fit_rationale="strong python match",
                        criteria_json={"sponsorship_signal": "offered"}))
        save_job(s, Job(source="manual", jd_text="b", company="Beta", title="Dev",
                        status=JobStatus.raw.value))  # excluded

        rows = shortlist_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.company == "Acme"
        assert row.fit_score == 82
        assert row.fit_rationale == "strong python match"
        assert row.sponsorship_signal == "offered"


def test_shortlist_row_flattens_metadata_and_tags_coverage():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                company="Acme",
                title="Eng",
                status=JobStatus.shortlisted.value,
                fit_score=80,
                posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                criteria_json={
                    "salary_range": {
                        "minimum": 150000,
                        "maximum": 190000,
                        "currency": "USD",
                    },
                    "remote_policy": "remote",
                    "seniority": "senior",
                    "employment_type": "full_time",
                    "industry": "fintech",
                    "company_size": "scaleup",
                    "must_have_skills": ["Python", "Go"],
                    "nice_to_have_skills": ["Docker"],
                },
            ),
        )
        rows = shortlist_rows(s, facts=_facts_with_python())
        row = rows[0]
        assert row.salary_min == 150000
        assert row.salary_max == 190000
        assert row.salary_currency == "USD"
        assert row.remote_policy == "remote"
        assert row.seniority == "senior"
        assert row.employment_type == "full_time"
        assert row.industry == "fintech"
        assert row.company_size == "scaleup"
        assert row.posted_at == datetime(2026, 6, 1)
        names = {t.name: t for t in row.skills}
        assert names["Python"].covered is True
        assert names["Python"].required is True
        assert names["Go"].covered is False
        assert names["Go"].required is True
        assert names["Docker"].required is False


def test_shortlist_row_surfaces_tech_stack_as_nonrequired_deduped():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                status=JobStatus.shortlisted.value,
                criteria_json={
                    "must_have_skills": ["Python"],
                    "tech_stack": ["Python", "Kafka"],  # Python dup -> stays required
                },
            ),
        )
        rows = shortlist_rows(s, facts=_facts_with_python())
        names = {t.name: t for t in rows[0].skills}
        # Python appears once, keeping its must-have (required) slot.
        assert [t.name for t in rows[0].skills].count("Python") == 1
        assert names["Python"].required is True
        assert names["Python"].covered is True
        # Kafka surfaces from tech_stack as a non-required, filterable tag.
        assert names["Kafka"].required is False
        assert names["Kafka"].covered is False


def test_shortlist_row_without_facts_marks_all_uncovered():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": ["Python"]},
            ),
        )
        rows = shortlist_rows(s, facts=None)
        assert rows[0].skills[0].covered is False


def test_pipeline_rows_include_pdf_and_application_status():
    with _session() as s:
        job = save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                              status=JobStatus.rendered.value, fit_score=90))
        save_resume_version(s, ResumeVersion(job_id=_require_id(job.id), round=1, content_json={"x": 1}))
        save_resume_version(
            s,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=2,
                content_json={"contact": {"name": "Ada"}},
                critique_json=[{"reviewer": "fact-check", "passed": True}],
                pdf_path="output/acme.pdf",
            ),
        )
        save_application(s, Application(job_id=_require_id(job.id), status=ApplicationStatus.submitted.value))

        rows = pipeline_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.status == JobStatus.rendered.value
        assert row.pdf_path == "output/acme.pdf"
        assert row.jd_text == "a"
        assert row.critique_json == [{"reviewer": "fact-check", "passed": True}]
        assert row.application_status == ApplicationStatus.submitted.value
        assert row.fit_score == 90


def test_pipeline_rows_distinguish_no_version_from_empty_critiques():
    # The board must tell "never tailored" (no ResumeVersion) apart from
    # "tailored, reviewers raised nothing": None vs []. Collapsing both to []
    # made every untailored card read as an empty critique list.
    with _session() as s:
        untailored = save_job(s, Job(source="manual", jd_text="a", company="A", title="E",
                                     status=JobStatus.shortlisted.value))
        reviewed_clean = save_job(s, Job(source="manual", jd_text="b", company="B", title="E",
                                         status=JobStatus.tailored.value))
        save_resume_version(
            s, ResumeVersion(job_id=_require_id(reviewed_clean.id), round=1, content_json={"x": 1})
        )

        by_id = {row.job_id: row for row in pipeline_rows(s)}
        assert by_id[_require_id(untailored.id)].critique_json is None
        assert by_id[_require_id(reviewed_clean.id)].critique_json == []


def test_pipeline_rows_include_lean_metadata_fields():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                company="Acme",
                title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={
                    "salary_range": {"minimum": 140000, "maximum": 180000},
                    "remote_policy": "hybrid",
                    "seniority": "staff",
                },
            ),
        )

        row = pipeline_rows(s)[0]
        assert row.salary_min == 140000
        assert row.salary_max == 180000
        assert row.remote_policy == "hybrid"
        assert row.seniority == "staff"
