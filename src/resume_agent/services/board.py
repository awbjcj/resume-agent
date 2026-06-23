"""Board read-models (filter/sort/paginate over the query DTOs) and mutations.

Read side wraps tracking.queries with the core server-side filters the API
exposes; rich faceting stays client-side for now. Mutation side wraps
tracking.repository, preserving the exact semantics the CLI/Streamlit use today.
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from resume_agent.profile.store import load_facts
from resume_agent.services.pagination import Page, paginate
from resume_agent.tracking.queries import (
    PipelineRow,
    ShortlistRow,
    TriageRow,
    archived_rows,
    job_facets,
    pipeline_rows,
    shortlist_rows,
    triage_rows,
)
from resume_agent.tracking.repository import (
    application_for_job,
    archive_job,
    delete_job,
    get_job,
    restore_job,
    save_application,
    save_job,
    update_application_status,
)
from resume_agent.tracking.tables import Application, Job

DEFAULT_FACTS = "data/profile/facts.json"


def _by_fit_desc(rows):
    return sorted(rows, key=lambda r: (r.fit_score is not None, r.fit_score or -1), reverse=True)


def list_shortlist(
    session: Session, *, min_fit: int | None = None, sort: str = "fit",
    page: int = 1, page_size: int = 50, facts_path: str = DEFAULT_FACTS,
) -> Page[ShortlistRow]:
    facts = load_facts(facts_path) if Path(facts_path).exists() else None
    rows = shortlist_rows(session, facts=facts)
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "salary":
        rows = sorted(rows, key=lambda r: (r.salary_max or r.salary_min or 0), reverse=True)
    return paginate(rows, page=page, page_size=page_size)


def job_detail_facets(
    session: Session, job_id: int, *, facts_path: str = DEFAULT_FACTS
) -> ShortlistRow | None:
    """Skill + meta facets for the single-job detail view (modal rail).

    Loads the profile facts the same way the board list does so ``covered``
    (the profile gap signal) is consistent between the card and the modal.
    """
    facts = load_facts(facts_path) if Path(facts_path).exists() else None
    return job_facets(session, job_id, facts=facts)


def list_pipeline(
    session: Session, *, status: str | None = None, min_fit: int | None = None,
    q: str | None = None, sort: str = "stage", page: int = 1, page_size: int = 50,
) -> Page[PipelineRow]:
    # sort defaults to "stage" = the native pipeline_rows order (status, company,
    # title); only "fit"/"company" re-sort. An unknown sort falls through to native.
    rows = pipeline_rows(session)
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in f"{r.company or ''} {r.title or ''}".lower()]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)


def list_triage(
    session: Session, *, archived: bool = False, status: str | None = None,
    min_fit: int | None = None, sort: str = "fit", page: int = 1, page_size: int = 50,
) -> Page[TriageRow]:
    rows = archived_rows(session) if archived else triage_rows(session)
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if min_fit is not None:
        rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
    if sort == "fit":
        rows = _by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)


# --- mutations (preserve current CLI/Streamlit semantics) -----------------

def set_stage(session: Session, job_id: int, status: str) -> Job | None:
    job = get_job(session, job_id)
    if job is None:
        return None
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
        return save_application(session, Application(job_id=job_id, status=status, notes=notes))
    updated = update_application_status(session, existing.id, status, notes)
    assert updated is not None  # existing.id was just confirmed present
    return updated
