import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.email_writer import (
    DRAFT_TYPES,
    EmailDraftContent,
    generate_email_draft,
)
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, Job


class _FakeAgent:
    def __init__(self):
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(
            content=EmailDraftContent(subject="Following up on Eng", body="Hi — ...")
        )

    async def arun(self, prompt: str):  # Runner protocol
        return self.run(prompt)


class _FakeMessages:
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
        self._messages = _FakeMessages(messages)

    def users(self):
        messages = self._messages
        return type("Users", (), {"messages": staticmethod(lambda: messages)})()


def _facts(tmp_path) -> str:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps({"summary": "Engineer with Python."}), encoding="utf-8")
    return str(path)


def test_generate_persists_draft_without_thread(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    agent = _FakeAgent()
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        save_application(session, Application(job_id=job.id, status="submitted"))
        draft = generate_email_draft(
            session,
            job.id,
            "follow_up",
            facts_path=_facts(tmp_path),
            agent=agent,
            service=None,
        )
    assert draft.id is not None
    assert draft.subject == "Following up on Eng"
    assert draft.to_addr == ""  # no thread context → user fills recipient
    assert draft.state == "generated"
    prompt = agent.prompts[0]
    assert "Acme" in prompt and "Engineer with Python." in prompt


def test_generate_rejects_unknown_type(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        with pytest.raises(ValueError):
            generate_email_draft(
                session, job.id, "spam", facts_path=_facts(tmp_path), agent=_FakeAgent()
            )


def test_draft_types_frozen():
    assert DRAFT_TYPES == ("follow_up", "thank_you", "withdrawal", "cold_outreach")


def test_generate_uses_matched_thread(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    agent = _FakeAgent()
    service = FakeGmailService(
        [
            {
                "id": "m1",
                "headers": [
                    {"name": "From", "value": "Jane Doe <jane@acme.com>"},
                    {"name": "Subject", "value": "Interview at Acme"},
                ],
                "snippet": "Schedule a call",
                "threadId": "t1",
            }
        ]
    )
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        draft = generate_email_draft(
            session,
            job.id,
            "follow_up",
            facts_path=_facts(tmp_path),
            agent=agent,
            service=service,
        )
    assert draft.to_addr == "jane@acme.com"
    assert draft.gmail_thread_id == "t1"
