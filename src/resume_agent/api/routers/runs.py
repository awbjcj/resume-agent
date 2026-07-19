"""Run launch endpoints + GET run. Each launch returns 202 with the run record.

The work callables open their OWN session inside the worker thread — never the
request session, which is not safe to share across threads. The session is bound
to the app engine so `create_app(db_url=...)` and in-memory test databases are
honored.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter, Depends, Query, Request, UploadFile

from resume_agent.api.deps import get_engine, get_run_manager, get_sse_user_context
from resume_agent.api.errors import ApiException
from resume_agent.api.uploads import UploadTooLargeError, read_upload
from resume_agent.api.mappers import to_page
from sse_starlette.sse import EventSourceResponse

from resume_agent.api.runs.manager import RunManager, RunQuotaError, RunSingletonConflict
from resume_agent.api.schemas.jobs import ReviseRequest
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
from resume_agent.api.schemas.base import Page
from resume_agent.config import get_settings
from resume_agent.db import get_session
from resume_agent.services.cover_letters import write_cover_letters
from resume_agent.services.cover_letter_revision import revise_cover_letter_version
from resume_agent.services.discovery import (
    add_job_from_url,
    discover_jobs,
    pull_jobs,
    refresh_jobs,
    reprocess_jobs,
    scrape_linkedin_jobs,
)
from resume_agent.services.errors import record_source_failures
from resume_agent.services.tailoring import DEFAULT_REVIEW, DEFAULT_REVIEW_DEEP, tailor
from resume_agent.services.pagination import paginate
from resume_agent.services.revision import revise_resume_version
from resume_agent.tracking.repository import get_cover_letter, get_resume_version
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.limits import DEFAULT_MAX_CONCURRENT_RUNS, active_limit

router = APIRouter()
link_router = APIRouter()


def _engine(request: Request):
    return get_engine(request)


class _WorkspaceArgs(TypedDict):
    search_path: str
    facts_path: str


def _workspace_args() -> _WorkspaceArgs:
    context = current_context()
    if context is None:
        return {
            "search_path": "config/search.yaml",
            "facts_path": "data/profile/facts.json",
        }
    return {
        "search_path": str(context.paths.config_dir / "search.yaml"),
        "facts_path": str(context.paths.profile_dir / "facts.json"),
    }


def _submit(
    mgr: RunManager,
    kind: str,
    work,
    *,
    singleton_key: str | None = None,
    singleton_conflict: str = "join",
    meta: dict[str, object] | None = None,
) -> str:
    context = current_context()
    try:
        return mgr.submit(
            kind,
            work,
            singleton_key=singleton_key,
            singleton_conflict=singleton_conflict,
            meta=meta,
            user_id=context.user_id if context is not None else None,
            max_concurrent=active_limit(
                "max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS
            ),
        )
    except RunSingletonConflict as error:
        raise ApiException(
            409,
            error.code,
            "A revision is already running for this item",
            details={"runId": error.run_id},
        ) from error
    except RunQuotaError as error:
        raise ApiException(429, error.code, str(error)) from error


def _owned_record(mgr: RunManager, run_id: str):
    record = mgr.get(run_id)
    context = current_context()
    if record is None or (context is not None and record.user_id != context.user_id):
        raise ApiException(404, "NOT_FOUND", f"Run {run_id} not found")
    return record


@router.post("/resume-versions/{version_id}/revise", response_model=RunOut, status_code=202)
def launch_resume_revise(
    version_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        parent = get_resume_version(session, version_id)
        if parent is None:
            raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
        job_id = parent.job_id

    def work(reporter):
        reporter.begin(1, f"Revising resume version #{version_id}")
        with get_session(engine) as session:
            context = current_context()
            child = revise_resume_version(
                session,
                version_id,
                body.instruction,
                re_review=body.re_review,
                review_path=str(context.paths.config_dir / "review.yaml") if context else "config/review.yaml",
                facts_path=_workspace_args()["facts_path"],
            )
        reporter.step(1)
        return {"versionId": child.id if child else None, "jobId": child.job_id if child else job_id}

    meta = {"versionId": version_id, "jobId": job_id, "instruction": body.instruction, "reReview": body.re_review}
    run_id = _submit(mgr, "revise", work, singleton_key=f"revise:{version_id}", singleton_conflict="raise", meta=meta)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/cover-letters/{cover_letter_id}/revise", response_model=RunOut, status_code=202)
def launch_cover_letter_revise(
    cover_letter_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        parent = get_cover_letter(session, cover_letter_id)
        if parent is None:
            raise ApiException(404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found")
        job_id = parent.job_id

    def work(reporter):
        reporter.begin(1, f"Revising cover letter #{cover_letter_id}")
        with get_session(engine) as session:
            child = revise_cover_letter_version(
                session,
                cover_letter_id,
                body.instruction,
                facts_path=_workspace_args()["facts_path"],
            )
        reporter.step(1)
        return {"coverLetterId": child.id if child else None, "jobId": child.job_id if child else job_id}

    meta = {"coverLetterId": cover_letter_id, "jobId": job_id, "instruction": body.instruction}
    run_id = _submit(mgr, "coverLetterRevise", work, singleton_key=f"cover-letter-revise:{cover_letter_id}", singleton_conflict="raise", meta=meta)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/jobs/import-urls", response_model=RunOut, status_code=202)
def launch_import_urls(
    file: UploadFile,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    try:
        raw = read_upload(file, max_bytes=2 * 1024 * 1024).decode("utf-8")
    except UploadTooLargeError as exc:
        raise ApiException(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise ApiException(400, "INVALID_FILE", "URL list must be UTF-8") from exc
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise ApiException(400, "NO_URLS", "The file contains no URL entries")
    if len(lines) > 10_000:
        raise ApiException(400, "TOO_MANY_URLS", "URL list exceeds 10,000 lines")
    valid_urls = [
        line for line in lines if line.startswith(("http://", "https://"))
    ]
    invalid_lines = [line for line in lines if line not in valid_urls]
    engine = _engine(request)
    allow_browser = get_settings().browser_enabled

    def work(reporter):
        reporter.begin(len(lines), "Importing job URLs")
        added = 0
        duplicates = 0
        failures = {line: "Invalid URL: expected http(s)" for line in invalid_lines}
        current = 0
        for line in invalid_lines:
            current += 1
            reporter.step(current, label=line)
        for url in valid_urls:
            reporter.checkpoint()
            try:
                with get_session(engine) as session:
                    job = add_job_from_url(
                        session, url=url, allow_browser=allow_browser
                    )
                if job is None:
                    duplicates += 1
                else:
                    added += 1
            except Exception as error:  # noqa: BLE001 - isolate each URL
                failures[url] = f"{type(error).__name__}: {error}"
            current += 1
            reporter.step(current, label=url)
        return {
            "added": added,
            "duplicates": duplicates,
            "failures": failures,
        }

    run_id = _submit(mgr, "importUrls", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/discover", response_model=RunOut, status_code=202)
def launch_discover(
    request: Request,
    params: DiscoverParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return {
                "statusCounts": discover_jobs(
                    session, reporter=reporter, **_workspace_args()
                )
            }

    run_id = _submit(mgr, "discover", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


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
            return {
                "statusCounts": reprocess_jobs(
                    session, scopes=scopes, reporter=reporter, **_workspace_args()
                )
            }

    run_id = _submit(mgr, "reprocess", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


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
            paths = _workspace_args()
            context = current_context()
            report = refresh_jobs(
                session,
                limit=limit,
                reporter=reporter,
                connectors_path=str(context.paths.config_dir / "connectors.yaml")
                if context is not None
                else "config/connectors.yaml",
                telemetry_path=str(context.workspace / "connector_runs.json")
                if context is not None
                else "data/connector_runs.json",
                **paths,
            )
        if report.failures:
            with get_session(engine) as error_session:
                record_source_failures(
                    error_session, report.failures, run_id=reporter.run_id
                )
        return {
            "pulled": report.pulled,
            "totals": report.totals,
            "statusCounts": report.status_counts,
            "failures": report.failures,
        }

    run_id = _submit(mgr, "refresh", work, singleton_key="refresh")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/pull", response_model=RunOut, status_code=202)
def launch_pull(
    params: PullParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            context = current_context()
            report = pull_jobs(
                session,
                search_path=_workspace_args()["search_path"],
                connectors_path=str(context.paths.config_dir / "connectors.yaml")
                if context is not None
                else "config/connectors.yaml",
                telemetry_path=str(context.workspace / "connector_runs.json")
                if context is not None
                else "data/connector_runs.json",
                limit=params.limit,
                source_ids=params.source_ids,
                reporter=reporter,
                skip_known=not bool(params.refresh),
            )
        if report.failures:
            with get_session(engine) as error_session:
                record_source_failures(
                    error_session, report.failures, run_id=reporter.run_id
                )
        return {
            "totals": report.totals,
            "upgraded": report.upgraded,
            "skipped": report.skipped,
            "failures": report.failures,
        }

    run_id = _submit(mgr, "pull", work, singleton_key="pull")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/tailor", response_model=RunOut, status_code=202)
def launch_tailor(
    params: TailorParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            context = current_context()
            results = tailor(
                session,
                job_ids=params.job_ids,
                approved=params.approved,
                review_path=str(
                    context.paths.config_dir
                    / ("review_deep.yaml" if params.deep else "review.yaml")
                )
                if context is not None
                else (DEFAULT_REVIEW_DEEP if params.deep else DEFAULT_REVIEW),
                facts_path=_workspace_args()["facts_path"],
                reporter=reporter,
                fail_on_partial=True,
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

    run_id = _submit(mgr, "tailor", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


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
                facts_path=_workspace_args()["facts_path"],
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

    run_id = _submit(mgr, "coverLetter", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/gmail/sync", response_model=RunOut, status_code=202)
def launch_gmail_sync(request: Request, mgr: RunManager = Depends(get_run_manager)):
    from resume_agent.gmail.auth import load_credentials

    engine = _engine(request)
    if load_credentials() is None:
        raise ApiException(
            409, "GMAIL_NOT_CONNECTED", "Connect Gmail in Settings before syncing"
        )

    def work(reporter):
        from resume_agent.services.gmail_sync import run_gmail_sync

        return run_gmail_sync(engine, reporter)

    run_id = _submit(mgr, "gmailSync", work, singleton_key="gmailSync")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


def _linkedin_ready() -> bool:
    """Return whether credentials or a persisted browser profile are available."""
    settings = get_settings()
    if not getattr(settings, "browser_enabled", True):
        return False
    if settings.linkedin_email.strip() and settings.linkedin_password:
        return True
    if not settings.linkedin_user_data_dir:
        return False
    profile = Path(settings.linkedin_user_data_dir)
    return profile.is_dir() and any(profile.iterdir())


@router.post("/sources/linkedin/scrape", response_model=RunOut, status_code=202)
def launch_linkedin_scrape(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    """Scrape LinkedIn; the worker opens a visible browser on the server host."""
    if not _linkedin_ready():
        raise ApiException(
            409,
            "LINKEDIN_NOT_CONFIGURED",
            "LinkedIn needs a saved browser profile or configured email and password. "
            "Run `resume-agent scrape` locally once to create the profile.",
        )
    engine = _engine(request)

    def work(reporter):
        with get_session(engine) as session:
            return scrape_linkedin_jobs(
                session,
                reporter=reporter,
                search_path=_workspace_args()["search_path"],
            )

    run_id = _submit(mgr, "linkedinScrape", work, singleton_key="linkedinScrape")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


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

    run_id = _submit(mgr, "addJobUrl", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.get("/runs", response_model=Page[RunOut])
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, alias="pageSize", ge=1, le=200),
    mgr: RunManager = Depends(get_run_manager),
):
    context = current_context()
    return to_page(
        paginate(
            mgr.list_rehydratable(
                user_id=context.user_id if context is not None else None
            ),
            page=page,
            page_size=page_size,
        ),
        RunOut,
    )


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    record = _owned_record(mgr, run_id)
    return record_to_run(record)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: str, mgr: RunManager = Depends(get_run_manager)):
    """Request cooperative cancellation. The worker stops at its next progress
    checkpoint; the run then settles into the ``cancelled`` terminal state."""
    record = _owned_record(mgr, run_id)
    mgr.request_cancel(run_id)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@link_router.get("/runs/{run_id}/events")
async def stream_run(
    run_id: str,
    mgr: RunManager = Depends(get_run_manager),
    _context=Depends(get_sse_user_context),
):
    _owned_record(mgr, run_id)
    return EventSourceResponse(run_events(mgr, run_id))
