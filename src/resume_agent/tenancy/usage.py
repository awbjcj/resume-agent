from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.system_db import UsageEvent

logger = logging.getLogger(__name__)

WEIGHT_INPUT = 1.0
WEIGHT_OUTPUT = 3.0
WEIGHT_CACHE_READ = 0.1
WEIGHT_CACHE_CREATION = 1.25


def _metric(metrics: object, name: str) -> int:
    value = (
        metrics.get(name, 0) if isinstance(metrics, dict) else getattr(metrics, name, 0)
    ) or 0
    if isinstance(value, (list, tuple)):
        value = sum(item or 0 for item in value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _model_id(agent: object) -> str:
    model = getattr(agent, "model", None)
    value = getattr(model, "id", None) or getattr(agent, "model_id", None)
    return value if isinstance(value, str) else ""


def record_call(agent: object, response: object) -> None:
    context = current_context()
    if context is None or context.system_engine is None:
        return
    try:
        metrics = getattr(response, "metrics", None)
        input_tokens = _metric(metrics, "input_tokens")
        output_tokens = _metric(metrics, "output_tokens")
        cache_read_tokens = _metric(metrics, "cache_read_tokens")
        cache_creation_tokens = _metric(metrics, "cache_creation_tokens")
        model_id = _model_id(agent)
        from resume_agent.llm_runner import split_provider

        provider = split_provider(model_id)[0] if model_id else None
        event = UsageEvent(
            user_id=context.user_id,
            provider=provider,
            model=model_id or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            weighted_total=(
                input_tokens * WEIGHT_INPUT
                + output_tokens * WEIGHT_OUTPUT
                + cache_read_tokens * WEIGHT_CACHE_READ
                + cache_creation_tokens * WEIGHT_CACHE_CREATION
            ),
            own_key=provider in context.own_key_providers if provider else False,
        )
        with Session(context.system_engine) as session:
            session.add(event)
            session.commit()
    except Exception:
        logger.warning("usage recording failed", exc_info=True)
