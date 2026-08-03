"""Board read orchestration and mutations.

Read side asks tracking.board_query for one filtered, sorted, paged set of jobs
(plus its leave-one-out facet counts) and then projects only those jobs through
tracking.queries. Mutation side wraps tracking.repository, preserving the
existing job/application semantics.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence, cast

from sqlmodel import Session, select

from resume_agent.profile.store import load_facts
from resume_agent.services.pagination import Page, page_from_slice
from resume_agent.tenancy.paths import FACTS_PATH as DEFAULT_FACTS, resolve_tenant_path
from resume_agent.tracking import board_query
from resume_agent.tracking.board_query import (
    BoardFilter,
    BoardName,
    FACET_SPECS as FACET_SPECS,
    Facets,
    Preset as Preset,
    SortKey as SortKey,
)
from resume_agent.tracking.queries import (
    PipelineRow,
    ShortlistRow,
    TriageRow,
    job_detail_row,
    project_pipeline_jobs,
    project_shortlist_jobs,
    project_triage_jobs,
)
from resume_agent.tracking.repository import (
    application_for_job,
    archive_job,
    delete_job,
    delete_job_row,
    get_cover_letter,
    get_job,
    get_resume_version,
    job_has_progress,
    progressed_job_ids,
    restore_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_agent.tracking.tables import Application, Job, JobStatus, utcnow

_DISCOVERY_STAGE_STATUSES = {
    JobStatus.filtered.value,
    JobStatus.rejected.value,
}
BulkAction = Literal["archive", "restore", "delete", "approve", "setStatus"]
SelectionScope = Literal["ids", "query"]


@dataclass(frozen=True)
class BoardListResult:
    page: Page
    facets: Facets | None


@dataclass(frozen=True)
class BulkResult:
    affected: int
    skipped: int
    reasons: dict[str, int]


def list_board(
    session: Session,
    board: BoardName,
    *,
    board_filter: BoardFilter | None = None,
    page: int = 1,
    page_size: int = 50,
    facts_path: str = DEFAULT_FACTS,
    with_facets: bool = True,
) -> BoardListResult:
    """One board page, plus leave-one-out facet counts on page 1.

    Facet counts cost their own aggregation queries, so ``with_facets=False``
    skips them for callers that only need the page (``facets`` is then ``None``,
    exactly as it already is on pages after the first).
    """
    f = board_filter or BoardFilter(sort="recency" if board == "pipeline" else "fit")
    query_time = datetime.now(timezone.utc)
    # Resolving a companySize/skills filter costs a table scan, so the page read
    # and the facet counts below share one derivation instead of each doing it.
    derived = board_query.derive_filter_values(session, f)
    jobs, total = board_query.board_page(
        session,
        board,
        f,
        page=page,
        page_size=page_size,
        now=query_time,
        derived=derived,
    )
    if board == "shortlist":
        resolved_facts = resolve_tenant_path(facts_path)
        facts = load_facts(resolved_facts) if resolved_facts.exists() else None
        rows = project_shortlist_jobs(session, jobs, facts=facts)
    elif board == "pipeline":
        rows = project_pipeline_jobs(session, jobs)
    else:
        rows = project_triage_jobs(session, jobs)
    return BoardListResult(
        page=page_from_slice(
            rows,
            total=total,
            page=page,
            page_size=page_size,
        ),
        facets=(
            board_query.board_facet_counts(
                session,
                board,
                f,
                now=query_time,
                derived=derived,
            )
            if with_facets and page == 1
            else None
        ),
    )


def list_shortlist(
    session: Session,
    *,
    board_filter: BoardFilter | None = None,
    min_fit: int | None = None,
    sort: SortKey = "fit",
    page: int = 1,
    page_size: int = 50,
    facts_path: str = DEFAULT_FACTS,
) -> Page[ShortlistRow]:
    f = board_filter or BoardFilter(min_fit=min_fit, sort=sort)
    return list_board(
        session,
        "shortlist",
        board_filter=f,
        page=page,
        page_size=page_size,
        facts_path=facts_path,
        with_facets=False,
    ).page


def get_job_detail(session: Session, job_id: int, *, facts_path: str = DEFAULT_FACTS):
    """Full detail read-model for one job."""
    resolved_facts = resolve_tenant_path(facts_path)
    facts = load_facts(resolved_facts) if resolved_facts.exists() else None
    return job_detail_row(session, job_id, facts=facts)


def list_pipeline(
    session: Session,
    *,
    status: str | None = None,
    min_fit: int | None = None,
    q: str | None = None,
    sort: SortKey = "recency",
    page: int = 1,
    page_size: int = 50,
    board_filter: BoardFilter | None = None,
) -> Page[PipelineRow]:
    f = board_filter or BoardFilter(
        status=(status,) if status else (),
        min_fit=min_fit,
        q=q,
        sort=sort,
    )
    return list_board(
        session,
        "pipeline",
        board_filter=f,
        page=page,
        page_size=page_size,
        with_facets=False,
    ).page


def list_triage(
    session: Session,
    *,
    archived: bool = False,
    status: str | None = None,
    min_fit: int | None = None,
    sort: SortKey = "fit",
    page: int = 1,
    page_size: int = 50,
    board_filter: BoardFilter | None = None,
) -> Page[TriageRow]:
    f = board_filter or BoardFilter(
        status=(status,) if status else (),
        min_fit=min_fit,
        sort=sort,
        archived=archived,
    )
    return list_board(
        session,
        "triage",
        board_filter=f,
        page=page,
        page_size=page_size,
        with_facets=False,
    ).page


def _target_ids(
    session: Session,
    *,
    board: BoardName,
    scope: SelectionScope,
    board_filter: BoardFilter,
    ids: Sequence[int],
) -> list[int]:
    if scope == "ids":
        return list(dict.fromkeys(ids))
    if scope == "query":
        statement = board_query.board_statement(session, board, board_filter)
        id_statement = cast(Any, statement.with_only_columns(cast(Any, Job.id)))
        return list(session.exec(id_statement).all())
    raise ValueError(f"Unknown bulk scope {scope!r}")


def bulk_apply(
    session: Session,
    *,
    board: BoardName,
    action: BulkAction,
    scope: SelectionScope,
    board_filter: BoardFilter,
    ids: Sequence[int] = (),
    status: str | None = None,
    dry_run: bool = True,
) -> BulkResult:
    target_ids = _target_ids(
        session,
        board=board,
        scope=scope,
        board_filter=board_filter,
        ids=ids,
    )
    id_col = cast(Any, Job.id)
    jobs = {
        job.id: job
        for job in session.exec(select(Job).where(id_col.in_(target_ids))).all()
    }
    affected = 0
    skipped = 0
    reasons: Counter[str] = Counter()
    progress_guarded = action in {"delete", "approve", "setStatus"}
    progressed = progressed_job_ids(session) if progress_guarded else set()

    for job_id in target_ids:
        job = jobs.get(job_id)
        if job is None:
            skipped += 1
            reasons["missing"] += 1
            continue
        if progress_guarded and job_has_progress(job, progressed):
            skipped += 1
            reasons["hasProgress"] += 1
            continue

        if dry_run:
            affected += 1
            continue

        if action == "archive":
            job.archived_at = utcnow()
            session.add(job)
        elif action == "restore":
            job.archived_at = None
            session.add(job)
        elif action == "delete":
            delete_job_row(session, job, commit=False)
        elif action == "approve":
            job.status = JobStatus.approved.value
            session.add(job)
        elif action == "setStatus":
            if status is None:
                raise ValueError("status is required for setStatus")
            if (
                job.status == JobStatus.rejected.value
                and status not in _DISCOVERY_STAGE_STATUSES
            ):
                job.gate_override = True
                # The prior rejection no longer applies once the job is
                # promoted; a stale reason would otherwise linger and be matched
                # by the triage reject-reason filter. Mirrors reprocess().
                job.reject_reason = None
                job.reject_category = None
            elif status in _DISCOVERY_STAGE_STATUSES:
                job.gate_override = False
            job.status = status
            session.add(job)
        else:
            raise ValueError(f"Unknown bulk action {action!r}")
        affected += 1

    if not dry_run:
        session.commit()
    return BulkResult(affected=affected, skipped=skipped, reasons=dict(reasons))


# --- mutations (preserve current job/application semantics) ---------------


def set_stage(session: Session, job_id: int, status: str) -> Job | None:
    job = get_job(session, job_id)
    if job is None:
        return None
    if (
        job.status == JobStatus.rejected.value
        and status not in _DISCOVERY_STAGE_STATUSES
    ):
        job.gate_override = True
        # The prior rejection no longer applies once the job is promoted; a
        # stale reason would otherwise linger and be matched by the triage
        # reject-reason filter. Mirrors reprocess().
        job.reject_reason = None
        job.reject_category = None
    elif status in _DISCOVERY_STAGE_STATUSES:
        job.gate_override = False
    job.status = status
    return save_job(session, job)


def set_archived(session: Session, job_id: int, archived: bool) -> Job | None:
    return archive_job(session, job_id) if archived else restore_job(session, job_id)


def delete(session: Session, job_id: int) -> bool:
    return delete_job(session, job_id)


def upsert_application(
    session: Session, job_id: int, *, status: str, notes: str | None = None
) -> Application:
    existing = application_for_job(session, job_id)
    if existing is None or existing.id is None:
        return save_application(
            session, Application(job_id=job_id, status=status, notes=notes)
        )
    updated = update_application_status(session, existing.id, status, notes)
    assert updated is not None  # existing.id was just confirmed present
    return updated


def select_resume_version(
    session: Session, job_id: int, version_id: int
) -> Application | None:
    if get_job(session, job_id) is None:
        return None
    version = get_resume_version(session, version_id)
    if version is None or version.job_id != job_id:
        return None
    application = application_for_job(session, job_id) or Application(job_id=job_id)
    application.resume_version_id = version_id
    return save_application(session, application)


def select_cover_letter(
    session: Session, job_id: int, cover_letter_id: int
) -> Application | None:
    if get_job(session, job_id) is None:
        return None
    cover_letter = get_cover_letter(session, cover_letter_id)
    if cover_letter is None or cover_letter.job_id != job_id:
        return None
    application = application_for_job(session, job_id) or Application(job_id=job_id)
    application.cover_letter_id = cover_letter_id
    return save_application(session, application)
