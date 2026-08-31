from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import defer
from sqlmodel import Session, col, select

from resume_tailor_harness.discovery.connectors.text import clean_job_description_text
from resume_tailor_harness.h1b.cache import load_company_evidence
from resume_tailor_harness.h1b.models import H1BSponsorshipEvidence
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.taxonomy.company_size import snap as snap_size
from resume_tailor_harness.taxonomy.industries import normalize_company
from resume_tailor_harness.taxonomy.location import location_instances_from_criteria
from resume_tailor_harness.taxonomy.skills import canonical_skill, load_aliases, split_skills
from resume_tailor_harness.tenancy.paths import SKILL_ALIASES_PATH
from resume_tailor_harness.tracking.match_gap import profile_skill_tokens
from resume_tailor_harness.tracking.repository import (
    application_for_job,
    applications_by_job,
    cover_letters_for_job,
    has_progress,
    job_has_progress,
    pick_best,
    progressed_job_ids,
    resume_versions_for_job,
    versions_by_job,
)
from resume_tailor_harness.tracking.tables import (
    Application,
    ApplicationEvent,
    CoverLetter,
    Job,
    JobStatus,
    ResumeVersion,
    utcnow,
)


def _require_job_id(job: Job) -> int:
    if job.id is None:
        raise ValueError("Encountered a job row without a persisted id")
    return job.id


@dataclass
class SkillTag:
    name: str
    covered: bool
    required: bool


@dataclass
class ShortlistRow:
    job_id: int
    company: str | None
    title: str | None
    source: str
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]
    locations: list[dict[str, Any]] = field(default_factory=list)
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    is_us: bool = False
    url: str | None = None
    h1b_sponsorship_status: str | None = None


@dataclass(kw_only=True)
class JobDetailRow(ShortlistRow):
    """Flat read-model for one job's detail view.

    Inherits the facet half from ShortlistRow (declared once, projected by
    _shortlist_row) and adds the detail-only columns, named to match the
    JobDetail schema: id, not job_id.
    """

    id: int
    jd_text: str
    status: str
    criteria_json: dict[str, Any] | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: Application | None
    resume_versions: list[ResumeVersion]
    cover_letters: list[CoverLetter]
    best_resume_version_id: int | None = None
    needs_attention: bool = False
    regressed: bool = False
    reject_reason: str | None = None
    reject_category: str | None = None


@dataclass
class TriageRow:
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    source: str
    status: str
    fit_score: int | None
    posted_at: datetime | None
    archived_at: datetime | None
    has_progress: bool
    reject_reason: str | None = None
    reject_category: str | None = None
    url: str | None = None
    h1b_sponsorship_status: str | None = None
    locations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PipelineRow:
    job_id: int
    company: str | None
    title: str | None
    source: str
    location: str | None
    status: str
    fit_score: int | None
    jd_preview: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    sponsorship_signal: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]
    locations: list[dict[str, Any]]
    location_country: str | None
    location_region: str | None
    location_city: str | None
    reject_reason: str | None
    reject_category: str | None
    has_progress: bool = False
    needs_attention: bool = False
    regressed: bool = False
    url: str | None = None
    h1b_sponsorship_status: str | None = None


def _h1b_sponsorship_status(
    job: Job, evidence_by_company: Mapping[str, H1BSponsorshipEvidence]
) -> str | None:
    """Return the company's cached H-1B status, or None when uncached."""
    key = normalize_company(job.company)
    if not key:
        return None
    evidence = evidence_by_company.get(key)
    return evidence.status if evidence is not None else None


def _company_evidence(
    session: Session, jobs: Sequence[Job]
) -> Mapping[str, H1BSponsorshipEvidence]:
    return load_company_evidence(session, [job.company for job in jobs])


