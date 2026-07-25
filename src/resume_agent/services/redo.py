"""Redo any pipeline stage on explicitly chosen jobs.

The automatic paths (pull/discover/refresh/reprocess) guard against clobbering
user work: merge.decide() freezes jd_text past raw, and reprocess() skips jobs
with progress. Those guards are right for a scheduled run and wrong for a user
who deliberately picked a job. Redo is the explicit escape hatch, and it never
regresses status, never rejects, and never deletes prior artifacts.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.discovery.pipeline import (
    StageScope,
    run_extract,
    run_filter,
    run_score,
)
from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.services.agents import build_discovery_bundle, build_url_extract_agent
from resume_agent.services.discovery import _skill_artifacts
from resume_agent.services.errors import (
    StageFailure,
    record_job_failure,
    resolve_job_failures,
)
from resume_agent.services.rendering import render_resume_version
from resume_agent.services.tailoring import tailor
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import FACTS_PATH, SEARCH_PATH
from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
from resume_agent.tracking.repository import (
    application_for_job,
    company_rename_collides,
    get_job,
    resume_versions_for_job,
    save_job,
)
from resume_agent.tracking.tables import Job

logger = logging.getLogger(__name__)

RedoStage = Literal["pull", "extract", "tailor", "render"]

# Stages always run in pipeline order, whatever order the caller listed them.
REDO_STAGES: tuple[RedoStage, ...] = ("pull", "extract", "tailor", "render")


@dataclass(frozen=True)
class StageOutcome:
    """One job's result for one stage, as reported in the run payload.

    Distinct from StageFailure, which is the durable diagnostic written to
    ErrorRecord. `detail` carries the same one-line message.
    """

    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None


def repull_job(
    session: Session,
    job: Job,
    *,
    agent,
    allow_browser: bool,
) -> tuple[StageOutcome, StageFailure | None]:
    """Re-fetch a job's posting and replace its description in place.

    Deliberately bypasses find_existing/decide/_apply. That machinery answers
    "is this the same job, and does it outrank what I hold?" -- already settled
    for a row the user picked -- and it is what freezes jd_text at merge.py:179.
    """
    job_id = job.id
    if job_id is None:
        raise ValueError("cannot re-pull an unsaved job")
    if not job.url:
        return StageOutcome(job_id, "pull", "skipped", "no source URL"), None

    try:
        raw = job_from_url(job.url, agent=agent, allow_browser=allow_browser)
    except (httpx.HTTPError, PlaywrightError) as exc:
        logger.warning("repull job=%s failed", job_id, exc_info=exc)
        failure = StageFailure.from_exception(exc)
        detail = f"{failure.error_type}: {failure.message}"
        return StageOutcome(job_id, "pull", "failed", detail), failure

    if raw is None or not raw.jd_text.strip():
        detail = "no job description found"
        return (
            StageOutcome(job_id, "pull", "failed", detail),
            StageFailure(
                error_type="UrlFetchError", message=detail, traceback_tail=""
            ),
        )

    job.jd_text = raw.jd_text
    job.content_fingerprint = compute_content_fingerprint(raw.jd_text)
    if raw.location:
        job.location = raw.location

    company = raw.company or job.company
    title = raw.title or job.title
    if company != job.company or title != job.title:
        new_key = compute_dedup_key(company, title)
        if company_rename_collides(session, existing=job, dedup_key=new_key):
            # Another live row already holds that identity. Take the text and
            # leave company/title/dedup_key alone rather than stealing it.
            logger.info("repull job=%s kept identity (key collision)", job_id)
        else:
            job.company = company
            job.title = title
            job.dedup_key = new_key

    save_job(session, job)
    return StageOutcome(job_id, "pull", "ok", None), None


def _record(session, job, stage, failure, run_id, model=None) -> None:
    """Persist a failure. Never let bookkeeping turn a partial run into a total one."""
    try:
        record_job_failure(
            session, job=job, stage=stage, failure=failure, run_id=run_id, model=model
        )
    except Exception:
        logger.warning(
            "could not record failure for job=%s stage=%s", job.id, stage, exc_info=True
        )


def _settle(session, job, stage, outcome, failure, run_id, model=None) -> StageOutcome:
    if outcome.status == "failed" and failure is not None:
        _record(session, job, stage, failure, run_id, model=model)
    elif outcome.status == "ok":
        resolve_job_failures(session, outcome.job_id, stage)
    return outcome


def _run_pull(session, jobs, run_id) -> list[StageOutcome]:
    agent = build_url_extract_agent()
    allow_browser = get_settings().browser_enabled
    outcomes = []
    for job in jobs:
        outcome, failure = repull_job(
            session, job, agent=agent, allow_browser=allow_browser
        )
        outcomes.append(_settle(session, job, "pull", outcome, failure, run_id))
    return outcomes


def _run_extract(session, jobs, run_id) -> list[StageOutcome]:
    """Re-run extract -> filter -> score over these ids, forward-only.

    run_relevance is deliberately not run: it exists to reject off-target raw
    rows, so under never_regress it is a guaranteed no-op.
    """
    config = load_search_config(SEARCH_PATH)
    facts = load_facts(FACTS_PATH)
    matrix, cluster_map = _skill_artifacts(FACTS_PATH, facts)
    bundle = build_discovery_bundle()
    scope = StageScope(
        job_ids=frozenset(job.id for job in jobs if job.id is not None),
        any_status=True,
        never_regress=True,
    )
    run_extract(
        session, bundle.extract, scope=scope,
        industry_classifier=bundle.industry_classifier,
    )
    run_filter(session, config, scope)
    run_score(
        session, facts, bundle.fit, canonicalizer=bundle.canonicalizer,
        scope=scope, matrix=matrix, cluster_map=cluster_map,
    )
    outcomes = []
    for job in jobs:
        assert job.id is not None
        outcomes.append(
            _settle(session, job, "extract",
                    StageOutcome(job.id, "extract", "ok", None), None, run_id)
        )
    return outcomes


def _run_tailor(session, jobs, run_id, deep) -> list[StageOutcome]:
    from resume_agent.services.tailoring import DEFAULT_REVIEW, DEFAULT_REVIEW_DEEP

    ids = [job.id for job in jobs if job.id is not None]
    outcome = tailor(
        session,
        job_ids=ids,
        review_path=DEFAULT_REVIEW_DEEP if deep else DEFAULT_REVIEW,
    )
    results = []
    for job in jobs:
        assert job.id is not None
        failure = outcome.failures.get(job.id)
        if failure is not None:
            detail = f"{failure.error_type}: {failure.message}"
            results.append(
                _settle(session, job, "tailor",
                        StageOutcome(job.id, "tailor", "failed", detail),
                        failure, run_id, model=outcome.model)
            )
        else:
            results.append(
                _settle(session, job, "tailor",
                        StageOutcome(job.id, "tailor", "ok", None), None, run_id)
            )
    return results


def _render_target(session, job_id: int) -> int | None:
    """The Application's chosen version, else the highest-id version."""
    application = application_for_job(session, job_id)
    if application is not None and application.resume_version_id is not None:
        return application.resume_version_id
    versions = resume_versions_for_job(session, job_id)
    if not versions:
        return None
    return max(version.id or 0 for version in versions) or None


