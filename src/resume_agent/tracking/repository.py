from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar, cast

from sqlalchemy import func
from sqlmodel import Session, col, select

from resume_agent.tracking.dedup import (
    compute_content_fingerprint,
    locations_compatible,
)
from resume_agent.tracking.prune import (
    PruneReport,
    PruneRow,
    expire_candidates,
    prune_candidates,
    prune_reason_counts,
    prune_skipped,
)
from resume_agent.tracking.prune_config import PruneConfig
from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    CoverLetter,
    EmailDraft,
    Job,
    JobStatus,
    Notification,
    ResumeVersion,
    utcnow,
)


def _stamp_submitted_at(application: Application) -> None:
    if application.status == ApplicationStatus.submitted.value and application.submitted_at is None:
        application.submitted_at = utcnow()


def save_job(session: Session, job: Job) -> Job:
    """Insert or update a job (SQLModel ``add`` handles both)."""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def jobs_by_status(session: Session, status: str) -> list[Job]:
    archived_col = cast(Any, Job.archived_at)
    return list(
        session.exec(
            select(Job).where(Job.status == status, archived_col.is_(None))
        ).all()
    )


def find_existing(
    session: Session,
    url: str | None,
    jd_text: str,
    dedup_key: str | None = None,
    content_fingerprint: str | None = None,
    location: str | None = None,
) -> Job | None:
    """Match by URL, JD, key, or keyless fingerprint, with a location guard."""
    archived_col = cast(Any, Job.archived_at)

    def first_compatible(rows: Iterable[Job]) -> Job | None:
        return next(
            (row for row in rows if locations_compatible(location, row.location)),
            None,
        )

    if url:
        by_url = session.exec(
            select(Job).where(Job.url == url, archived_col.is_(None))
        ).first()
        if by_url is not None:
            return by_url
    if jd_text:
        # Equal jd_text implies equal content_fingerprint (a pure function of
        # jd_text), so the indexed fingerprint column narrows the scan without
        # changing which row matches; jd_text equality stays the real predicate.
        fingerprint = compute_content_fingerprint(jd_text)
        conditions = [Job.jd_text == jd_text, archived_col.is_(None)]
        if fingerprint:
            conditions.insert(0, Job.content_fingerprint == fingerprint)
        by_jd = first_compatible(
            session.exec(select(Job).where(*conditions)).all()
        )
        if by_jd is not None:
            return by_jd
    if dedup_key:
        by_key = first_compatible(
            session.exec(
                select(Job).where(
                    Job.dedup_key == dedup_key,
                    archived_col.is_(None),
                )
            ).all()
        )
        if by_key is not None:
            return by_key
    if dedup_key is None and content_fingerprint:
        return first_compatible(
            session.exec(
                select(Job).where(
                    Job.content_fingerprint == content_fingerprint,
                    archived_col.is_(None),
                )
            ).all()
        )
    return None


def company_rename_collides(
    session: Session,
    *,
    existing: Job,
    dedup_key: str | None,
) -> bool:
    """Return whether a rename would take another live row's identity."""
    return company_rename_collision(
        session, existing=existing, dedup_key=dedup_key
    ) is not None


def company_rename_collision(
    session: Session,
    *,
    existing: Job,
    dedup_key: str | None,
) -> Job | None:
    """Find the live compatible row holding a proposed company identity."""
    if dedup_key is None:
        return None
    candidates = session.exec(
        select(Job).where(
            col(Job.dedup_key) == dedup_key,
            col(Job.id) != existing.id,
            col(Job.archived_at).is_(None),
        )
    ).all()
    return next(
        (
            candidate
            for candidate in candidates
            if locations_compatible(candidate.location, existing.location)
        ),
        None,
    )


def status_counts(session: Session) -> dict[str, int]:
    archived_col = cast(Any, Job.archived_at)
    rows = session.exec(
        select(Job.status, func.count())
        .where(archived_col.is_(None))
        .group_by(Job.status)
    ).all()
    return {status: count for status, count in rows}


def get_job(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def save_resume_version(session: Session, version: ResumeVersion) -> ResumeVersion:
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def resume_versions_for_job(session: Session, job_id: int) -> list[ResumeVersion]:
    return list(session.exec(select(ResumeVersion).where(ResumeVersion.job_id == job_id)).all())


def cover_letters_for_job(session: Session, job_id: int) -> list[CoverLetter]:
    return list(session.exec(select(CoverLetter).where(CoverLetter.job_id == job_id)).all())


def get_resume_version(session: Session, version_id: int) -> ResumeVersion | None:
    return session.get(ResumeVersion, version_id)


def save_application(session: Session, application: Application) -> Application:
    _stamp_submitted_at(application)
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def get_application(session: Session, application_id: int) -> Application | None:
    return session.get(Application, application_id)


def application_for_job(session: Session, job_id: int) -> Application | None:
    return session.exec(select(Application).where(Application.job_id == job_id)).first()


def applications_by_status(session: Session, status: str) -> list[Application]:
    return list(session.exec(select(Application).where(Application.status == status)).all())


def update_application_status(
    session: Session, application_id: int, status: str, notes: str | None = None
) -> Application | None:
    application = session.get(Application, application_id)
    if application is None:
        return None
    application.status = status
    _stamp_submitted_at(application)
    if notes is not None:
        application.notes = notes
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def latest_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    round_col = cast(Any, ResumeVersion.round)
    id_col = cast(Any, ResumeVersion.id)
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(round_col.desc(), id_col.desc())
    ).first()


