from dataclasses import dataclass

from resume_agent.gmail.match import match_email_to_application
from resume_agent.tracking.tables import Application, ApplicationStatus, Job

_CLASS_TO_STATUS = {
    "rejection": ApplicationStatus.rejected.value,
    "interview": ApplicationStatus.interview.value,
    "assessment": ApplicationStatus.interview.value,
    "offer": ApplicationStatus.offer.value,
}
_RANK = {"ready": 0, "submitted": 1, "interview": 2, "offer": 3}
_TERMINAL = {ApplicationStatus.rejected.value, ApplicationStatus.closed.value}


@dataclass
class Proposal:
    application_id: int
    label: str
    current_status: str
    proposed_status: str
    evidence: str


def _is_forward(current: str, proposed: str) -> bool:
    if current in _TERMINAL:
        return False
    if proposed == ApplicationStatus.rejected.value:
        return True
    return _RANK.get(proposed, 0) > _RANK.get(current, 0)


def propose_transitions(emails, pairs: list[tuple[Application, Job]], classify) -> list[Proposal]:
    """Match emails to applications and propose forward status changes. Applies nothing.

    Emails are expected newest-first. At most one proposal is emitted per
    application — the most recent matching email wins — so that applying the
    list in order cannot regress a status (e.g. a stale "interview" email
    overwriting a newer "rejection").
    """
    by_job_id = {job.id: (app, job) for app, job in pairs if job.id is not None}
    jobs = [job for _, job in pairs]
    proposals: list[Proposal] = []
    proposed_app_ids: set[int] = set()
    for email in emails:
        job = match_email_to_application(email, jobs)
        if job is None or job.id not in by_job_id:
            continue
        app, job = by_job_id[job.id]
        if app.id is None or app.id in proposed_app_ids:
            continue
        proposed = _CLASS_TO_STATUS.get(classify(email))
        if proposed is None or not _is_forward(app.status, proposed):
            continue
        proposed_app_ids.add(app.id)
        proposals.append(
            Proposal(app.id, f"{job.company} - {job.title}", app.status, proposed, email.subject)
        )
    return proposals
