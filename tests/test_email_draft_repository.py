from sqlmodel import Session

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.repository import (
    delete_job_row,
    email_drafts_for_job,
    get_email_draft,
    has_progress,
    save_email_draft,
    save_job,
)
from resume_tailor_harness.tracking.tables import EmailDraft, Job


def _draft(job_id: int, subject: str = "Following up") -> EmailDraft:
    return EmailDraft(
        job_id=job_id, draft_type="follow_up", subject=subject, body="Hi —"
    )


def test_save_and_list_newest_first():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        first = save_email_draft(session, _draft(job.id, "one"))
        second = save_email_draft(session, _draft(job.id, "two"))
        drafts = email_drafts_for_job(session, job.id)
        assert [d.subject for d in drafts] == ["two", "one"]
        assert first.id is not None
        assert get_email_draft(session, first.id) is not None
        assert second.state == "generated"


def test_drafts_never_gate_deletion_and_cascade():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        save_email_draft(session, _draft(job.id))
        assert has_progress(session, job.id) is False  # invariant: no gate
        delete_job_row(session, job)
        assert email_drafts_for_job(session, job.id) == []
