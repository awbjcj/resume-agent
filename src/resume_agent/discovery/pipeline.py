import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import String
from sqlmodel import Session, select

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.discovery.extract import (  # noqa: F401
    Runner,
    aextract_job_criteria,
    extract_job_criteria,
)
from resume_agent.discovery.filter import apply_filters
from resume_agent.discovery.fit import (  # noqa: F401
    FitScore,
    ascore_fit,
    compose_fit_input,
    score_fit,
)
from resume_agent.discovery.industry import IndustryCandidate, classify_industries
from resume_agent.discovery.relevance import (  # noqa: F401
    ajudge_relevance,
    judge_relevance,
)
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.llm_runner import run_with_cleanup
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.matrix import SkillMatrix, build_skill_match_context
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.industries import (
    INDUSTRY_TAXONOMY_PATH,
    IndustryTaxonomy,
    canonical_industry,
    load_industry_taxonomy,
    merge_industry_taxonomy,
    normalize_company,
    normalize_industry,
    save_industry_taxonomy,
)
from resume_agent.taxonomy.location import build_location
from resume_agent.taxonomy.skills import refresh_aliases, split_skills
from resume_agent.tenancy.paths import SKILL_ALIASES_PATH
from resume_agent.tracking.match_gap import Canonicalizer, normalize_skill
from resume_agent.tracking.repository import has_progress, jobs_by_status, status_counts
from resume_agent.tracking.stages import advance
from resume_agent.tracking.tables import Job, JobStatus

logger = logging.getLogger(__name__)


# The LLM-bound discover phases surfaced to progress consumers; the cheap,
# instant run_filter step is not surfaced. relevance may be skipped (no agent),
# in which case the strip simply opens at phase 2.
_DISCOVER_PHASES = 3


@dataclass(frozen=True)
class StageScope:
    """Which rows a funnel stage runs over, and how it may write status.

    The default reproduces the automatic funnel exactly: select by status,
    write status freely. Redo passes explicit ids with any_status=True and
    never_regress=True so a rendered job can be re-extracted without being
    dragged back down the ladder.
    """

    job_ids: frozenset[int] | None = None
    any_status: bool = False
    never_regress: bool = False


# Frozen and immutable, so sharing this instance as a default arg is safe;
# ruff (B008) forbids a fresh `StageScope()` call in a signature.
_DEFAULT_SCOPE = StageScope()


def _stage_jobs(session: Session, status: str, scope: StageScope) -> list[Job]:
    if scope.any_status and scope.job_ids is not None:
        rows = [session.get(Job, job_id) for job_id in sorted(scope.job_ids)]
        return [job for job in rows if job is not None]
    jobs = jobs_by_status(session, status)
    if scope.job_ids is None:
        return jobs
    return [job for job in jobs if job.id in scope.job_ids]


def run_extract(
    session: Session,
    agent: Runner,
    reporter: ProgressReporter | None = None,
    scope: StageScope = _DEFAULT_SCOPE,
    industry_classifier: Runner | None = None,
    industry_taxonomy_path: Path | str = INDUSTRY_TAXONOMY_PATH,
) -> None:
    jobs = _stage_jobs(session, JobStatus.raw.value, scope)
    if reporter:
        reporter.begin(
            len(jobs), "Extracting criteria", phase_index=2, phase_count=_DISCOVER_PHASES
        )
    if jobs:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None
        results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    jobs,
                    lambda job: aextract_job_criteria(job.jd_text, agent, sem=sem),
                    on_complete=on_complete,
                ),
                agent,
            )
        )
        for job, res in zip(jobs, results):
            if not res.ok or res.value is None:
                # Leave failed jobs raw so the next discover retries them.
                continue
            criteria = res.value
            job.criteria_json = criteria.model_dump(mode="json")
            advance(job, JobStatus.extracted.value, never_regress=scope.never_regress)
            session.add(job)
    _normalize_job_industries(
        session, industry_classifier, industry_taxonomy_path, batch=jobs
    )
    session.commit()


_INDUSTRY_RETRY_KEY = "_industry_candidate"
_STALE_SIC_KEYS = ("sic_major", "sic_label", "sic_division")


def _industry_candidate(criteria: dict) -> str | None:
    value = criteria.get(_INDUSTRY_RETRY_KEY)
    if value is None:
        value = criteria.get("industry")
    if normalize_industry(value) is None:
        return None
    return str(value).strip()


def _prepare_industry_fields(job: Job, taxonomy: IndustryTaxonomy) -> str | None:
    if job.criteria_json is None:
        return None
    criteria = dict(job.criteria_json)
    for key in _STALE_SIC_KEYS:
        criteria.pop(key, None)

    candidate = _industry_candidate(criteria)
    canonical = canonical_industry(job.company, candidate, taxonomy)
    if canonical is not None:
        criteria["industry"] = canonical
        criteria.pop(_INDUSTRY_RETRY_KEY, None)
    elif candidate is not None:
        criteria["industry"] = None
        criteria[_INDUSTRY_RETRY_KEY] = candidate
    else:
        criteria["industry"] = None
        criteria.pop(_INDUSTRY_RETRY_KEY, None)
    if criteria != job.criteria_json:
        job.criteria_json = criteria
    return candidate


