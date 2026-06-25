"""Run launch endpoints + GET run. Each launch returns 202 with the run record.

The work callables open their OWN session inside the worker thread — never the
request session, which is not safe to share across threads. The session is bound
to the app engine so `create_app(db_url=...)` and in-memory test databases are
honored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from resume_agent.api.deps import get_run_manager
from resume_agent.api.errors import ApiException
from sse_starlette.sse import EventSourceResponse

from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run, run_events
from resume_agent.api.schemas.runs import (
    AddJobUrlParams,
    CoverLetterParams,
    DiscoverParams,
    PullParams,
    RefreshParams,
    ReprocessParams,
    RunOut,
    TailorParams,
)
from resume_agent.db import get_session
from resume_agent.services.cover_letters import write_cover_letters
from resume_agent.services.discovery import (
    add_job_from_url,
    discover_jobs,
    pull_jobs,
    refresh_jobs,
    reprocess_jobs,
)
from resume_agent.services.tailoring import tailor

router = APIRouter()


def _engine(request: Request):
    return request.app.state.engine


@router.post("/discover", response_model=RunOut, status_code=202)
def launch_discover(
    request: Request,
    params: DiscoverParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return {"statusCounts": discover_jobs(session, reporter=reporter)}

    run_id = mgr.submit("discover", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/reprocess", response_model=RunOut, status_code=202)
def launch_reprocess(
    request: Request,
    params: ReprocessParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    scopes = params.scopes if params is not None and params.scopes else ["shortlisted"]

    def work(reporter):
        with get_session(engine) as session:
            return {"statusCounts": reprocess_jobs(session, scopes=scopes, reporter=reporter)}

    run_id = mgr.submit("reprocess", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/refresh", response_model=RunOut, status_code=202)
def launch_refresh(
    request: Request,
    params: RefreshParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    limit = params.limit if params is not None else None

    def work(reporter):
        with get_session(engine) as session:
            report = refresh_jobs(session, limit=limit, reporter=reporter)
            return {
                "pulled": report.pulled,
                "totals": report.totals,
                "statusCounts": report.status_counts,
                "failures": report.failures,
            }

    run_id = mgr.submit("refresh", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/pull", response_model=RunOut, status_code=202)
def launch_pull(
    params: PullParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            report = pull_jobs(session, limit=params.limit, reporter=reporter)
            return {"totals": report.totals, "failures": report.failures}

    run_id = mgr.submit("pull", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/tailor", response_model=RunOut, status_code=202)
def launch_tailor(
    params: TailorParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            results = tailor(
                session,
                job_ids=params.job_ids,
                approved=params.approved,
                reporter=reporter,
            )
            return {
                "jobs": [
                    {
                        "jobId": jid,
                        "versionCount": len(v),
                        "factCheckPassed": v[-1].fact_check_passed if v else False,
                    }
                    for jid, v in results.items()
                ]
            }

    run_id = mgr.submit("tailor", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/cover-letters", response_model=RunOut, status_code=202)
def launch_cover_letters(
    params: CoverLetterParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            results = write_cover_letters(
                session,
                job_ids=params.job_ids,
                approved=params.approved,
                reporter=reporter,
            )
            return {
                "coverLetters": [
                    {
                        "jobId": r.job_id,
                        "coverLetterId": r.cover_letter_id,
                        "factCheckPassed": r.fact_check_passed,
                    }
                    for r in results
                ]
            }

    run_id = mgr.submit("coverLetter", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.post("/jobs/from-url", response_model=RunOut, status_code=202)
def launch_add_from_url(
    params: AddJobUrlParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        reporter.begin(1, f"Fetching {params.url}")
        with get_session(engine) as session:
            job = add_job_from_url(
                session,
                url=params.url,
                company=params.company,
                title=params.title,
                location=params.location,
                allow_browser=params.allow_browser,
            )
            job_id = job.id if job else None
            duplicate = job is None
        reporter.step(1)
        return {"jobId": job_id, "duplicate": duplicate}

    run_id = mgr.submit("addJobUrl", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    record = mgr.get(run_id)
    if record is None:
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    return record_to_run(run_id, record)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    """Request cooperative cancellation. The worker stops at its next progress
    checkpoint; the run then settles into the ``cancelled`` terminal state."""
    record = mgr.get(run_id)
    if record is None:
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    mgr.request_cancel(run_id)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)


@router.get("/runs/{run_id}/events")
async def stream_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    if mgr.get(run_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    return EventSourceResponse(run_events(mgr, run_id))