def _skill_tags(
    criteria: dict, tokens: set[str], aliases: dict[str, str]
) -> list[SkillTag]:
    # tech_stack (techs the post names) is also surfaced as non-required tags so
    # the skill cloud and "Skills (any match)" filter can match on it. Compound
    # entries are split into atomic skills, then deduped by canonical token (the
    # canonical token becomes the display name); must_have > nice_to_have > tech_stack.
    profile_canonical = {canonical_skill(t, aliases) for t in tokens}
    tags: list[SkillTag] = []
    seen: set[str] = set()
    for key, required in (
        ("must_have_skills", True),
        ("nice_to_have_skills", False),
        ("tech_stack", False),
    ):
        raw_items = [str(s) for s in (criteria.get(key) or [])]
        for atomic in split_skills(raw_items):
            canonical = canonical_skill(atomic, aliases)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            tags.append(
                SkillTag(
                    name=canonical,
                    covered=canonical in profile_canonical,
                    required=required,
                )
            )
    return tags


def _location_payload(criteria: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        location.as_dict() for location in location_instances_from_criteria(criteria)
    ]


def _shortlist_row(
    job: Job,
    tokens: set[str],
    aliases: dict[str, str],
    evidence_by_company: Mapping[str, H1BSponsorshipEvidence],
) -> ShortlistRow:
    """Project one ``Job`` into the full skill + meta facet row.

    Shared by the board list (``shortlist_rows``) and the single-job detail
    facets (``job_facets``) so the wire format stays identical across the card
    preview and the detail modal.
    """
    job_id = _require_job_id(job)
    criteria = job.criteria_json or {}
    salary = criteria.get("salary_range") or {}
    locations = _location_payload(criteria)
    loc = locations[0] if locations else {}
    return ShortlistRow(
        job_id=job_id,
        company=job.company,
        title=job.title,
        source=job.source,
        location=job.location,
        fit_score=job.fit_score,
        fit_rationale=job.fit_rationale,
        sponsorship_signal=criteria.get("sponsorship_signal"),
        salary_min=salary.get("minimum"),
        salary_max=salary.get("maximum"),
        salary_currency=salary.get("currency"),
        remote_policy=criteria.get("remote_policy"),
        seniority=criteria.get("seniority"),
        employment_type=criteria.get("employment_type"),
        industry=criteria.get("industry"),
        company_size=snap_size(criteria.get("company_size")),
        posted_at=job.posted_at,
        skills=_skill_tags(criteria, tokens, aliases),
        locations=locations,
        location_country=loc.get("country"),
        location_region=loc.get("region"),
        location_city=loc.get("city"),
        is_us=bool(loc.get("is_us")),
        url=job.url,
        h1b_sponsorship_status=_h1b_sponsorship_status(job, evidence_by_company),
    )


