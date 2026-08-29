"""Background Gmail sync: one asyncio task, one serial pass per tick.

Each user's pass is isolated — a revoked token or quota error never
aborts the loop. Runs are submitted through the RunManager so scheduled
syncs appear on the Runs page and share the per-user gmailSync singleton
with the manual endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from sqlalchemy import select

from resume_agent.api.runs.models import ACTIVE_RUN_STATES
from resume_agent.gmail.auth import token_path
from resume_agent.services.gmail_sync import run_gmail_sync
from resume_agent.tenancy.context import use_context
from resume_agent.tenancy.workspace import workspace_paths

logger = logging.getLogger(__name__)

_POLL_SECONDS = 1.0
_MAX_WAIT_SECONDS = 900


async def _wait_terminal(run_manager: Any, run_id: str) -> None:
    for _ in range(int(_MAX_WAIT_SECONDS / _POLL_SECONDS)):
        snapshot = run_manager.get(run_id)
        if snapshot is None or snapshot.state not in ACTIVE_RUN_STATES:
            return
        await asyncio.sleep(_POLL_SECONDS)


def _submit(
    state: Any, engine: Any, work: Callable[..., dict], user_id: str | None
) -> str:
    def run(reporter):
        return work(engine, reporter)

    return state.run_manager.submit(
        "gmailSync",
        run,
        singleton_key="gmailSync",
        user_id=user_id,
        meta={"scheduled": True},
    )


async def tick(
    state: Any, *, work: Callable[..., dict] = run_gmail_sync
) -> dict[str, str]:
    """One serial pass over every connected owner. Never raises per-user errors."""
    results: dict[str, str] = {}
    if state.system_engine is None:
        if token_path(state.data_dir).is_file():
            try:
                run_id = _submit(state, state.engine, work, user_id=None)
                results["local"] = run_id
                await _wait_terminal(state.run_manager, run_id)
            except Exception as exc:  # noqa: BLE001 — isolate; next tick retries
                logger.warning("scheduled gmail sync failed: %s", exc)
                results["local"] = f"error: {exc}"
        return results

    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.bootstrap import build_context
    from resume_agent.tenancy.system_db import User

    with SystemSession(state.system_engine, expire_on_commit=False) as session:
        users = list(
            session.execute(select(User).where(User.disabled_at.is_(None)))
            .scalars()
            .all()
        )
        for user in users:
            session.expunge(user)
    for user in users:
        paths = workspace_paths(state.data_dir, user.id)
        if not paths.gmail_token.is_file():
            continue
        try:
            context = build_context(
                user,
                state.data_dir,
                state.settings,
                state.engine_registry,
                system_engine=state.system_engine,
                template_dir=state.template_config_dir,
            )
            state.run_manager.register_root(context.paths.runs_root)
            with use_context(context):
                run_id = _submit(state, context.engine, work, user_id=user.id)
            results[user.id] = run_id
            await _wait_terminal(state.run_manager, run_id)
        except Exception as exc:  # noqa: BLE001 — one user never aborts the loop
            logger.warning("scheduled gmail sync failed for %s: %s", user.id, exc)
            results[user.id] = f"error: {exc}"
    return results


async def scheduler_loop(state: Any) -> None:
    interval_hours = state.settings.gmail_sync_interval_hours
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            await tick(state)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            logger.exception("gmail scheduler tick crashed")
