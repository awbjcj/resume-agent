from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.gmail.client import EmailMessage
from resume_agent.services.notifications import (
    accept_notification,
    dismiss_notification,
    list_pending,
    sync_notifications,
)
from resume_agent.tracking.repository import get_application, save_application, save_job
from resume_agent.tracking.tables import Application, Job


def _seed(session: Session):
    job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
    assert job.id is not None
    app = save_application(session, Application(job_id=job.id, status="submitted"))
    return app


def _email(message_id: str) -> EmailMessage:
    return EmailMessage(
        sender="recruiting@acme.com",
        sender_domain="acme.com",
        subject="Interview at Acme",
        snippet="Schedule a call",
        message_id=message_id,
    )


def test_sync_creates_pending_and_is_idempotent():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session)
        first = sync_notifications(session, [_email("m1")], classify=lambda email: "interview")
        again = sync_notifications(session, [_email("m1")], classify=lambda email: "interview")

        assert len(first) == 1
        assert len(again) == 1
        assert again[0].message_id == "m1"


def test_accept_applies_transition_and_dismiss_suppresses():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        app = _seed(session)
        assert app.id is not None
        [notification] = sync_notifications(
            session, [_email("m1")], classify=lambda email: "interview"
        )
        assert notification.id is not None
        accepted = accept_notification(session, notification.id)

        assert accepted is not None
        assert accepted.state == "accepted"
        updated = get_application(session, app.id)
        assert updated is not None
        assert updated.status == "interview"

        [second] = sync_notifications(session, [_email("m2")], classify=lambda email: "offer")
        assert second.id is not None
        dismissed = dismiss_notification(session, second.id)
        assert dismissed is not None
        sync_notifications(session, [_email("m2")], classify=lambda email: "offer")
        assert all(item.message_id != "m2" for item in list_pending(session))
