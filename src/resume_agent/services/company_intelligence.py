"""Generate, validate, cache, and load company-intelligence evidence."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, select

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceDraft,
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.config import Settings
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tracking.tables import CompanyIntelligenceEvidenceRow, utcnow

COMPANY_INTELLIGENCE_CAVEAT = (
    "Public company research can be incomplete or become outdated. Verify important "
    "claims with the linked sources before using them in an application or interview."
)
COMPANY_INTELLIGENCE_EMPTY_MESSAGE = (
    "No company research has been saved yet. Run an explicit refresh to build a cited dossier."
)
_URL = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)
_WRITE_LOCK = Lock()


def _normalized_http_url(value: str) -> str | None:
    parsed = urlsplit(value.rstrip(".,;:"))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _grounded_evidence(
    *,
    company: str,
    draft: CompanyIntelligenceDraft,
    research: str,
    retrieved_at: datetime,
    expires_at: datetime,
) -> CompanyIntelligenceEvidence:
    grounded_urls: dict[str, str] = {}
    for raw in _URL.findall(research):
        exact_url = raw.rstrip(".,;:")
        normalized = _normalized_http_url(exact_url)
        if normalized is not None:
            grounded_urls.setdefault(normalized, exact_url)
    sources: list[CompanyIntelligenceSource] = []
    seen: set[str] = set()
    for source in draft.sources:
        normalized = _normalized_http_url(source.url)
        if normalized is None or normalized not in grounded_urls or normalized in seen:
            continue
        seen.add(normalized)
        sources.append(source.model_copy(update={"url": grounded_urls[normalized]}))

    allowed = {
        normalized: source.url
        for source in sources
        if (normalized := _normalized_http_url(source.url)) is not None
    }
    insights: list[CompanyIntelligenceInsight] = []
    seen_axes: set[str] = set()
    for insight in draft.insights:
        citations = sorted(
            {
                allowed[normalized]
                for value in insight.citations
                if (normalized := _normalized_http_url(value)) in allowed
            }
        )
        summary = insight.summary.strip()
        if not summary or not citations or insight.axis in seen_axes:
            continue
        seen_axes.add(insight.axis)
        insights.append(
            insight.model_copy(
                update={
                    "summary": summary,
                    "why_it_matters": insight.why_it_matters.strip(),
                    "citations": citations,
                }
            )
        )

    if not sources or not insights:
        raise ValueError("company research contained no grounded insights")
    normalized_company = normalize_company(company)
    if not normalized_company:
        raise ValueError("company is required")
    return CompanyIntelligenceEvidence(
        normalized_company=normalized_company,
        display_company=company.strip(),
        overview=draft.overview.strip(),
        insights=insights,
        sources=sources,
        retrieved_at=retrieved_at,
        expires_at=expires_at,
        caveat=COMPANY_INTELLIGENCE_CAVEAT,
    )


def _research_prompt(company: str) -> str:
    return (
        f"Company: {company.strip()}\n"
        "Build a current, source-linked company dossier across the requested research axes."
    )


def _format_prompt(research: str) -> str:
    return f"Research:\n{research}"


def load_company_intelligence(
    session: Session, company: str | None
) -> CompanyIntelligenceEvidence | None:
    key = normalize_company(company)
    if not key:
        return None
    row = session.exec(
        select(CompanyIntelligenceEvidenceRow).where(
            CompanyIntelligenceEvidenceRow.normalized_company == key
        )
    ).first()
    if row is None:
        return None
    try:
        return CompanyIntelligenceEvidence.model_validate(row.evidence_json)
    except (TypeError, ValueError):
        return None


def generate_company_intelligence(
    session: Session,
    *,
    company: str,
    settings: Settings,
    research_agent,
    formatter,
    reporter=None,
    now: datetime | None = None,
) -> CompanyIntelligenceEvidenceRow:
    key = normalize_company(company)
    if not key:
        raise ValueError("company is required")
    research = str(research_agent.run(_research_prompt(company)).content)
    if reporter is not None:
        reporter.checkpoint()
    formatted = formatter.run(_format_prompt(research)).content
    if not isinstance(formatted, CompanyIntelligenceDraft):
        raise ValueError("company formatter did not return CompanyIntelligenceDraft")
    if reporter is not None:
        reporter.checkpoint()

    retrieved_at = now or utcnow()
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    evidence = _grounded_evidence(
        company=company,
        draft=formatted,
        research=research,
        retrieved_at=retrieved_at,
        expires_at=retrieved_at
        + timedelta(days=settings.company_intelligence_ttl_days),
    )
    with _WRITE_LOCK:
        row = session.exec(
            select(CompanyIntelligenceEvidenceRow).where(
                CompanyIntelligenceEvidenceRow.normalized_company == key
            )
        ).first()
        if row is None:
            row = CompanyIntelligenceEvidenceRow(normalized_company=key)
            session.add(row)
        row.display_company = company.strip()
        row.evidence_json = evidence.model_dump(mode="json")
        row.retrieved_at = evidence.retrieved_at
        row.expires_at = evidence.expires_at
        session.commit()
        session.refresh(row)
    return row
