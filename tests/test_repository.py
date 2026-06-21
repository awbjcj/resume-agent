from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.repository import (
    find_existing,
    jobs_by_status,
    save_job,
    status_counts,
)
from resume_agent.tracking.tables import Job, JobStatus


def test_archive_and_restore_preserve_status():
    from resume_agent.tracking.repository import archive_job, restore_job

    with _session() as s:
        job = save_job(s, Job(source="m", jd_text="a", status=JobStatus.shortlisted.value))
        jid = _require_id(job.id)

        archived = archive_job(s, jid)
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.status == JobStatus.shortlisted.value

        restored = restore_job(s, jid)
        assert restored is not None
        assert restored.archived_at is None
        assert restored.status == JobStatus.shortlisted.value

        assert archive_job(s, 9999) is None
        assert restore_job(s, 9999) is None


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_save_and_query_by_status():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="manual", jd_text="b", status=JobStatus.shortlisted.value))
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert len(raw) == 1
        assert raw[0].jd_text == "a"


def test_find_existing_by_url_then_jd_text():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="hello", url="http://x/1"))
        assert find_existing(s, "http://x/1", "different") is not None  # url match
        assert find_existing(s, None, "hello") is not None             # jd_text match
        assert find_existing(s, "http://x/2", "nope") is None


def test_status_counts():
    with _session() as s:
        save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="c", status=JobStatus.shortlisted.value))
        counts = status_counts(s)
        assert counts[JobStatus.raw.value] == 2
        assert counts[JobStatus.shortlisted.value] == 1


def test_get_resume_version_roundtrip():
    from resume_agent.tracking.repository import get_resume_version, save_resume_version
    from resume_agent.tracking.tables import ResumeVersion

    with _session() as s:
        v = save_resume_version(s, ResumeVersion(job_id=1, round=1, content_json={"contact": {"name": "Ada"}}))
        fetched = get_resume_version(s, _require_id(v.id))
        assert fetched is not None
        assert fetched.content_json is not None
        assert fetched.content_json["contact"]["name"] == "Ada"
        assert get_resume_version(s, 9999) is None


def test_has_progress_true_for_advanced_status_and_children():
    from resume_agent.tracking.repository import (
        has_progress, save_application, save_resume_version,
    )
    from resume_agent.tracking.tables import Application, ResumeVersion

    with _session() as s:
        raw = save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        approved = save_job(s, Job(source="m", jd_text="b", status=JobStatus.approved.value))
        with_version = save_job(s, Job(source="m", jd_text="c", status=JobStatus.raw.value))
        save_resume_version(s, ResumeVersion(job_id=_require_id(with_version.id), round=1))
        with_app = save_job(s, Job(source="m", jd_text="d", status=JobStatus.raw.value))
        save_application(s, Application(job_id=_require_id(with_app.id)))

        assert has_progress(s, _require_id(raw.id)) is False
        assert has_progress(s, _require_id(approved.id)) is True
        assert has_progress(s, _require_id(with_version.id)) is True
        assert has_progress(s, _require_id(with_app.id)) is True
        assert has_progress(s, 9999) is False


def test_delete_job_cascades_children_and_refuses_progress():
    from resume_agent.tracking.repository import (
        delete_job, get_job, save_application, save_cover_letter, save_resume_version,
    )
    from resume_agent.tracking.tables import Application, CoverLetter, ResumeVersion
    from sqlmodel import select

    with _session() as s:
        junk = save_job(s, Job(source="m", jd_text="a", status=JobStatus.rejected.value))
        jid = _require_id(junk.id)
        assert delete_job(s, jid) is True
        assert get_job(s, jid) is None

        # A job with children/progress is refused and left intact.
        kept = save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        kid = _require_id(kept.id)
        save_resume_version(s, ResumeVersion(job_id=kid, round=1))
        save_application(s, Application(job_id=kid))
        save_cover_letter(s, CoverLetter(job_id=kid))
        assert delete_job(s, kid) is False
        assert get_job(s, kid) is not None
        assert s.exec(select(ResumeVersion).where(ResumeVersion.job_id == kid)).first() is not None
