"""Project stored application evidence without model calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlmodel import Session

from resume_tailor_harness.company_intelligence.models import (
    CompanyIntelligenceEvidence,
    CompanyVerificationState,
)
from resume_tailor_harness.h1b.cache import load_company_evidence
from resume_tailor_harness.h1b.models import H1BSponsorshipEvidence
from resume_tailor_harness.role_comparison.models import (
    CompanyEvidenceComparison,
    RoleComparisonItem,
)
from resume_tailor_harness.services.company_intelligence import load_company_intelligence_many
from resume_tailor_harness.taxonomy.industries import normalize_company
from resume_tailor_harness.tracking.status_rules import TERMINAL
from resume_tailor_harness.tracking.timeline_pivot import build_pivot

_VERIFICATION_RANK = {"inferred": 0, "single_source": 1, "corroborated": 2}


class InactiveRoleComparisonError(ValueError):
    """Selected applications include a terminal funnel state."""


def _company_projection(
    evidence: CompanyIntelligenceEvidence | None, now: datetime
) -> CompanyEvidenceComparison:
    if evidence is None:
        return CompanyEvidenceComparison(state="not_researched")
    verification_states: list[CompanyVerificationState] = [
        insight.verification_state for insight in evidence.insights
    ]
    strongest = max(
        verification_states,
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


def _h1b_status(
    company: str | None, evidence: dict[str, H1BSponsorshipEvidence]
) -> Literal["matched", "no_match", "unavailable"] | None:
    key = normalize_company(company)
    return evidence[key].status if key is not None and key in evidence else None


def compare_roles(
    session: Session, job_ids: list[int], *, now: datetime | None = None
) -> list[RoleComparisonItem]:
    requested = list(dict.fromkeys(job_ids))
    if len(requested) not in {2, 3}:
        raise ValueError("choose two or three distinct jobs")
    rows_by_id = {
        row.job_id: row for row in build_pivot(session, job_ids=requested).rows
    }
    missing = [job_id for job_id in requested if job_id not in rows_by_id]
    if missing:
        raise LookupError(
            "application jobs not found: " + ", ".join(str(value) for value in missing)
        )
    rows = [rows_by_id[job_id] for job_id in requested]
    inactive = [row.job_id for row in rows if row.status in TERMINAL]
    if inactive:
        raise InactiveRoleComparisonError(
            "comparison requires active applications; terminal jobs: "
            + ", ".join(str(value) for value in inactive)
        )
    h1b = load_company_evidence(session, [row.company for row in rows])
    company_evidence = load_company_intelligence_many(
        session, [row.company for row in rows]
    )
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
            company_evidence=_company_projection(
                company_evidence.get(normalize_company(row.company) or ""), moment
            ),
            h1b_status=_h1b_status(row.company, h1b),
            offer_total=row.total_comp,
            offer_currency=row.comp_currency,
        )
        for row in rows
    ]
