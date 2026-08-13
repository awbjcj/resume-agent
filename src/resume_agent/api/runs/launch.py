"""The run-launch seam shared by every router that starts a background run.

Owns the whole launch tail: submit through RunManager (which derives user_id
and max_concurrent from the active UserContext), map the three launch-time
errors onto the API error envelope, and convert the created record to RunOut.

``session_work`` owns the one threading invariant every worker must honor:
the worker opens its OWN session bound to the app engine — never the request
session, which is not safe to share across threads.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import (
    RunFn,
    RunManager,
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session


def launch(
    mgr: RunManager,
    kind: str,
    work: RunFn,
    *,
    singleton_key: str | None = None,
    singleton_keys: Iterable[str] | None = None,
    singleton_conflict: str = "join",
    meta: dict[str, object] | None = None,
    busy_code: str | None = None,
    busy_message: str = "A run is already active for this item",
) -> RunOut:
    try:
        run_id = mgr.submit(
            kind,
            work,
            singleton_key=singleton_key,
            singleton_keys=singleton_keys,
            singleton_conflict=singleton_conflict,
            meta=meta,
        )
    except RunSingletonConflict as error:
        raise ApiException(
            409,
            busy_code or error.code,
            busy_message,
            details={"runId": error.run_id},
        ) from error
    except RunResetConflict as error:
        raise ApiException(409, error.code, str(error)) from error
    except RunQuotaError as error:
        raise ApiException(429, error.code, str(error)) from error
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


def session_work(engine, fn: Callable[[Any, Any], object]) -> RunFn:
    """Wrap ``fn(session, reporter)`` in a worker-owned session."""

    def work(reporter):
        with get_session(engine) as session:
            return fn(session, reporter)

    return work
