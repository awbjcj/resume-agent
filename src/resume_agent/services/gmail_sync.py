"""One sync pass: fetch inbox → propose status changes → follow-up reminders.

Shared by the manual POST /api/gmail/sync run and the scheduler tick, so
the two can never drift. Never auto-applies a status change.
"""

from __future__ import annotations

from typing import Any

from resume_agent.config import get_settings
from resume_agent.db import get_session
from resume_agent.gmail.auth import build_service
from resume_agent.gmail.classify import build_classifier_llm, hydrating_classifier
from resume_agent.gmail.client import fetch_recent_messages
from resume_agent.llm_runner import Runner
from resume_agent.services.notifications import sync_notifications
from resume_agent.services.reminders import create_follow_up_reminders

_UNSET = object()


def run_gmail_sync(
    engine: Any,
    reporter: Any,
    *,
    service: Any | None = None,
    llm: Runner | None | Any = _UNSET,
) -> dict:
    reporter.begin(2, "Scanning Gmail")
    if service is None:
        service = build_service()
    if llm is _UNSET:
        llm = build_classifier_llm()
    emails = fetch_recent_messages(
        service, max_results=get_settings().gmail_max_messages
    )
    classify = hydrating_classifier(service, llm)
    with get_session(engine) as session:
        pending = sync_notifications(session, emails, classify=classify)
        reporter.step(1, label="Checking follow-ups")
        reminders = create_follow_up_reminders(session)
    reporter.step(2, label="Done")
    return {"pending": len(pending), "reminders": len(reminders)}
