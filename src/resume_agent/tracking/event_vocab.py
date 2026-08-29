"""Closed vocabularies for application timeline events.

Kept free of SQLModel and of any session import: these are the values an
auditor of the amended status invariant reads, and the values the funnel
analytics group by. Pure data, importable from anywhere.
"""

from __future__ import annotations

from enum import Enum


class EventKind(str, Enum):
    application_submitted = "application_submitted"
    recruiter_screen = "recruiter_screen"
    online_assessment = "online_assessment"
    questionnaire = "questionnaire"
    technical_phone_screen = "technical_phone_screen"
    technical_round = "technical_round"
    system_design = "system_design"
    behavioral = "behavioral"
    hiring_manager = "hiring_manager"
    onsite_loop = "onsite_loop"
    team_match = "team_match"
    offer_received = "offer_received"
    offer_deadline = "offer_deadline"
    rejected = "rejected"
    withdrawn = "withdrawn"
    custom = "custom"


class Modality(str, Enum):
    onsite = "onsite"
    virtual = "virtual"
    phone = "phone"
    async_ = "async"  # `async` is a Python keyword; the wire value is "async"


class Platform(str, Enum):
    zoom = "zoom"
    teams = "teams"
    google_meet = "google_meet"
    webex = "webex"
    tencent_meeting = "tencent_meeting"
    feishu = "feishu"
    phone = "phone"
    hackerrank = "hackerrank"
    codesignal = "codesignal"
    coderpad = "coderpad"
    karat = "karat"
    other = "other"


class EventResult(str, Enum):
    pending = "pending"
    advanced = "advanced"
    rejected = "rejected"
    no_response = "no_response"  # ghosting is not rejection
    cancelled = "cancelled"
    withdrew = "withdrew"


_INTERVIEW_KINDS = (
    EventKind.recruiter_screen,
    EventKind.online_assessment,
    EventKind.questionnaire,
    EventKind.technical_phone_screen,
    EventKind.technical_round,
    EventKind.system_design,
    EventKind.behavioral,
    EventKind.hiring_manager,
    EventKind.onsite_loop,
    EventKind.team_match,
)

KIND_IMPLIES_STATUS: dict[str, str] = {
    EventKind.application_submitted.value: "submitted",
    **{kind.value: "interview" for kind in _INTERVIEW_KINDS},
    EventKind.offer_received.value: "offer",
    EventKind.offer_deadline.value: "offer",
    EventKind.rejected.value: "rejected",
    EventKind.withdrawn.value: "closed",
}
"""What logging an event implies about Application.status.

`custom` is deliberately absent: a user-labelled event says nothing about the
funnel, so it never moves status.
"""

REPEATABLE_KINDS: frozenset[str] = frozenset(
    {EventKind.technical_round.value, EventKind.offer_received.value}
)
"""Kinds that legitimately occur more than once and carry a `sequence`.

`offer_received` repeats because a negotiated revision is a new event, which
is what gives negotiation history for free.
"""

FUNNEL_KINDS: tuple[str, ...] = (
    EventKind.application_submitted.value,
    EventKind.recruiter_screen.value,
    EventKind.online_assessment.value,
    EventKind.questionnaire.value,
    EventKind.technical_phone_screen.value,
    EventKind.technical_round.value,
    EventKind.system_design.value,
    EventKind.behavioral.value,
    EventKind.hiring_manager.value,
    EventKind.onsite_loop.value,
    EventKind.team_match.value,
    EventKind.offer_received.value,
)
"""Funnel order for the Sankey and cycle-time charts (Phase 3).

`custom` is excluded so user-labelled events cannot distort the numbers;
`offer_deadline`, `rejected`, and `withdrawn` are excluded because they are
not stages a candidate passes through.
"""
