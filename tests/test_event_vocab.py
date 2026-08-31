from resume_tailor_harness.tracking.event_vocab import (
    FUNNEL_KINDS,
    KIND_IMPLIES_STATUS,
    REPEATABLE_KINDS,
    EventKind,
    EventResult,
    Modality,
    Platform,
)
from resume_tailor_harness.tracking.tables import ApplicationStatus


def test_every_kind_except_custom_has_a_status_implication():
    missing = {k.value for k in EventKind} - set(KIND_IMPLIES_STATUS)
    assert missing == {EventKind.custom.value}


def test_status_implications_are_all_real_application_statuses():
    valid = {s.value for s in ApplicationStatus}
    assert set(KIND_IMPLIES_STATUS.values()) <= valid


def test_interview_kinds_all_imply_interview():
    for kind in (
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
    ):
        assert KIND_IMPLIES_STATUS[kind.value] == ApplicationStatus.interview.value


def test_offer_kinds_imply_offer_and_exits_are_terminal():
    assert KIND_IMPLIES_STATUS[EventKind.offer_received.value] == "offer"
    assert KIND_IMPLIES_STATUS[EventKind.offer_deadline.value] == "offer"
    assert KIND_IMPLIES_STATUS[EventKind.rejected.value] == "rejected"
    assert KIND_IMPLIES_STATUS[EventKind.withdrawn.value] == "closed"


def test_repeatable_kinds_are_technical_round_and_offer_received():
    assert REPEATABLE_KINDS == frozenset(
        {EventKind.technical_round.value, EventKind.offer_received.value}
    )


def test_custom_is_excluded_from_the_funnel():
    assert EventKind.custom.value not in FUNNEL_KINDS
    assert FUNNEL_KINDS[0] == EventKind.application_submitted.value


def test_online_assessment_and_questionnaire_are_distinct():
    assert EventKind.online_assessment.value != EventKind.questionnaire.value


def test_async_modality_uses_a_non_keyword_member_name():
    assert Modality.async_.value == "async"


def test_platform_and_result_vocabularies():
    assert "tencent_meeting" in {p.value for p in Platform}
    assert "no_response" in {r.value for r in EventResult}
