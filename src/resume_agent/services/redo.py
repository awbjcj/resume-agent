"""Redo any pipeline stage on explicitly chosen jobs.

The automatic paths (pull/discover/refresh/reprocess) guard against clobbering
user work: merge.decide() freezes jd_text past raw, and reprocess() skips jobs
with progress. Those guards are right for a scheduled run and wrong for a user
who deliberately picked a job. Redo is the explicit escape hatch, and it never
regresses status, never rejects, and never deletes prior artifacts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from playwright.sync_api import Error as PlaywrightError
from sqlmodel import Session

from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.services.errors import StageFailure
from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
from resume_agent.tracking.repository import company_rename_collides, save_job
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
