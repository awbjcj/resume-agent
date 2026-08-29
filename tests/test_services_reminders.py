from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.notifications import accept_notification, list_pending
from resume_agent.services.reminders import FOLLOW_UP_KIND, create_follow_up_reminders
from resume_agent.tracking.repository import get_application, save_application, save_job
from resume_agent.tracking.tables import Application, Job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(
    session: Session, *, status: str = "submitted", days_old: int = 20
) -> Application:
    job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
    assert job.id is not None
    app = save_application(session, Application(job_id=job.id, status=status))
    app.updated_at = _now() - timedelta(days=days_old)
    session.add(app)
    session.commit()
    return app


def test_stale_submitted_application_gets_one_reminder():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=20)
        first = create_follow_up_reminders(session, days=14, now=_now())
        again = create_follow_up_reminders(session, days=14, now=_now())
        assert len(first) == 1
        assert first[0].kind == FOLLOW_UP_KIND
        assert first[0].proposed_status == ""
        assert again == []  # same episode → deduped


def test_fresh_and_terminal_applications_are_skipped():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=3)
        _seed(session, status="rejected", days_old=40)
        assert create_follow_up_reminders(session, days=14, now=_now()) == []


def test_zero_days_disables_reminders():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=100)
        assert create_follow_up_reminders(session, days=0, now=_now()) == []


def test_accept_follow_up_does_not_change_status():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        app = _seed(session, days_old=20)
        assert app.id is not None
        [reminder] = create_follow_up_reminders(session, days=14, now=_now())
        assert reminder.id is not None
        accepted = accept_notification(session, reminder.id)
        assert accepted is not None and accepted.state == "accepted"
        refreshed = get_application(session, app.id)
        assert refreshed is not None and refreshed.status == "submitted"
        assert list_pending(session) == []
