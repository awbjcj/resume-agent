import re

from resume_agent.gmail.client import EmailMessage
from resume_agent.tracking.tables import Job


def _company_token(company: str) -> str:
    """First alphanumeric word of a company name, lowercased."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    return words[0] if words else ""


def match_email_to_application(email: EmailMessage, jobs: list[Job]) -> Job | None:
    """Return the job whose company appears in the sender domain or message text."""
    haystack = f"{email.subject} {email.snippet}".lower()
    domain = (email.sender_domain or "").lower()
    for job in jobs:
        if not job.company:
            continue
        token = _company_token(job.company)
        if token and (token in domain or token in haystack):
            return job
    return None
