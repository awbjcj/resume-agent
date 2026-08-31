from resume_tailor_harness.gmail.client import EmailMessage
from resume_tailor_harness.gmail.propose import Proposal, propose_transitions
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job


def _email(subject, domain="acme.com"):
    return EmailMessage(
        sender=f"r@{domain}",
        sender_domain=domain,
        subject=subject,
        snippet="",
        message_id=f"mid-{subject}",
    )


def _pair(app_id, status, company):
    job = Job(id=app_id, source="manual", company=company, title="Eng")
    app = Application(id=app_id, job_id=app_id, status=status)
    return (app, job)


def _classify(email):
    subject = email.subject.lower()
    if "offer" in subject:
        return "offer"
    if "interview" in subject:
        return "interview"
    if "unfortunately" in subject:
        return "rejection"
    return "none"


def test_proposes_forward_transition():
    pairs = [_pair(1, ApplicationStatus.submitted.value, "Acme")]
    props = propose_transitions([_email("interview invite")], pairs, _classify)
    assert props == [
        Proposal(
            1,
            "Acme - Eng",
            "submitted",
            "interview",
            "interview invite",
            "mid-interview invite",
        )
    ]


def test_skips_backward_transition():
    pairs = [_pair(1, ApplicationStatus.offer.value, "Acme")]
    assert propose_transitions([_email("interview follow-up")], pairs, _classify) == []


def test_rejection_allowed_from_active_state():
    pairs = [_pair(1, ApplicationStatus.interview.value, "Acme")]
    props = propose_transitions([_email("unfortunately update")], pairs, _classify)
    assert props[0].proposed_status == "rejected"


def test_unmatched_or_none_email_yields_nothing():
    pairs = [_pair(1, ApplicationStatus.submitted.value, "Acme")]
    assert (
        propose_transitions(
            [_email("newsletter", domain="other.com")], pairs, _classify
        )
        == []
    )
