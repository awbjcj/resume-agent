"""Generate, validate, cache, and load company-intelligence evidence."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, col, select

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceAxis,
    CompanyIntelligenceChangeSet,
    CompanyIntelligenceDraft,
    CompanyIntelligenceEvidence,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
    CompanyResearchDepth,
)
from resume_agent.config import Settings
from resume_agent.discovery.source_resolution.identity import registrable_domain
from resume_agent.taxonomy.industries import normalize_company
from resume_agent.tracking.tables import (
    CompanyIntelligenceEvidenceRow,
    CompanyIntelligenceVersionRow,
    utcnow,
)

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
    research_depth: CompanyResearchDepth = "standard",
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
        source_tier = source.source_tier
        if source_tier == "other" and source.source_type == "official":
            source_tier = "company_official"
        sources.append(
            source.model_copy(
                update={
                    "url": grounded_urls[normalized],
                    "source_tier": source_tier,
                    "last_verified_at": retrieved_at,
                }
            )
        )

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
        authorities = {
            registrable_domain(value)
            for value in citations
            if registrable_domain(value)
        }
        verification_state = (
            "inferred"
            if insight.verification_state == "inferred"
            else "corroborated"
            if len(authorities) >= 2
            else "single_source"
        )
        seen_axes.add(insight.axis)
        insights.append(
            insight.model_copy(
                update={
                    "summary": summary,
                    "why_it_matters": insight.why_it_matters.strip(),
                    "citations": citations,
                    "verification_state": verification_state,
                    "conflicting_evidence": insight.conflicting_evidence.strip(),
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
        research_depth=research_depth,
    )


def _research_prompt(company: str, depth: CompanyResearchDepth) -> str:
    return (
        f"Company: {company.strip()}\n"
        f"Research depth: {depth}\n"
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


def load_company_intelligence_history(
    session: Session, company: str | None, *, limit: int = 10
) -> list[CompanyIntelligenceEvidence]:
    key = normalize_company(company)
    if not key:
        return []
    rows = session.exec(
        select(CompanyIntelligenceVersionRow)
        .where(CompanyIntelligenceVersionRow.normalized_company == key)
        .order_by(col(CompanyIntelligenceVersionRow.version_number).desc())
        .limit(max(1, min(limit, 50)))
    ).all()
    evidence: list[CompanyIntelligenceEvidence] = []
    for row in rows:
        try:
            evidence.append(CompanyIntelligenceEvidence.model_validate(row.evidence_json))
        except (TypeError, ValueError):
            continue
    if evidence:
        return evidence
    current = load_company_intelligence(session, company)
    return [current] if current is not None else []


def _changes_between(
    previous: CompanyIntelligenceEvidence | None,
    current: CompanyIntelligenceEvidence,
) -> CompanyIntelligenceChangeSet:
    current_by_axis: dict[CompanyIntelligenceAxis, CompanyIntelligenceInsight] = {
        item.axis: item for item in current.insights
    }
    previous_by_axis: dict[CompanyIntelligenceAxis, CompanyIntelligenceInsight] = (
        {item.axis: item for item in previous.insights} if previous is not None else {}
    )
    current_axes: set[CompanyIntelligenceAxis] = set(current_by_axis)
    previous_axes: set[CompanyIntelligenceAxis] = set(previous_by_axis)

    def comparable(insight: CompanyIntelligenceInsight) -> dict:
        return insight.model_dump(
            mode="json",
            exclude={"schema_version"},
        )

    changed: list[CompanyIntelligenceAxis] = sorted(
        axis
        for axis in current_axes & previous_axes
        if comparable(current_by_axis[axis]) != comparable(previous_by_axis[axis])
    )
    current_sources = {source.url for source in current.sources}
    previous_sources = (
        {source.url for source in previous.sources} if previous is not None else set()
    )
    return CompanyIntelligenceChangeSet(
        added_axes=sorted(current_axes - previous_axes),
        removed_axes=sorted(previous_axes - current_axes),
        changed_axes=changed,
        added_source_urls=sorted(current_sources - previous_sources),
        removed_source_urls=sorted(previous_sources - current_sources),
    )


def _append_version(
    session: Session,
    *,
    evidence: CompanyIntelligenceEvidence,
    previous: CompanyIntelligenceEvidence | None,
    version_number: int,
    previous_version_id: int | None,
) -> tuple[CompanyIntelligenceVersionRow, CompanyIntelligenceEvidence]:
    changes = _changes_between(previous, evidence)
    row = CompanyIntelligenceVersionRow(
        normalized_company=evidence.normalized_company,
        display_company=evidence.display_company,
        version_number=version_number,
        previous_version_id=previous_version_id,
        research_depth=evidence.research_depth,
        evidence_json={},
        change_json=changes.model_dump(mode="json"),
        retrieved_at=evidence.retrieved_at,
        expires_at=evidence.expires_at,
    )
    session.add(row)
    session.flush()
    stored = evidence.model_copy(
        update={
            "version_id": row.id,
            "version_number": version_number,
            "previous_version_id": previous_version_id,
            "changes": changes,
        }
    )
    row.evidence_json = stored.model_dump(mode="json")
    session.add(row)
    return row, stored


def generate_company_intelligence(
    session: Session,
    *,
    company: str,
    settings: Settings,
    research_agent,
    formatter,
    reporter=None,
    now: datetime | None = None,
    research_depth: CompanyResearchDepth = "standard",
) -> CompanyIntelligenceEvidenceRow:
    key = normalize_company(company)
    if not key:
        raise ValueError("company is required")
    research = str(research_agent.run(_research_prompt(company, research_depth)).content)
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
        research_depth=research_depth,
    )
    with _WRITE_LOCK:
        current_row = session.exec(
            select(CompanyIntelligenceEvidenceRow).where(
                CompanyIntelligenceEvidenceRow.normalized_company == key
            )
        ).first()
        previous = None
        if current_row is not None:
            try:
                previous = CompanyIntelligenceEvidence.model_validate(
                    current_row.evidence_json
                )
            except (TypeError, ValueError):
                previous = None
        latest_version = session.exec(
            select(CompanyIntelligenceVersionRow)
            .where(CompanyIntelligenceVersionRow.normalized_company == key)
            .order_by(col(CompanyIntelligenceVersionRow.version_number).desc())
        ).first()
        if latest_version is None and previous is not None:
            latest_version, previous = _append_version(
                session,
                evidence=previous,
                previous=None,
                version_number=1,
                previous_version_id=None,
            )
            assert current_row is not None
            current_row.evidence_json = previous.model_dump(mode="json")
            current_row.schema_version = 2
            session.add(current_row)

        version_number = (latest_version.version_number + 1) if latest_version else 1
        previous_version_id = latest_version.id if latest_version else None
        _version_row, evidence = _append_version(
            session,
            evidence=evidence,
            previous=previous,
            version_number=version_number,
            previous_version_id=previous_version_id,
        )

        row = current_row
        if row is None:
            row = CompanyIntelligenceEvidenceRow(
                normalized_company=key,
                expires_at=evidence.expires_at,
            )
            session.add(row)
        row.display_company = company.strip()
        row.evidence_json = evidence.model_dump(mode="json")
        row.retrieved_at = evidence.retrieved_at
        row.expires_at = evidence.expires_at
        row.schema_version = 2
        session.commit()
        session.refresh(row)
    return row