def _industry_scope(session: Session, batch: list[Job]) -> list[Job]:
    """Rows this pass can change: the current batch plus revisitable rows."""
    criteria_text = cast(Any, Job.criteria_json).cast(String)
    revisitable = session.exec(
        select(Job).where(
            criteria_text.like(f'%"{_INDUSTRY_RETRY_KEY}"%')
            | criteria_text.like('%"sic_major"%')
        )
    ).all()
    by_id: dict[int | None, Job] = {job.id: job for job in revisitable}
    for job in batch:
        by_id.setdefault(job.id, job)
    return list(by_id.values())


def _normalize_job_industries(
    session: Session,
    classifier: Runner | None,
    taxonomy_path: Path | str,
    batch: list[Job],
) -> None:
    taxonomy = load_industry_taxonomy(taxonomy_path)
    jobs = _industry_scope(session, batch)
    unresolved: dict[tuple[str, str], IndustryCandidate] = {}
    company_additions: dict[str, str] = {}

    for job in jobs:
        candidate = _prepare_industry_fields(job, taxonomy)
        company = normalize_company(job.company)
        industry = normalize_industry(candidate)
        if company and industry:
            canonical = canonical_industry(job.company, candidate, taxonomy)
            if canonical is None:
                unresolved[(company, industry)] = IndustryCandidate(
                    company=company, industry=industry
                )
            elif company not in taxonomy.companies:
                company_additions.setdefault(company, canonical)

    additions: dict[tuple[str, str], str] = {}
    if unresolved and classifier is not None:
        existing = sorted(set(taxonomy.aliases.values()) | set(taxonomy.companies.values()))
        try:
            additions = classify_industries(
                list(unresolved.values()), existing, classifier
            ).assignments
        except Exception:
            logger.warning(
                "industry classification failed; %d industr%s left unresolved this run",
                len(unresolved),
                "y" if len(unresolved) == 1 else "ies",
                exc_info=True,
            )
            additions = {}

    alias_additions: dict[str, str] = {}
    if additions:
        for (company, candidate), canonical in additions.items():
            alias_additions[candidate] = canonical
            canonical_key = normalize_industry(canonical)
            if canonical_key:
                alias_additions[canonical_key] = canonical
            company_additions.setdefault(company, canonical)

    if alias_additions or company_additions:
        taxonomy = merge_industry_taxonomy(
            taxonomy, aliases=alias_additions, companies=company_additions
        )
        save_industry_taxonomy(taxonomy, taxonomy_path)

    for job in jobs:
        _prepare_industry_fields(job, taxonomy)
        session.add(job)


def run_filter(
    session: Session,
    config: SearchConfig,
    scope: StageScope = _DEFAULT_SCOPE,
) -> None:
    jobs = _stage_jobs(session, JobStatus.extracted.value, scope)
    for job in jobs:
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        decision = apply_filters(criteria, config)
        if decision.keep or job.gate_override:
            advance(job, JobStatus.filtered.value, never_regress=scope.never_regress)
        elif advance(job, JobStatus.rejected.value, never_regress=scope.never_regress):
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
    scope: StageScope = _DEFAULT_SCOPE,
    matrix: SkillMatrix | None = None,
    cluster_map: ClusterMap | None = None,
) -> None:
    jobs = _stage_jobs(session, JobStatus.filtered.value, scope)
    if reporter:
        reporter.begin(len(jobs), "Scoring fit", phase_index=3, phase_count=_DISCOVER_PHASES)
    if jobs:
        locations = [_job_location_text(job) for job in jobs]
        pairs = list(zip(jobs, locations))
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None

        def _skill_context(job: Job):
            if matrix is None or cluster_map is None:
                return None
            criteria = JobCriteria.model_validate(job.criteria_json or {})
            return build_skill_match_context(criteria, matrix, cluster_map)

        results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    pairs,
                    lambda pair: ascore_fit(
                        compose_fit_input(
                            pair[0].jd_text,
                            profile_facts,
                            pair[1],
                            skill_context=_skill_context(pair[0]),
                        ),
                        agent,
                        sem=sem,
                    ),
                    on_complete=on_complete,
                ),
                agent,
            )
        )
        for (job, location_text), res in zip(pairs, results):
            if not res.ok or res.value is None:
                # Leave failed jobs filtered so the next discover retries them.
                continue
            fit = res.value
            job.fit_score = fit.score
            job.fit_rationale = fit.rationale
            _write_taxonomy_fields(job, fit, location_text)
            advance(job, JobStatus.shortlisted.value, never_regress=scope.never_regress)
            session.add(job)
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
    scope: StageScope = _DEFAULT_SCOPE,
) -> int:
    """Reject off-target raw jobs via the cheap relevance gate."""
    target = _relevance_target(config)
    if target is None or agent is None:
        return 0

    jobs = [
        job
        for job in _stage_jobs(session, JobStatus.raw.value, scope)
        if not job.gate_override
    ]
    judged = [job for job in jobs if (job.jd_text or "").strip()]
    skipped = len(jobs) - len(judged)
    if reporter:
        reporter.begin(
            len(jobs), "Checking relevance", phase_index=1, phase_count=_DISCOVER_PHASES
        )
    rejected = 0
    if judged:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(skipped + n)) if reporter else None
        results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    judged,
                    lambda job: ajudge_relevance(
                        target, job.title, job.jd_text or "", agent, sem=sem
                    ),
                    on_complete=on_complete,
                ),
                agent,
            )
        )
        for job, res in zip(judged, results):
            if not res.ok or res.value is None:
                continue
            verdict = res.value
            if not verdict.keep and advance(
                job, JobStatus.rejected.value, never_regress=scope.never_regress
            ):
                reason = (verdict.reason or "model rejected").strip()
                job.reject_reason = f"off-target role: {reason}"
                job.reject_category = "relevance"
                session.add(job)
                rejected += 1
    if reporter:
        reporter.step(len(jobs))
    session.commit()
    return rejected


