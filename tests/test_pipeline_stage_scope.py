import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.pipeline import StageScope, _stage_jobs, run_filter
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def _job(session, status: str, **criteria) -> Job:
    return save_job(
        session,
        Job(
            source="manual",
            jd_text="jd",
            status=status,
            criteria_json=JobCriteria(**criteria).model_dump(mode="json"),
        ),
    )


# apply_filters rejects when the job's yoe_min exceeds the config's yoe_max.
# That is the cheapest deterministic rejection available (see discovery/filter.py).
REJECTING_CONFIG = SearchConfig(yoe_max=0)
REJECTED_CRITERIA = {"yoe_min": 5}


def test_default_scope_selects_by_status_only(session):
    extracted = _job(session, JobStatus.extracted.value)
    _job(session, JobStatus.rendered.value)

    rows = _stage_jobs(session, JobStatus.extracted.value, StageScope())

    assert [row.id for row in rows] == [extracted.id]


def test_id_scope_still_filters_by_status(session):
    extracted = _job(session, JobStatus.extracted.value)
    rendered = _job(session, JobStatus.rendered.value)
    assert extracted.id is not None
    assert rendered.id is not None

    scope = StageScope(job_ids=frozenset({extracted.id, rendered.id}))
    rows = _stage_jobs(session, JobStatus.extracted.value, scope)

    assert [row.id for row in rows] == [extracted.id]


def test_any_status_scope_selects_the_ids_whatever_their_status(session):
    rendered = _job(session, JobStatus.rendered.value)
    assert rendered.id is not None

    scope = StageScope(job_ids=frozenset({rendered.id}), any_status=True)
    rows = _stage_jobs(session, JobStatus.extracted.value, scope)

    assert [row.id for row in rows] == [rendered.id]


def test_never_regress_scope_suppresses_rejection(session):
    rendered = _job(session, JobStatus.rendered.value, **REJECTED_CRITERIA)
    assert rendered.id is not None

    run_filter(
        session,
        REJECTING_CONFIG,
        StageScope(
            job_ids=frozenset({rendered.id}), any_status=True, never_regress=True
        ),
    )

    session.refresh(rendered)
    assert rendered.status == JobStatus.rendered.value
    # A suppressed rejection must not leave a reason behind: the triage board
    # filters on reject_reason.
    assert rendered.reject_reason is None


def test_default_scope_still_rejects(session):
    extracted = _job(session, JobStatus.extracted.value, **REJECTED_CRITERIA)

    run_filter(session, REJECTING_CONFIG, StageScope())

    session.refresh(extracted)
    assert extracted.status == JobStatus.rejected.value
    assert extracted.reject_reason == "requires more experience than yoe_max"
