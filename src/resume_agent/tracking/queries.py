from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlmodel import Session, select

from resume_agent.models.profile import ProfileFacts
from resume_agent.taxonomy import sic as sic_tax
from resume_agent.taxonomy.company_size import snap as snap_size
from resume_agent.taxonomy.skills import canonical_skill, load_aliases, split_skills
from resume_agent.tracking.match_gap import profile_skill_tokens
from resume_agent.tracking.repository import (
    application_for_job,
    cover_letters_for_job,
    has_progress,
    latest_rendered_resume_version,
    latest_resume_version,
    resume_versions_for_job,
)
from resume_agent.tracking.tables import Application, CoverLetter, Job, JobStatus, ResumeVersion


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
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    is_us: bool = False


@dataclass
class JobDetailRow:
    # Detail-only columns (named to match the JobDetail schema: id, not job_id).
    id: int
    source: str
    url: str | None
    jd_text: str
    status: str
    criteria_json: dict[str, Any] | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: Application | None
    resume_versions: list[ResumeVersion]
    cover_letters: list[CoverLetter]
    # Facet half mirrors ShortlistRow and is reused via _shortlist_row.
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None


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


@dataclass
class PipelineRow:
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: int | None
    salary_max: int | None
    remote_policy: str | None
    seniority: str | None
    has_progress: bool = False


def _skill_tags(criteria: dict, tokens: set[str], aliases: dict[str, str]) -> list[SkillTag]:
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
                SkillTag(name=canonical, covered=canonical in profile_canonical, required=required)
            )
    return tags


def _shortlist_row(
    job: Job, tokens: set[str], aliases: dict[str, str], sic_table: Any
) -> ShortlistRow:
    """Project one ``Job`` into the full skill + meta facet row.

    Shared by the board list (``shortlist_rows``) and the single-job detail
    facets (``job_facets``) so the wire format stays identical across the card
    preview and the detail modal.
    """
    job_id = _require_job_id(job)
    criteria = job.criteria_json or {}
    salary = criteria.get("salary_range") or {}
    loc = criteria.get("location_parts") or {}
    code = sic_tax.coerce_code(criteria.get("sic_major"), sic_table)
    division = sic_tax.division_for(code, sic_table)
    return ShortlistRow(
        job_id=job_id,
        company=job.company,
        title=job.title,
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
        sic_major=code,
        sic_label=sic_tax.display_label(code, sic_table),
        sic_division=division[1] if division else None,
        location_country=loc.get("country"),
        location_region=loc.get("region"),
        location_city=loc.get("city"),
        is_us=bool(loc.get("is_us")),
    )


def shortlist_rows(
    session: Session,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = "data/skill_aliases.json",
) -> list[ShortlistRow]:
    fit_score_col = cast(Any, Job.fit_score)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value, archived_col.is_(None))
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    sic_table = sic_tax.load_sic_table()
    return [_shortlist_row(job, tokens, aliases, sic_table) for job in jobs]


def job_facets(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = "data/skill_aliases.json",
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
    sic_table = sic_tax.load_sic_table()
    return _shortlist_row(job, tokens, aliases, sic_table)


def job_detail_row(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = "data/skill_aliases.json",
) -> JobDetailRow | None:
    """Assemble the full detail read-model for one job."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    sic_table = sic_tax.load_sic_table()
    facets = _shortlist_row(job, tokens, aliases, sic_table)
    jid = _require_job_id(job)
    return JobDetailRow(
        id=jid,
        source=job.source,
        url=job.url,
        jd_text=job.jd_text,
        status=job.status,
        criteria_json=job.criteria_json,
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, jid),
        application=application_for_job(session, jid),
        resume_versions=resume_versions_for_job(session, jid),
        cover_letters=cover_letters_for_job(session, jid),
        company=facets.company,
        title=facets.title,
        location=facets.location,
        fit_score=facets.fit_score,
        fit_rationale=facets.fit_rationale,
        sponsorship_signal=facets.sponsorship_signal,
        salary_min=facets.salary_min,
        salary_max=facets.salary_max,
        salary_currency=facets.salary_currency,
        remote_policy=facets.remote_policy,
        seniority=facets.seniority,
        employment_type=facets.employment_type,
        industry=facets.industry,
        company_size=facets.company_size,
        posted_at=facets.posted_at,
        skills=facets.skills,
        sic_major=facets.sic_major,
        sic_label=facets.sic_label,
        sic_division=facets.sic_division,
        location_country=facets.location_country,
        location_region=facets.location_region,
        location_city=facets.location_city,
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
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        version = latest_resume_version(session, job_id)
        rendered = latest_rendered_resume_version(session, job_id)
        application = application_for_job(session, job_id)
        rows.append(
            PipelineRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                status=job.status,
                fit_score=job.fit_score,
                jd_text=job.jd_text,
                # None means "never tailored" (no version); [] means a version
                # exists but reviewers raised nothing. The board reads them apart.
                critique_json=(version.critique_json or []) if version else None,
                pdf_path=rendered.pdf_path if rendered else None,
                application_status=application.status if application else None,
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                has_progress=has_progress(session, job_id),
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


_TRIAGE_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
)


def _triage_row(session: Session, job: Job) -> TriageRow:
    job_id = _require_job_id(job)
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
        has_progress=has_progress(session, job_id),
    )


def triage_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    status_col = cast(Any, Job.status)
    jobs = session.exec(
        select(Job)
        .where(status_col.in_(_TRIAGE_STATUSES), archived_col.is_(None))
        .order_by(cast(Any, Job.fit_score).asc().nullsfirst())
    ).all()
    return [_triage_row(session, job) for job in jobs]


def archived_rows(session: Session) -> list[TriageRow]:
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job).where(archived_col.is_not(None)).order_by(archived_col.desc())
    ).all()
    return [_triage_row(session, job) for job in jobs]
