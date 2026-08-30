"""Read and explicitly generate job-scoped role-preparation briefs."""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_engine, get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.launch import launch, session_work
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.role_preparation import (
    RolePreparationBriefOut,
    RolePreparationEmptyOut,
    RolePreparationOut,
    RolePreparationReadyOut,
    RolePreparationUnavailableOut,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.role_preparation.agents import build_role_preparation_formatter
from resume_agent.services.company_intelligence import load_company_intelligence
from resume_agent.services.role_preparation import (
    build_role_preparation_inputs,
    generate_role_preparation_brief,
    load_role_preparation_brief,
    role_preparation_inputs_changed,
)
from resume_agent.tracking.tables import Job

router = APIRouter()


def _resource(session: Session, job: Job) -> RolePreparationOut:
    if not job.jd_text.strip():
        return RolePreparationUnavailableOut(
            reason="missing_job_description",
            message="Add a job description before generating role preparation.",
        )
    if load_company_intelligence(session, job.company) is None:
        return RolePreparationUnavailableOut(
            reason="company_intelligence_required",
            message="Research the company before generating role preparation.",
        )
    brief = load_role_preparation_brief(session, job.id or 0)
    if brief is None:
        return RolePreparationEmptyOut(
            message="Generate a role-specific brief from this job and company dossier."
        )
    return RolePreparationReadyOut(
        inputs_changed=role_preparation_inputs_changed(session, brief),
        brief=RolePreparationBriefOut.from_brief(brief),
    )


@router.get(
    "/jobs/{job_id}/role-preparation-brief",
    response_model=RolePreparationOut,
)
def get_role_preparation_brief(
    job_id: int,
    session: Session = Depends(get_session),
) -> RolePreparationOut:
    job = session.get(Job, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    return _resource(session, job)


@router.post(
    "/jobs/{job_id}/role-preparation-brief/refreshes",
    response_model=RunOut,
    status_code=202,
)
def create_role_preparation_refresh(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
) -> RunOut:
    job = session.get(Job, job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    if build_role_preparation_inputs(session, job_id) is None:
        raise ApiException(
            409,
            "ROLE_PREPARATION_UNAVAILABLE",
            "A job description and saved company dossier are required",
        )
    engine = get_engine(request)

    def do_generate(worker_session: Session, reporter):
        reporter.begin(1, f"Preparing for {job.title or 'this role'}")
        generate_role_preparation_brief(
            worker_session,
            job_id=job_id,
            formatter=build_role_preparation_formatter(),
            reporter=reporter,
        )
        reporter.step(1)
        return {"jobId": job_id}

    return launch(
        mgr,
        "rolePreparation",
        session_work(engine, do_generate),
        singleton_key=f"role-preparation:{job_id}",
        singleton_conflict="raise",
        meta={"jobId": job_id},
        busy_message="Role preparation is already running for this job",
    )
