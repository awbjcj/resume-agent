from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.progress import ProgressReporter
from resume_agent.services.gmail_sync import run_gmail_sync
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, Job


class _FakeListing:
    def __init__(self, messages):
        self._messages = messages

    def list(self, **kwargs):
        refs = [{"id": m["id"]} for m in self._messages]
        return type("Req", (), {"execute": staticmethod(lambda: {"messages": refs})})()

    def get(self, userId, id, format, metadataHeaders=None):
        msg = next(m for m in self._messages if m["id"] == id)
        if format == "full":
            result = {"payload": msg.get("payload", {})}
        else:
            result = {
                "payload": {"headers": msg["headers"]},
                "snippet": msg.get("snippet", ""),
                "threadId": msg.get("threadId"),
            }
        return type("Req", (), {"execute": staticmethod(lambda: result)})()


class FakeGmailService:
    def __init__(self, messages):
        self._messages = _FakeListing(messages)

    def users(self):
        messages = self._messages
        return type("Users", (), {"messages": staticmethod(lambda: messages)})()


def _reporter(tmp_path):
    return ProgressReporter("test-run", root=tmp_path)


def test_run_gmail_sync_creates_notifications_without_owning_reminders(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        app = save_application(session, Application(job_id=job.id, status="submitted"))
        app.updated_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.add(app)
        session.commit()

    service = FakeGmailService(
        [
            {
                "id": "m1",
                "headers": [
                    {"name": "From", "value": "hr@acme.com"},
                    {"name": "Subject", "value": "Interview at Acme"},
                ],
                "snippet": "Schedule a call",
                "threadId": "t1",
            }
        ]
    )
    result = run_gmail_sync(engine, _reporter(tmp_path), service=service, llm=None)
    assert result["pending"] >= 1
    assert set(result) == {"pending"}


def test_run_gmail_sync_disconnected_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate from a real legacy data/gmail_token.json
    engine = make_engine("sqlite://")
    init_db(engine)
    with pytest.raises(GmailNotConnected):
        run_gmail_sync(engine, _reporter(tmp_path))
