"""Structured-output turn helpers shared by the coach and interviewer stacks."""

from __future__ import annotations

from resume_agent.llm_runner import expect_schema


class TurnRejected(ValueError):
    """A formatted turn failed validation against the session's rules."""


def format_with_retry(formatter, notes: object, schema, validate, *, label: str):
    """Format untrusted notes into ``schema`` and validate, retrying once.

    The retry feeds the rejection reason back to the formatter; a second
    rejection propagates. Non-``schema`` output raises ``UnparsedAgentOutput``
    (a TypeError) immediately, carrying the model, provider, token counts, and a
    response head/tail -- this seam is shared by the coach and interview stacks,
    so a truncated or rejected turn is diagnosable in both without a redeploy.
    """
    prompt = f"{label} (UNTRUSTED):\n{notes}"
    formatted = expect_schema(formatter.run(prompt), schema, source=label)
    try:
        return validate(formatted)
    except TurnRejected as first:
        result = formatter.run(f"{prompt}\n\nPREVIOUS OUTPUT REJECTED: {first}")
        try:
            retry = expect_schema(result, schema, source=f"{label} retry")
        except TypeError as exc:
            raise exc from first
        return validate(retry)