def latest_rendered_resume_version(session: Session, job_id: int) -> ResumeVersion | None:
    pdf_path_col = cast(Any, ResumeVersion.pdf_path)
    round_col = cast(Any, ResumeVersion.round)
    id_col = cast(Any, ResumeVersion.id)
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id, pdf_path_col.is_not(None))
        .order_by(round_col.desc(), id_col.desc())
    ).first()


@dataclass(frozen=True)
class BestResume:
    """Read-side result for the default surfaced resume round."""

    version: ResumeVersion | None
    no_clean_round: bool
    regressed: bool


def _latest_key(version: ResumeVersion) -> tuple[int, int]:
    return version.round, version.id or 0


def _score_key(version: ResumeVersion) -> tuple[int, int, int]:
    score = -1 if version.review_score is None else version.review_score
    return score, version.round, version.id or 0


_Surfaceable = TypeVar("_Surfaceable")


def select_surfaced(
    items: list[_Surfaceable],
    *,
    is_clean: Callable[[_Surfaceable], bool],
    score_key: Callable[[_Surfaceable], Any],
    latest_key: Callable[[_Surfaceable], Any],
) -> tuple[_Surfaceable | None, bool, bool]:
    """Pick the highest-scoring clean item, falling back to the latest when none
    is clean. Returns ``(item, no_clean_round, regressed)``.

    The single home for the "default surfaced round" rule, shared by the product
    read-side (:func:`pick_best`) and the eval harness so the two cannot drift.
    """
    if not items:
        return None, False, False
    latest = max(items, key=latest_key)
    clean = [item for item in items if is_clean(item)]
    if not clean:
        return latest, True, False
    best = max(clean, key=score_key)
    return best, False, best is not latest


def pick_best(versions: list[ResumeVersion]) -> BestResume:
    """Pick the highest-scoring clean round, falling back visibly when none is clean."""
    best, no_clean_round, regressed = select_surfaced(
        versions,
        is_clean=lambda version: version.fact_check_passed,
        score_key=_score_key,
        latest_key=_latest_key,
    )
    return BestResume(
        version=best, no_clean_round=no_clean_round, regressed=regressed
    )


def best_resume_version(session: Session, job_id: int) -> BestResume:
    """Load and select the default surfaced resume for a job."""
    return pick_best(resume_versions_for_job(session, job_id))


def save_cover_letter(session: Session, cover_letter: CoverLetter) -> CoverLetter:
    session.add(cover_letter)
    session.commit()
    session.refresh(cover_letter)
    return cover_letter


def get_cover_letter(session: Session, cover_letter_id: int) -> CoverLetter | None:
    return session.get(CoverLetter, cover_letter_id)


def save_notification(session: Session, notification: Notification) -> Notification:
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification


def get_notification(session: Session, notification_id: int) -> Notification | None:
    return session.get(Notification, notification_id)


def notification_by_key(
    session: Session, application_id: int, message_id: str
) -> Notification | None:
    return session.exec(
        select(Notification).where(
            Notification.application_id == application_id,
            Notification.message_id == message_id,
        )
    ).first()


def pending_notifications(session: Session) -> list[Notification]:
    return list(session.exec(select(Notification).where(Notification.state == "pending")).all())


def save_email_draft(session: Session, draft: EmailDraft) -> EmailDraft:
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def get_email_draft(session: Session, draft_id: int) -> EmailDraft | None:
    return session.get(EmailDraft, draft_id)


def email_drafts_for_job(session: Session, job_id: int) -> list[EmailDraft]:
    id_col = cast(Any, EmailDraft.id)
    return list(
        session.exec(
            select(EmailDraft)
            .where(EmailDraft.job_id == job_id)
            .order_by(id_col.desc())
        ).all()
    )


_PROGRESS_STATUSES = {
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
}


