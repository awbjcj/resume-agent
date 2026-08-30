"""Read and explicitly refresh public hiring-contact intelligence."""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_engine, get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.launch import launch, session_work
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.hiring_contacts import (
    HiringContactEmptyOut,
    HiringContactIntelligenceOut,
    HiringContactReadyOut,
    HiringContactResourceOut,
    HiringContactUnavailableOut,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.hiring_contacts.agents import (
    build_hiring_contact_formatter,
    build_hiring_contact_researcher,
)
from resume_agent.services.hiring_contacts import (
    generate_hiring_contact_intelligence,
    load_hiring_contact_intelligence,
)
from resume_agent.tracking.tables import Job

router = APIRouter()


def _resource(session: Session, job: Job) -> HiringContactResourceOut:
    if not job.company.strip():
        return HiringContactUnavailableOut(
            message="Add a company before researching public hiring contacts."
        )
    artifact = load_hiring_contact_intelligence(session, job.id or 0)
    if artifact is None:
        return HiringContactEmptyOut(
            message="Search public sources for people relevant to this role."
        )
    return HiringContactReadyOut(
        intelligence=HiringContactIntelligenceOut.from_artifact(artifact)
    )


@router.get(
    "/jobs/{job_id}/hiring-contact-intelligence",
    response_model=HiringContactResourceOut,
)
def get_hiring_contact_intelligence(
    job_id: int, session: Session = Depends(get_session)
) -> HiringContactResourceOut:
    job = session.get(Job, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return _resource(session, job)


@router.post(
    "/jobs/{job_id}/hiring-contact-intelligence/refreshes",
    response_model=RunOut,
    status_code=202,
)
def create_hiring_contact_refresh(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
) -> RunOut:
    job = session.get(Job, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if not job.company.strip():
        raise ApiException(
            409,
            "HIRING_CONTACT_INTELLIGENCE_UNAVAILABLE",
            "A company is required",
        )
    engine = get_engine(request)

    def do_generate(worker_session: Session, reporter):
        reporter.begin(2, f"Researching public contacts at {job.company}")
        generate_hiring_contact_intelligence(
            worker_session,
            job_id=job_id,
            researcher=build_hiring_contact_researcher(),
            formatter=build_hiring_contact_formatter(),
            reporter=reporter,
        )
        reporter.step(2)
        return {"jobId": job_id}

    return launch(
        mgr,
        "hiringContactIntelligence",
        session_work(engine, do_generate),
        singleton_key=f"hiring-contact-intelligence:{job_id}",
        singleton_conflict="raise",
        meta={"jobId": job_id},
        busy_message="Hiring-contact research is already running for this job",
    )