def _run_render(session, jobs, run_id) -> list[StageOutcome]:
    outcomes = []
    for job in jobs:
        assert job.id is not None
        version_id = _render_target(session, job.id)
        if version_id is None:
            outcomes.append(
                StageOutcome(job.id, "render", "skipped", "no resume version")
            )
            continue
        try:
            render_resume_version(session, version_id)
        except Exception as exc:
            logger.warning("render job=%s failed", job.id, exc_info=exc)
            failure = StageFailure.from_exception(exc)
            outcomes.append(
                _settle(
                    session, job, "render",
                    StageOutcome(job.id, "render", "failed",
                                 f"{failure.error_type}: {failure.message}"),
                    failure, run_id,
                )
            )
            continue
        outcomes.append(
            _settle(session, job, "render",
                    StageOutcome(job.id, "render", "ok", None), None, run_id)
        )
    return outcomes


def redo_jobs(
    session: Session,
    *,
    job_ids: Sequence[int],
    stages: Sequence[RedoStage],
    deep: bool = False,
    reporter: ProgressReporter | None = None,
    run_id: str | None = None,
) -> list[StageOutcome]:
    """Re-run the chosen stages over the chosen jobs, stage-major.

    Inputs are validated at the API boundary (RedoParams): non-empty and
    deduped. This function trusts them.
    """
    enforce_active_budget()
    ordered = [stage for stage in REDO_STAGES if stage in set(stages)]
    found = {job_id: get_job(session, job_id) for job_id in job_ids}
    jobs = [job for job in found.values() if job is not None]

    outcomes: list[StageOutcome] = [
        StageOutcome(job_id, ordered[0], "skipped", "job not found")
        for job_id, job in found.items()
        if job is None
    ]
    if not jobs:
        return outcomes

    runners = {
        "pull": lambda: _run_pull(session, jobs, run_id),
        "extract": lambda: _run_extract(session, jobs, run_id),
        "tailor": lambda: _run_tailor(session, jobs, run_id, deep),
        "render": lambda: _run_render(session, jobs, run_id),
    }
    for index, stage in enumerate(ordered):
        if reporter:
            reporter.begin(len(jobs), f"Redo: {stage}",
                           phase_index=index + 1, phase_count=len(ordered))
        outcomes.extend(runners[stage]())
        if reporter:
            reporter.step(len(jobs))
    if reporter:
        reporter.done()
    return outcomes
