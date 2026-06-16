from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlmodel import Session, select

from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.match_gap import normalize_skill, profile_skill_tokens
from resume_agent.tracking.repository import (
    application_for_job,
    latest_rendered_resume_version,
    latest_resume_version,
)
from resume_agent.tracking.tables import Application, Job, JobStatus


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


def _skill_tags(criteria: dict, tokens: set[str]) -> list[SkillTag]:
    # tech_stack (techs the post names) is also surfaced as non-required tags so
    # the skill cloud and "Skills (any match)" filter can match on it; deduped by
    # normalized token, with must_have > nice_to_have > tech_stack taking the slot.
    tags: list[SkillTag] = []
    seen: set[str] = set()
    for key, required in (
        ("must_have_skills", True),
        ("nice_to_have_skills", False),
        ("tech_stack", False),
    ):
        for raw_name in criteria.get(key) or []:
            name = str(raw_name).strip()
            token = normalize_skill(name)
            if not token or token in seen:
                continue
            seen.add(token)
            tags.append(SkillTag(name=name, covered=token in tokens, required=required))
    return tags


def shortlist_rows(session: Session, facts: ProfileFacts | None = None) -> list[ShortlistRow]:
    fit_score_col = cast(Any, Job.fit_score)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value)
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        rows.append(
            ShortlistRow(
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
                company_size=criteria.get("company_size"),
                posted_at=job.posted_at,
                skills=_skill_tags(criteria, tokens),
            )
        )
    return rows


def pipeline_rows(session: Session) -> list[PipelineRow]:
    status_col = cast(Any, Job.status)
    company_col = cast(Any, Job.company)
    title_col = cast(Any, Job.title)
    jobs = session.exec(select(Job).order_by(status_col, company_col, title_col)).all()
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
                critique_json=version.critique_json if version else None,
                pdf_path=rendered.pdf_path if rendered else None,
                application_status=application.status if application else None,
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
            )
        )
    return rows


def application_job_pairs(session: Session) -> list[tuple[Application, Job]]:
    """Every application paired with its job (one query, no N+1 per-row fetch)."""
    statement = select(Application, Job).join(Job, Application.job_id == Job.id)  # type: ignore[arg-type]
    return [(app, job) for app, job in session.exec(statement).all()]
