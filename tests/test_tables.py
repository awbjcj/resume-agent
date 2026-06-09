from sqlmodel import Session, SQLModel, create_engine, select

from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    ResumeVersion,
)


def _memory_engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_job_defaults_and_json_column_round_trip():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(
            source="linkedin",
            jd_text="We need a Python engineer",
            criteria_json={"sponsorship_signal": "silent", "must_have_skills": ["Python"]},
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        assert job.id is not None
        assert job.status == JobStatus.raw.value
        assert job.criteria_json["must_have_skills"] == ["Python"]
        assert job.created_at is not None


def test_resume_version_links_to_job_and_stores_critiques():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(source="linkedin", jd_text="jd")
        s.add(job)
        s.commit()
        s.refresh(job)
        rv = ResumeVersion(
            job_id=job.id,
            round=1,
            content_json={"contact": {"name": "Ada"}},
            critique_json=[{"reviewer": "fact-check", "score": 100, "passed": True}],
            fact_check_passed=True,
            review_score=88,
        )
        s.add(rv)
        s.commit()
        s.refresh(rv)
        assert rv.job_id == job.id
        assert rv.critique_json[0]["reviewer"] == "fact-check"


def test_application_status_default_is_ready():
    engine = _memory_engine()
    with Session(engine) as s:
        job = Job(source="linkedin", jd_text="jd")
        s.add(job)
        s.commit()
        s.refresh(job)
        app = Application(job_id=job.id)
        s.add(app)
        s.commit()
        s.refresh(app)
        assert app.status == ApplicationStatus.ready.value

        rows = s.exec(select(Application).where(Application.job_id == job.id)).all()
        assert len(rows) == 1