def archive_job(session: Session, job_id: int) -> Job | None:
    """Soft-archive a job (reversible). Status is left untouched."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def restore_job(session: Session, job_id: int) -> Job | None:
    """Un-archive a job, restoring it to its exact prior stage."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    job.archived_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def delete_job_row(session: Session, job: Job, *, commit: bool = True) -> None:
    """Cascade-delete a job's children, then the job itself.

    Unguarded: callers must have already applied the has_progress gate.
    """
    for model in (CoverLetter, Application, ResumeVersion, EmailDraft):
        for child in session.exec(select(model).where(model.job_id == job.id)).all():
            session.delete(child)
    session.delete(job)
    if commit:
        session.commit()


def delete_job(session: Session, job_id: int) -> bool:
    """Hard-delete a zero-progress job and its children in one transaction.

    Returns False (and changes nothing) if the job has user progress or is
    already gone. The progress check is the single irreversible-path guard.
    """
    if has_progress(session, job_id):
        return False
    job = session.get(Job, job_id)
    if job is None:
        return False
    delete_job_row(session, job)
    return True


def has_progress(session: Session, job_id: int) -> bool:
    """True if a job has user investment that must never be destroyed."""
    job = session.get(Job, job_id)
    if job is None:
        return False
    if job.status in _PROGRESS_STATUSES:
        return True
    for model in (Application, ResumeVersion, CoverLetter):
        if session.exec(select(model).where(model.job_id == job_id)).first() is not None:
            return True
    return False


def progressed_job_ids(session: Session) -> set[int]:
    """Job ids owning any child row, resolved in one query per child table.

    Mirrors has_progress()'s child-existence check, but batched so a whole-table
    prune scan costs three queries instead of ~4 per job (an N+1 over every job).
    """
    progressed: set[int] = set()
    for model in (Application, ResumeVersion, CoverLetter):
        progressed.update(session.exec(select(cast(Any, model.job_id))).all())
    return progressed


def versions_by_job(session: Session) -> dict[int, list[ResumeVersion]]:
    """Every resume version grouped by job_id — one query for whole-board reads."""
    grouped: dict[int, list[ResumeVersion]] = {}
    for version in session.exec(select(ResumeVersion)).all():
        grouped.setdefault(version.job_id, []).append(version)
    return grouped


def applications_by_job(session: Session) -> dict[int, Application]:
    """Lowest-id application per job — the batched mirror of application_for_job()."""
    id_col = cast(Any, Application.id)
    grouped: dict[int, Application] = {}
    for application in session.exec(select(Application).order_by(id_col)).all():
        grouped.setdefault(application.job_id, application)
    return grouped


def job_has_progress(job: Job, progressed: set[int]) -> bool:
    """Batched counterpart of has_progress(): same rule, zero per-job queries."""
    return job.status in _PROGRESS_STATUSES or (job.id is not None and job.id in progressed)


def _prune_rows(session: Session) -> list[PruneRow]:
    progressed = progressed_job_ids(session)
    return [
        PruneRow(
            job_id=job.id,
            status=job.status,
            fit_score=job.fit_score,
            posted_at=job.posted_at,
            created_at=job.created_at,
            archived_at=job.archived_at,
            has_progress=job.status in _PROGRESS_STATUSES or job.id in progressed,
        )
        for job in session.exec(select(Job)).all()
        if job.id is not None
    ]


def _prune_plan(session: Session, config: PruneConfig, now: datetime):
    rows = _prune_rows(session)
    return (
        prune_candidates(rows, config, now),
        expire_candidates(rows, config, now),
        prune_skipped(rows, config, now),
    )


def _prune_report(
    to_archive: list[PruneRow],
    to_expire: list[PruneRow],
    skipped: list[PruneRow],
    config: PruneConfig,
    now: datetime,
) -> PruneReport:
    reasons = prune_reason_counts(to_archive, config, now)
    return PruneReport(
        archived=len(to_archive),
        expired=len(to_expire),
        skipped=len(skipped),
        rejected=reasons["rejected"],
        low_fit=reasons["low_fit"],
        stale=reasons["stale"],
    )


def prune_preview(
    session: Session, config: PruneConfig, now: datetime | None = None
) -> PruneReport:
    """Count what a prune would do, without writing anything."""
    now = now or utcnow()
    to_archive, to_expire, skipped = _prune_plan(session, config, now)
    return _prune_report(to_archive, to_expire, skipped, config, now)


def prune_run(
    session: Session, config: PruneConfig, now: datetime | None = None
) -> PruneReport:
    """Archive matching junk and expire old archived rows. Returns the tally."""
    now = now or utcnow()
    to_archive, to_expire, skipped = _prune_plan(session, config, now)
    for row in to_archive:
        job = session.get(Job, row.job_id)
        if job is not None:
            job.archived_at = now
            session.add(job)
    session.commit()
    progressed = progressed_job_ids(session)
    for row in to_expire:
        job = session.get(Job, row.job_id)
        if job is None or job_has_progress(job, progressed):
            continue
        delete_job_row(session, job, commit=False)
    session.commit()
    return _prune_report(to_archive, to_expire, skipped, config, now)
