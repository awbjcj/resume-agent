from sqlmodel import Session, SQLModel, create_engine

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
