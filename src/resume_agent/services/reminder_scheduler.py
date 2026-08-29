"""Hourly reminders for every user, independent of Gmail connection state."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlmodel import Session

from resume_agent.db import get_session
from resume_agent.services.reminders import (
    create_event_reminders,
    create_follow_up_reminders,
)

logger = logging.getLogger(__name__)
REMINDER_INTERVAL_SECONDS = 3600


def run_reminder_pass(
    session: Session, *, now: datetime | None = None
) -> dict[str, int]:
    follow_ups = create_follow_up_reminders(session, now=now)
    events = create_event_reminders(session, now=now)
    return {"followUp": len(follow_ups), "events": len(events)}


async def reminder_tick(state: Any, *, now: datetime | None = None) -> dict[str, int]:
    """Run each user's isolated workspace; one failure never aborts the tick."""
    if state.system_engine is None:
        with get_session(state.engine) as session:
            counts = run_reminder_pass(session, now=now)
        return {"local": counts["followUp"] + counts["events"]}

    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.bootstrap import build_context
    from resume_agent.tenancy.context import use_context
    from resume_agent.tenancy.system_db import User

    with SystemSession(state.system_engine, expire_on_commit=False) as session:
        users = list(
            session.execute(select(User).where(User.disabled_at.is_(None)))
            .scalars()
            .all()
        )
        for user in users:
            session.expunge(user)

    results: dict[str, int] = {}
    for user in users:
        try:
            context = build_context(
                user,
                state.data_dir,
                state.settings,
                state.engine_registry,
                system_engine=state.system_engine,
                template_dir=state.template_config_dir,
            )
            if context.engine is None:
                raise RuntimeError(f"workspace engine unavailable for user {user.id}")
            with use_context(context), get_session(context.engine) as user_session:
                counts = run_reminder_pass(user_session, now=now)
            results[user.id] = counts["followUp"] + counts["events"]
        except Exception as error:  # noqa: BLE001 - isolate users and retry next tick
            logger.warning("reminder pass failed for %s: %s", user.id, error)
    return results


async def reminder_loop(state: Any) -> None:
    while True:
        try:
            await reminder_tick(state)
        except Exception:  # noqa: BLE001 - background loop must survive
            logger.exception("reminder tick crashed")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)
