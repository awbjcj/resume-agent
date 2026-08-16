"""Closed vocabulary for the durable aspect assigned to an evidence bullet."""

from typing import Literal


Aspect = Literal[
    "scope",
    "technical",
    "impact",
    "collaboration",
    "leadership",
    "process",
    "tooling",
    "problem",
]

ASPECTS: tuple[Aspect, ...] = (
    "scope",
    "technical",
    "impact",
    "collaboration",
    "leadership",
    "process",
    "tooling",
    "problem",
)

ASPECT_DESCRIPTIONS: dict[Aspect, str] = {
    "scope": "scale of responsibility, system, users, or budget",
    "technical": "what was built and how",
    "impact": "measured outcome or business result",
    "collaboration": "partners, stakeholders, or cross-functional work",
    "leadership": "ownership, mentoring, driving, or decisions",
    "process": "methodology, standards, reviews, or quality gates",
    "tooling": "automation, infrastructure, or developer experience",
    "problem": "debugging, incidents, root cause, or recovery",
}
