from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.extract import Runner, extract_job_criteria
from resume_agent.discovery.filter import apply_filters
from resume_agent.discovery.fit import FitScore, compose_fit_input, score_fit
from resume_agent.discovery.relevance import judge_relevance
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy import sic
from resume_agent.taxonomy.location import build_location
from resume_agent.taxonomy.skills import refresh_aliases, split_skills
from resume_agent.tracking.match_gap import Canonicalizer, normalize_skill
from resume_agent.tracking.repository import jobs_by_status, status_counts
from resume_agent.tracking.tables import Job, JobStatus

SKILL_ALIASES_PATH = Path("data/skill_aliases.json")
_SIC_TABLE = sic.load_sic_table()


_REEXTRACT_STATUSES = (
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
    JobStatus.shortlisted.value,
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
)


# The LLM-bound discover phases the dashboard shows a per-phase bar for; the
# cheap, instant run_filter step is not surfaced. relevance may be skipped (no
# agent), in which case the strip simply opens at phase 2.
_DISCOVER_PHASES = 3


def run_extract(session: Session, agent: Runner, reporter: ProgressReporter | None = None) -> None:
    jobs = jobs_by_status(session, JobStatus.raw.value)
    if reporter:
        reporter.begin(
            len(jobs), "Extracting criteria", phase_index=2, phase_count=_DISCOVER_PHASES
        )
    for index, job in enumerate(jobs, 1):
        criteria = extract_job_criteria(job.jd_text, agent)
        job.criteria_json = criteria.model_dump(mode="json")
        job.status = JobStatus.extracted.value
        session.add(job)
        if reporter:
            reporter.step(index)
    session.commit()


def run_filter(session: Session, config: SearchConfig) -> None:
    for job in jobs_by_status(session, JobStatus.extracted.value):
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        decision = apply_filters(criteria, config)
        if decision.keep:
            job.status = JobStatus.filtered.value
        else:
            job.status = JobStatus.rejected.value
            job.reject_reason = decision.reject_reason
            job.reject_category = "filtered"
        session.add(job)
    session.commit()


def run_score(
    session: Session,
    profile_facts: ProfileFacts,
    agent: Runner,
    canonicalizer: Canonicalizer | None = None,
    aliases_path: Path | str = SKILL_ALIASES_PATH,
    reporter: ProgressReporter | None = None,
) -> None:
    jobs = jobs_by_status(session, JobStatus.filtered.value)
    if reporter:
        reporter.begin(len(jobs), "Scoring fit", phase_index=3, phase_count=_DISCOVER_PHASES)
    for index, job in enumerate(jobs, 1):
        location_text = _job_location_text(job)
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts, location_text), agent)
        job.fit_score = fit.score
        job.fit_rationale = fit.rationale
        _write_taxonomy_fields(job, fit, location_text)
        job.status = JobStatus.shortlisted.value
        session.add(job)
        if reporter:
            reporter.step(index)
    session.commit()
    if canonicalizer is not None:
        _refresh_skill_aliases(
            jobs_by_status(session, JobStatus.shortlisted.value), canonicalizer, aliases_path
        )


def _job_location_text(job: Job) -> str | None:
    criteria = job.criteria_json or {}
    value = job.location or criteria.get("location")
    return str(value).strip() if value and str(value).strip() else None


def _write_taxonomy_fields(job: Job, fit: FitScore, raw_location: str | None) -> None:
    criteria = dict(job.criteria_json or {})
    criteria["sic_major"] = sic.coerce_code(fit.sic_major, _SIC_TABLE)
    if fit.location is not None:
        loc = build_location(
            fit.location.city, fit.location.region, fit.location.country, raw=raw_location
        )
        criteria["location_parts"] = loc.as_dict()
    job.criteria_json = criteria


def _refresh_skill_aliases(
    jobs: list[Job], canonicalizer: Canonicalizer, aliases_path: Path | str
) -> None:
    tokens: set[str] = set()
    for job in jobs:
        criteria = job.criteria_json or {}
        for key in ("must_have_skills", "nice_to_have_skills", "tech_stack"):
            for atomic in split_skills([str(s) for s in (criteria.get(key) or [])]):
                token = normalize_skill(atomic)
                if token:
                    tokens.add(token)
    if tokens:
        refresh_aliases(tokens, canonicalizer, aliases_path)


def _relevance_target(config: SearchConfig) -> str | None:
    if config.target_role and config.target_role.strip():
        return config.target_role.strip()
    titles = [title.strip() for title in config.titles if title.strip()]
    if titles:
        return "Roles like: " + ", ".join(titles)
    return None


def run_relevance(
    session: Session,
    config: SearchConfig,
    agent: Runner | None,
    reporter: ProgressReporter | None = None,
) -> int:
    """Reject off-target raw jobs via the cheap relevance gate."""
    target = _relevance_target(config)
    if target is None or agent is None:
        return 0

    jobs = jobs_by_status(session, JobStatus.raw.value)
    if reporter:
        reporter.begin(
            len(jobs), "Checking relevance", phase_index=1, phase_count=_DISCOVER_PHASES
        )
    rejected = 0
    for index, job in enumerate(jobs, 1):
        jd_text = job.jd_text or ""
        if not jd_text.strip():
            if reporter:
                reporter.step(index)
            continue
        try:
            verdict = judge_relevance(target, job.title, jd_text, agent)
        except Exception:
            if reporter:
                reporter.step(index)
            continue
        if not verdict.keep:
            reason = (verdict.reason or "model rejected").strip()
            job.status = JobStatus.rejected.value
            job.reject_reason = f"off-target role: {reason}"
            job.reject_category = "relevance"
            session.add(job)
            rejected += 1
        if reporter:
            reporter.step(index)
    session.commit()
    return rejected


def reextract(session: Session, agent: Runner) -> int:
    """Re-run extraction over already-processed jobs, rewriting criteria_json in place.

    Does not change status or fit. Returns the number of jobs updated.
    """
    updated = 0
    for status in _REEXTRACT_STATUSES:
        for job in jobs_by_status(session, status):
            if not job.jd_text.strip():
                continue
            criteria = extract_job_criteria(job.jd_text, agent)
            job.criteria_json = criteria.model_dump(mode="json")
            session.add(job)
            updated += 1
    session.commit()
    return updated


def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    relevance_agent: Runner | None = None,
    canonicalizer: Canonicalizer | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Run the full funnel over current rows and return final status counts."""
    run_relevance(session, config, relevance_agent, reporter=reporter)
    run_extract(session, extract_agent, reporter=reporter)
    run_filter(session, config)
    run_score(session, profile_facts, fit_agent, canonicalizer=canonicalizer, reporter=reporter)
    if reporter:
        reporter.done()
    return status_counts(session)


def backfill_rescore(
    session: Session,
    profile_facts: ProfileFacts,
    agent: Runner,
    canonicalizer: Canonicalizer | None = None,
    aliases_path: Path | str = SKILL_ALIASES_PATH,
) -> int:
    """Populate sic_major + location for already-shortlisted jobs.

    Re-runs the fit agent only to harvest the new fields; does NOT change
    fit_score or status. Returns the number of jobs updated.
    """
    updated = 0
    for job in jobs_by_status(session, JobStatus.shortlisted.value):
        if not job.jd_text.strip():
            continue
        location_text = _job_location_text(job)
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts, location_text), agent)
        _write_taxonomy_fields(job, fit, location_text)
        session.add(job)
        updated += 1
    session.commit()
    if canonicalizer is not None:
        _refresh_skill_aliases(
            jobs_by_status(session, JobStatus.shortlisted.value), canonicalizer, aliases_path
        )
    return updated
