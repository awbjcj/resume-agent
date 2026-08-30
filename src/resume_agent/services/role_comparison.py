"""Project stored application evidence without model calls."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.h1b.cache import load_company_evidence
from resume_agent.role_comparison.models import (
    CompanyEvidenceComparison,
    RoleComparisonItem,
)
from resume_agent.services.company_intelligence import load_company_intelligence
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tracking.timeline_pivot import build_pivot

_VERIFICATION_RANK = {"inferred": 0, "single_source": 1, "corroborated": 2}


def _company_projection(session: Session, company: str | None, now: datetime):
    evidence = load_company_intelligence(session, company or "")
    if evidence is None:
        return CompanyEvidenceComparison(state="not_researched")
    strongest = max(
        (insight.verification_state for insight in evidence.insights),
        key=lambda value: _VERIFICATION_RANK[value],
        default=None,
    )
    return CompanyEvidenceComparison(
        state="ready",
        retrieved_at=evidence.retrieved_at,
        is_stale=not evidence.is_fresh(now),
        research_depth=evidence.research_depth,
        source_count=len(evidence.sources),
        strongest_verification=strongest,
    )


def compare_roles(
    session: Session, job_ids: list[int], *, now: datetime | None = None
) -> list[RoleComparisonItem]:
    requested = list(dict.fromkeys(job_ids))
    if len(requested) not in {2, 3}:
        raise ValueError("choose two or three distinct jobs")
    rows_by_id = {row.job_id: row for row in build_pivot(session).rows}
    missing = [job_id for job_id in requested if job_id not in rows_by_id]
    if missing:
        raise LookupError(
            "application jobs not found: " + ", ".join(str(value) for value in missing)
        )
    rows = [rows_by_id[job_id] for job_id in requested]
    h1b = load_company_evidence(session, [row.company for row in rows])
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return [
        RoleComparisonItem(
            job_id=row.job_id,
            company=row.company,
            title=row.title,
            fit_score=row.fit_score,
            application_status=row.status,
            company_evidence=_company_projection(session, row.company, moment),
            h1b_status=(
                h1b.get(normalize_company(row.company)).status
                if normalize_company(row.company) in h1b
                else None
            ),
            offer_total=row.total_comp,
            offer_currency=row.comp_currency,
        )
        for row in rows
    ]
