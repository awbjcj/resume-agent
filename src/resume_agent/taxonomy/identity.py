"""Stable identifiers shared across taxonomy and profile layers."""

from __future__ import annotations

from urllib.parse import quote

from resume_agent.tracking.match_gap import normalize_skill


def legacy_concept_id(token: str) -> str:
    """Return the stable graph ID for one normalized legacy skill token."""
    normalized = normalize_skill(token)
    if not normalized:
        raise ValueError("legacy concept token must normalize to a non-empty value")
    return f"legacy:skill:{quote(normalized, safe='')}"


def typed_concept_id(concept_type: str, label: str) -> str:
    """Return a stable provisional ID for a typed source phrase."""
    normalized = normalize_skill(label)
    if not normalized:
        raise ValueError("typed concept label must normalize to a non-empty value")
    return f"observed:{quote(concept_type, safe='')}:{quote(normalized, safe='')}"
