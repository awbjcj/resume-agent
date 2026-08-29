"""How an event moves Application.status. See ADR-0012.

A flat high-water mark cannot express the most common transition in a job
hunt: `interview -> rejected`. `rejected` is not *behind* `interview`, it is
an *exit*. So the rule has two halves — an ordered progression that only
advances, and a terminal set reachable from anywhere. This mirrors
`gmail/propose.py`'s existing `_TERMINAL` rather than inventing a second rule.
"""

from __future__ import annotations

PROGRESSION: tuple[str, ...] = ("ready", "submitted", "interview", "offer")
TERMINAL: frozenset[str] = frozenset({"rejected", "closed"})


def advance_application_status(current: str, implied: str) -> str:
    """Return the status after an event implying `implied` is logged.

    Never raises: an unrecognised `implied` is a no-op, because a vocabulary
    gap must not block recording what happened.
    """
    if implied in TERMINAL:
        return implied
    if current in TERMINAL:
        return current  # an exit is not undone by logging an earlier stage
    if implied not in PROGRESSION or current not in PROGRESSION:
        return current
    return (
        implied
        if PROGRESSION.index(implied) > PROGRESSION.index(current)
        else current
    )
