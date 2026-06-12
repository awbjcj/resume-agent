from resume_agent.gmail.client import EmailMessage
from resume_agent.gmail.match import match_email_to_application
from resume_agent.tracking.tables import Job


def _job(id_, company):
    return Job(id=id_, source="manual", company=company, title="Eng")


def test_matches_company_in_sender_domain():
    email = EmailMessage(sender="ta@acme.com", sender_domain="acme.com", subject="Hi", snippet="")
    job = match_email_to_application(email, [_job(1, "Acme Corp"), _job(2, "Beta")])
    assert job is not None
    assert job.id == 1


def test_matches_company_in_subject_text():
    email = EmailMessage(
        sender="noreply@greenhouse.io",
        sender_domain="greenhouse.io",
        subject="Your application to Beta",
        snippet="",
    )
    job = match_email_to_application(email, [_job(1, "Acme"), _job(2, "Beta")])
    assert job is not None
    assert job.id == 2


def test_no_match_returns_none():
    email = EmailMessage(sender="x@unknown.com", sender_domain="unknown.com", subject="Newsletter", snippet="")
    assert match_email_to_application(email, [_job(1, "Acme")]) is None