def shortlist_rows(
    session: Session,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> list[ShortlistRow]:
    fit_score_col = cast(Any, Job.fit_score)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .options(defer(cast(Any, Job.jd_text)))
        .where(Job.status == JobStatus.shortlisted.value, archived_col.is_(None))
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    return project_shortlist_jobs(session, jobs, facts=facts, aliases_path=aliases_path)


def project_shortlist_jobs(
    session: Session,
    jobs: Sequence[Job],
    *,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> list[ShortlistRow]:
    """Project an already-selected job page into shortlist rows."""
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    evidence_by_company = _company_evidence(session, jobs)
    return [_shortlist_row(job, tokens, aliases, evidence_by_company) for job in jobs]


def job_facets(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> ShortlistRow | None:
    """Build the skill + meta facets for a single job (detail modal).

    Returns ``None`` when the job does not exist. Reuses the same projection as
    the board list so ``covered`` (the profile gap signal) is computed once,
    server-side, against ``facts``.
    """
    job = session.get(Job, job_id)
    if job is None:
        return None
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    evidence_by_company = _company_evidence(session, [job])
    return _shortlist_row(job, tokens, aliases, evidence_by_company)


def job_detail_row(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> JobDetailRow | None:
    """Assemble the full detail read-model for one job."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    facets = _shortlist_row(job, tokens, aliases, {})
    jid = _require_job_id(job)
    versions = resume_versions_for_job(session, jid)
    best = pick_best(versions)
    return JobDetailRow(
        **vars(facets),
        id=jid,
        jd_text=clean_job_description_text(job.jd_text),
        status=job.status,
        criteria_json=(
            {
                key: value
                for key, value in job.criteria_json.items()
                if key != "_industry_candidate"
            }
            if job.criteria_json is not None
            else None
        ),
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, jid),
        application=application_for_job(session, jid),
        resume_versions=versions,
        cover_letters=cover_letters_for_job(session, jid),
        best_resume_version_id=best.version.id if best.version else None,
        needs_attention=best.no_clean_round,
        regressed=best.regressed,
        reject_reason=job.reject_reason,
        reject_category=job.reject_category,
    )


def pipeline_rows(session: Session) -> list[PipelineRow]:
    status_col = cast(Any, Job.status)
    company_col = cast(Any, Job.company)
    title_col = cast(Any, Job.title)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(archived_col.is_(None))
        .order_by(status_col, company_col, title_col)
    ).all()
    return project_pipeline_jobs(session, jobs, aliases_path=SKILL_ALIASES_PATH)


def project_pipeline_jobs(
    session: Session,
    jobs: Sequence[Job],
    *,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> list[PipelineRow]:
    """Project an already-selected job page with page-scoped child lookups."""
    job_ids = [_require_job_id(job) for job in jobs]
    versions = versions_by_job(session, job_ids)
    applications = applications_by_job(session, job_ids)
    progressed = progressed_job_ids(session, job_ids)
    aliases = load_aliases(aliases_path)
    evidence_by_company = _company_evidence(session, jobs)
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        locations = _location_payload(criteria)
        location = locations[0] if locations else {}
        best = pick_best(versions.get(job_id, []))
        version = best.version
        application = applications.get(job_id)
        rows.append(
            PipelineRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                source=job.source,
                location=job.location,
                status=job.status,
                fit_score=job.fit_score,
                jd_preview=clean_job_description_text(job.jd_text)[:400],
                # None means "never tailored" (no version); [] means a version
                # exists but reviewers raised nothing. The board reads them apart.
                critique_json=(version.critique_json or []) if version else None,
                # The surfaced version's own PDF, not any job's latest-rendered
                # round — otherwise a clean older round can pair with a PDF
                # from an unrelated (regressed) later round.
                pdf_path=version.pdf_path if version else None,
                application_status=application.status if application else None,
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                salary_currency=salary.get("currency"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                sponsorship_signal=criteria.get("sponsorship_signal"),
                employment_type=criteria.get("employment_type"),
                industry=criteria.get("industry"),
                company_size=snap_size(criteria.get("company_size")),
                posted_at=job.posted_at,
                skills=_skill_tags(criteria, set(), aliases),
                locations=locations,
                location_country=location.get("country"),
                location_region=location.get("region"),
                location_city=location.get("city"),
                reject_reason=job.reject_reason,
                reject_category=job.reject_category,
                has_progress=job_has_progress(job, progressed),
                needs_attention=best.no_clean_round,
                regressed=best.regressed,
                url=job.url,
                h1b_sponsorship_status=_h1b_sponsorship_status(
                    job, evidence_by_company
                ),
            )
        )
    return rows


def application_job_pairs(session: Session) -> list[tuple[Application, Job]]:
    """Every active application paired with its unarchived job."""
    archived_col = cast(Any, Job.archived_at)
    statement = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)  # type: ignore[arg-type]
        .where(archived_col.is_(None))
    )
    return [(app, job) for app, job in session.exec(statement).all()]


def application_event_job_rows(
    session: Session,
) -> list[tuple[ApplicationEvent, Application, Job]]:
    """Dated event rows with their active application and unarchived job."""
    statement = (
        select(ApplicationEvent, Application, Job)
        .join(Application, col(ApplicationEvent.application_id) == Application.id)
        .join(Job, col(Application.job_id) == Job.id)
        .where(
            col(ApplicationEvent.occurred_at).is_not(None),
            col(Job.archived_at).is_(None),
        )
    )
    return [
        (event, application, job)
        for event, application, job in session.exec(statement).all()
    ]


def reminder_event_job_rows(
    session: Session,
    *,
    after: datetime,
    before: datetime,
    kinds: set[str],
    dead_results: set[str],
) -> list[tuple[ApplicationEvent, Application, Job]]:
    """Only live reminder candidates in the scheduler's widest time window."""
    statement = (
        select(ApplicationEvent, Application, Job)
        .join(Application, col(ApplicationEvent.application_id) == Application.id)
        .join(Job, col(Application.job_id) == Job.id)
        .where(
            col(ApplicationEvent.occurred_at) > after,
            col(ApplicationEvent.occurred_at) <= before,
            col(ApplicationEvent.kind).in_(kinds),
            col(ApplicationEvent.result).not_in(dead_results),
            col(Application.status).not_in({"rejected", "closed"}),
            col(Job.archived_at).is_(None),
        )
    )
    return [
        (event, application, job)
        for event, application, job in session.exec(statement).all()
    ]


def upcoming_events(
    session: Session,
    *,
    within_days: int = 7,
    now: datetime | None = None,
    kinds: set[str] | frozenset[str] | None = None,
) -> list[tuple[ApplicationEvent, Job]]:
    """Live, actionable events in ``(now, now + within_days]``."""
    current = now or utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    limit = current + timedelta(days=within_days)
    rows: list[tuple[ApplicationEvent, Job]] = []
    for event, application, job in application_event_job_rows(session):
        if application.status in {"rejected", "closed"}:
            continue
        if kinds is not None and event.kind not in kinds:
            continue
        if event.result in {"cancelled", "withdrew"} or event.occurred_at is None:
            continue
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if current < occurred <= limit:
            rows.append((event, job))
    return sorted(
        rows,
        key=lambda row: (
            (row[0].occurred_at or current).replace(tzinfo=timezone.utc)
            if (row[0].occurred_at or current).tzinfo is None
            else row[0].occurred_at or current
        ),
    )


_TRIAGE_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
)


def _triage_row(
    job: Job,
    progressed: set[int],
    evidence_by_company: Mapping[str, H1BSponsorshipEvidence],
) -> TriageRow:
    job_id = _require_job_id(job)
    locations = _location_payload(job.criteria_json or {})
    return TriageRow(
        job_id=job_id,
        company=job.company,
        title=job.title,
        location=job.location,
        source=job.source,
        status=job.status,
        fit_score=job.fit_score,
        posted_at=job.posted_at,
        archived_at=job.archived_at,
        has_progress=job_has_progress(job, progressed),
        reject_reason=job.reject_reason,
        reject_category=job.reject_category,
        url=job.url,
        h1b_sponsorship_status=_h1b_sponsorship_status(job, evidence_by_company),
        locations=locations,
    )


def triage_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    status_col = cast(Any, Job.status)
    jobs = session.exec(
        select(Job)
        .options(defer(cast(Any, Job.jd_text)))
        .where(status_col.in_(_TRIAGE_STATUSES), archived_col.is_(None))
        .order_by(cast(Any, Job.fit_score).asc().nullsfirst())
    ).all()
    return project_triage_jobs(session, jobs)


def archived_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .options(defer(cast(Any, Job.jd_text)))
        .where(archived_col.is_not(None))
        .order_by(archived_col.desc())
    ).all()
    return project_triage_jobs(session, jobs)


def project_triage_jobs(
    session: Session,
    jobs: Sequence[Job],
) -> list[TriageRow]:
    """Project an already-selected job page with page-scoped progress lookups."""
    job_ids = [_require_job_id(job) for job in jobs]
    progressed = progressed_job_ids(session, job_ids)
    evidence_by_company = _company_evidence(session, jobs)
    return [_triage_row(job, progressed, evidence_by_company) for job in jobs]
