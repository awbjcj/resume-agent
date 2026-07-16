"""Board read-models (filter/sort/paginate over the query DTOs) and mutations.

Read side wraps tracking.queries with the core server-side filters the API
exposes; rich faceting stays client-side for now. Mutation side wraps
tracking.repository, preserving the existing job/application semantics.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Literal, Sequence, cast

from sqlmodel import Session, select

from resume_agent.profile.store import load_facts
from resume_agent.services.pagination import Page, paginate
from resume_agent.tenancy.paths import resolve_tenant_path
from resume_agent.tracking.queries import (
    PipelineRow,
    ShortlistRow,
    TriageRow,
    archived_rows,
    job_detail_row,
    pipeline_rows,
    shortlist_rows,
    triage_rows,
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

DEFAULT_FACTS = "data/profile/facts.json"
BoardName = Literal["shortlist", "triage", "pipeline"]
BulkAction = Literal["archive", "restore", "delete", "approve", "setStatus"]
SelectionScope = Literal["ids", "query"]
Facets = dict[str, dict[str, int]]


@dataclass(frozen=True)
class BoardFilter:
    q: str | None = None
    source: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    remote: tuple[str, ...] = ()
    sponsorship: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ()
    employment_type: tuple[str, ...] = ()
    industry: tuple[str, ...] = ()
    country: tuple[str, ...] = ()
    region: tuple[str, ...] = ()
    city: tuple[str, ...] = ()
    company_size: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    min_fit: int | None = None
    max_fit: int | None = None
    min_salary: int | None = None
    stale_days: int | None = None
    stale_min_days: int | None = None
    sort: str = "fit"
    archived: bool = False


@dataclass(frozen=True)
class BoardListResult:
    page: Page
    facets: Facets


@dataclass(frozen=True)
class BulkResult:
    affected: int
    skipped: int
    reasons: dict[str, int]


@dataclass(frozen=True)
class FacetSpec:
    """One facet: its wire key, the row attribute it reads, and the BoardFilter
    field that selects on it. The single statement of the facet vocabulary —
    _row_value, _passes_filter, and board_facets all derive from this table."""

    key: str  # camelCase wire key (facet payload + filter query param)
    row_attr: str  # attribute on the row DTO
    filter_attr: str  # field name on BoardFilter
    skip_unset_rows: bool = False  # rows without the value pass the filter


FACET_SPECS: tuple[FacetSpec, ...] = (
    FacetSpec("source", "source", "source"),
    FacetSpec("status", "status", "status"),
    FacetSpec("remote", "remote_policy", "remote"),
    FacetSpec("sponsorship", "sponsorship_signal", "sponsorship"),
    FacetSpec("seniority", "seniority", "seniority"),
    FacetSpec("employmentType", "employment_type", "employment_type"),
    FacetSpec("industry", "industry", "industry", skip_unset_rows=True),
    FacetSpec("country", "location_country", "country"),
    FacetSpec("region", "location_region", "region"),
    FacetSpec("city", "location_city", "city"),
    FacetSpec("companySize", "company_size", "company_size"),
)

_FACETS_BY_KEY = {spec.key: spec for spec in FACET_SPECS}


_PUNCT = re.compile(r"[^a-z0-9+#. ]+")
_WS = re.compile(r"\s+")


def _normalize_token(value: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", value.lower())).strip()


def _selected(values: Sequence[str]) -> set[str]:
    return {v for v in values if v}


def _row_value(row: Any, key: str) -> str | None:
    spec = _FACETS_BY_KEY.get(key)
    if spec is None:
        return None
    return getattr(row, spec.row_attr, None)


def _row_text(row: Any) -> str:
    fields = (
        getattr(row, "company", None),
        getattr(row, "title", None),
        getattr(row, "location", None),
        getattr(row, "source", None),
        getattr(row, "status", None),
        getattr(row, "jd_text", None),
    )
    return " ".join(str(v) for v in fields if v).lower()


def _row_skill_tokens(row: Any) -> set[str]:
    return {
        _normalize_token(tag.name) for tag in getattr(row, "skills", []) if tag.name
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _passes_filter(row: Any, f: BoardFilter) -> bool:
    if f.q and f.q.strip().lower() not in _row_text(row):
        return False

    score = getattr(row, "fit_score", None)
    if f.min_fit is not None and score is not None and score < f.min_fit:
        return False
    if f.max_fit is not None and score is not None and score > f.max_fit:
        return False

    if f.min_salary is not None:
        salary = getattr(row, "salary_max", None) or getattr(row, "salary_min", None)
        currency = (getattr(row, "salary_currency", None) or "USD").upper()
        if currency == "USD" and salary is not None and salary < f.min_salary:
            return False

    if f.stale_days is not None:
        posted_at = getattr(row, "posted_at", None)
        if posted_at is None:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(days=f.stale_days)
        if _aware(posted_at) < cutoff:
            return False

    if f.stale_min_days is not None:
        posted_at = getattr(row, "posted_at", None)
        if posted_at is None:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(days=f.stale_min_days)
        if _aware(posted_at) >= cutoff:
            return False

    for spec in FACET_SPECS:
        selected = _selected(getattr(f, spec.filter_attr))
        value = getattr(row, spec.row_attr, None)
        if spec.skip_unset_rows and value is None:
            continue
        if selected and value not in selected:
            return False

    selected_skills = {_normalize_token(v) for v in f.skills if v}
    if selected_skills and not (_row_skill_tokens(row) & selected_skills):
        return False

    return True


def _apply_board_filter(rows: list[Any], f: BoardFilter) -> list[Any]:
    return [row for row in rows if _passes_filter(row, f)]


def _posted_sort_value(row: Any) -> datetime:
    posted_at = getattr(row, "posted_at", None)
    return (
        _aware(posted_at)
        if posted_at is not None
        else datetime.min.replace(tzinfo=timezone.utc)
    )


def _salary_sort_value(row: Any) -> int:
    return getattr(row, "salary_max", None) or getattr(row, "salary_min", None) or 0


def _sort_rows(rows: list[Any], sort: str) -> list[Any]:
    if sort in {"fit", "composite"}:
        return _by_fit_desc(rows)
    if sort == "salary":
        return sorted(rows, key=_salary_sort_value, reverse=True)
    if sort == "recency":
        return sorted(rows, key=_posted_sort_value, reverse=True)
    if sort == "company":
        return sorted(
            rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower())
        )
    if sort == "stage":
        return sorted(
            rows, key=lambda r: (getattr(r, "status", ""), (r.company or "").lower())
        )
    return rows


def _count_values(rows: list[Any], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = _row_value(row, key)
        if value:
            counts[value] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _count_skills(rows: list[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for token in _row_skill_tokens(row):
            if token:
                counts[token] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def board_facets(rows: list[Any]) -> Facets:
    facets: Facets = {}
    for spec in FACET_SPECS:
        counts = _count_values(rows, spec.key)
        if counts:
            facets[spec.key] = counts
    skills = _count_skills(rows)
    if skills:
        facets["skills"] = skills
    return facets


def _by_fit_desc(rows):
    return sorted(
        rows, key=lambda r: (r.fit_score is not None, r.fit_score or -1), reverse=True
    )


def _board_rows(
    session: Session,
    board: BoardName,
    f: BoardFilter,
    *,
    facts_path: str = DEFAULT_FACTS,
) -> list[Any]:
    if board == "shortlist":
        resolved_facts = resolve_tenant_path(facts_path)
        facts = load_facts(resolved_facts) if resolved_facts.exists() else None
        rows = shortlist_rows(session, facts=facts)
    elif board == "pipeline":
        rows = pipeline_rows(session)
    elif board == "triage":
        rows = archived_rows(session) if f.archived else triage_rows(session)
    else:
        raise ValueError(f"Unknown board {board!r}")
    return _sort_rows(_apply_board_filter(rows, f), f.sort)


def list_board(
    session: Session,
    board: BoardName,
    *,
    board_filter: BoardFilter | None = None,
    page: int = 1,
    page_size: int = 50,
    facts_path: str = DEFAULT_FACTS,
) -> BoardListResult:
    f = board_filter or BoardFilter(sort="stage" if board == "pipeline" else "fit")
    rows = _board_rows(session, board, f, facts_path=facts_path)
    return BoardListResult(
        page=paginate(rows, page=page, page_size=page_size),
        facets=board_facets(rows),
    )


def list_shortlist(
    session: Session,
    *,
    board_filter: BoardFilter | None = None,
    min_fit: int | None = None,
    sort: str = "fit",
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
    sort: str = "stage",
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
    ).page


def list_triage(
    session: Session,
    *,
    archived: bool = False,
    status: str | None = None,
    min_fit: int | None = None,
    sort: str = "fit",
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
        return [row.job_id for row in _board_rows(session, board, board_filter)]
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