def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    relevance_agent: Runner | None = None,
    canonicalizer: Canonicalizer | None = None,
    industry_classifier: Runner | None = None,
    industry_taxonomy_path: Path | str = INDUSTRY_TAXONOMY_PATH,
    reporter: ProgressReporter | None = None,
    scope: StageScope = _DEFAULT_SCOPE,
    matrix: SkillMatrix | None = None,
    cluster_map: ClusterMap | None = None,
) -> dict[str, int]:
    """Run the full funnel over current rows (optionally scoped)."""
    run_relevance(session, config, relevance_agent, reporter=reporter, scope=scope)
    run_extract(
        session,
        extract_agent,
        reporter=reporter,
        scope=scope,
        industry_classifier=industry_classifier,
        industry_taxonomy_path=industry_taxonomy_path,
    )
    run_filter(session, config, scope=scope)
    run_score(
        session, profile_facts, fit_agent, canonicalizer=canonicalizer,
        reporter=reporter, scope=scope,
        matrix=matrix, cluster_map=cluster_map,
    )
    if reporter:
        reporter.done()
    return status_counts(session)


_REPROCESS_ALL_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
    JobStatus.shortlisted.value,
)


def _scope_jobs(session: Session, scope: str) -> list[Job]:
    if scope == "shortlisted":
        return jobs_by_status(session, JobStatus.shortlisted.value)
    if scope == "rejected:relevance":
        return [
            j for j in jobs_by_status(session, JobStatus.rejected.value)
            if j.reject_category == "relevance"
        ]
    if scope == "rejected:filtered":
        return [
            j for j in jobs_by_status(session, JobStatus.rejected.value)
            if j.reject_category == "filtered"
        ]
    if scope == "all":
        jobs: list[Job] = []
        for status in _REPROCESS_ALL_STATUSES:
            jobs.extend(jobs_by_status(session, status))
        return jobs
    raise ValueError(f"unknown reprocess scope: {scope}")


def reprocess(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    scopes: list[str],
    relevance_agent: Runner | None = None,
    canonicalizer: Canonicalizer | None = None,
    industry_classifier: Runner | None = None,
    industry_taxonomy_path: Path | str = INDUSTRY_TAXONOMY_PATH,
    reporter: ProgressReporter | None = None,
    matrix: SkillMatrix | None = None,
    cluster_map: ClusterMap | None = None,
) -> dict[str, int]:
    """Reset in-scope, non-progressed jobs to a clean raw state and re-run the funnel."""
    selected: dict[int, Job] = {}
    for scope in scopes:
        for job in _scope_jobs(session, scope):
            if job.id is None or job.id in selected:
                continue
            if has_progress(session, job.id):
                continue
            selected[job.id] = job
    for job in selected.values():
        job.status = JobStatus.raw.value
        job.reject_reason = None
        job.reject_category = None
        job.fit_score = None
        job.fit_rationale = None
        job.criteria_json = None
        session.add(job)
    session.commit()
    return discover(
        session, config, profile_facts, extract_agent, fit_agent, relevance_agent,
        canonicalizer=canonicalizer,
        industry_classifier=industry_classifier,
        industry_taxonomy_path=industry_taxonomy_path,
        reporter=reporter,
        scope=StageScope(job_ids=frozenset(selected)),
        matrix=matrix,
        cluster_map=cluster_map,
    )
