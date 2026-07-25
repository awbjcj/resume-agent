from resume_agent.tracking.stages import advance, rank
from resume_agent.tracking.tables import Job, JobStatus


def _job(status: str) -> Job:
    return Job(source="manual", jd_text="jd", status=status)


def test_rank_orders_the_pipeline():
    assert rank(JobStatus.raw.value) < rank(JobStatus.extracted.value)
    assert rank(JobStatus.extracted.value) < rank(JobStatus.filtered.value)
    assert rank(JobStatus.filtered.value) < rank(JobStatus.shortlisted.value)
    assert rank(JobStatus.shortlisted.value) < rank(JobStatus.approved.value)
    assert rank(JobStatus.approved.value) < rank(JobStatus.tailored.value)
    assert rank(JobStatus.tailored.value) < rank(JobStatus.rendered.value)


def test_rejected_ranks_below_raw():
    # This is what makes "redo never rejects" fall out of "redo never regresses"
    # instead of needing its own branch.
    assert rank(JobStatus.rejected.value) < rank(JobStatus.raw.value)


def test_unknown_status_ranks_as_raw():
    assert rank("nonsense") == rank(JobStatus.raw.value)


def test_advance_writes_forward_moves_when_never_regress():
    job = _job(JobStatus.approved.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is True
    assert job.status == JobStatus.tailored.value


def test_advance_refuses_backward_moves_when_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is False
    assert job.status == JobStatus.rendered.value


def test_advance_refuses_rejection_when_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.rejected.value, never_regress=True) is False
    assert job.status == JobStatus.rendered.value


def test_advance_allows_backward_moves_when_not_never_regress():
    job = _job(JobStatus.rendered.value)
    assert advance(job, JobStatus.raw.value, never_regress=False) is True
    assert job.status == JobStatus.raw.value


def test_advance_is_a_noop_write_at_equal_rank():
    job = _job(JobStatus.tailored.value)
    assert advance(job, JobStatus.tailored.value, never_regress=True) is True
    assert job.status == JobStatus.tailored.value
