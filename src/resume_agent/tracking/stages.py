"""The pipeline status ladder and the single status-write helper.

Status doubles as "where a job is in the funnel" and "how far it has got".
Redo needs the second reading: a rendered job that is re-tailored is still
rendered. `advance` is the one place that distinction is enforced.
"""

from __future__ import annotations

from resume_agent.tracking.tables import Job, JobStatus

# rejected sits below raw deliberately: it makes "redo never rejects" a
# consequence of "redo never regresses" rather than a separate rule.
_RANK: dict[str, int] = {
    JobStatus.rejected.value: -1,
    JobStatus.raw.value: 0,
    JobStatus.extracted.value: 1,
    JobStatus.filtered.value: 2,
    JobStatus.shortlisted.value: 3,
    JobStatus.approved.value: 4,
    JobStatus.tailored.value: 5,
    JobStatus.rendered.value: 6,
}


def rank(status: str) -> int:
    """Ladder position of a status. Unknown statuses rank as raw."""
    return _RANK.get(status, 0)


def advance(job: Job, target: str, *, never_regress: bool) -> bool:
    """Move job.status toward target. Returns whether it wrote."""
    if never_regress and rank(target) < rank(job.status):
        return False
    job.status = target
    return True
