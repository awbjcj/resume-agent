"""Read-only access to saved company dossiers for Discovery Scout."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlmodel import Session

from resume_agent.company_intelligence.models import CompanyIntelligenceEvidence
from resume_agent.models.base import ExtensibleModel
from resume_agent.services.company_intelligence import load_company_intelligence_many
from resume_agent.taxonomy.industries import normalize_company

_TOOL_COMPANY_CAP = 8
_TOOL_INSIGHT_CAP = 5
_TOOL_CITATION_CAP = 4
_TOOL_SOURCE_CAP = 8
_TOOL_OVERVIEW_CHAR_CAP = 1_200
_TOOL_SUMMARY_CHAR_CAP = 700
_TOOL_WHY_CHAR_CAP = 500
_TOOL_CONFLICT_CHAR_CAP = 400
_TOOL_CAVEAT_CHAR_CAP = 400
_TOOL_SOURCE_TITLE_CHAR_CAP = 240
_TOOL_SOURCE_PUBLISHER_CHAR_CAP = 160
_TOOL_URL_CHAR_CAP = 2_048


@dataclass(frozen=True)
class _CompanyRequest:
    normalized_company: str
    display_company: str


def _company_requests(companies: list[str]) -> list[_CompanyRequest]:
    requested: list[_CompanyRequest] = []
    seen: set[str] = set()
    for company in companies[:_TOOL_COMPANY_CAP]:
        display = company.strip()[:200]
        key = normalize_company(display)
        if key and key not in seen:
            requested.append(_CompanyRequest(key, display))
            seen.add(key)
    return requested


def _clip(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[: limit - 1].rstrip() + "…", True


class ScoutCompanyIntelligenceSnapshot(ExtensibleModel):
    """Server-owned dossier state used by the Scout tool and proposal metadata."""

    status: Literal["ready", "stale", "missing"]
    normalized_company: str
    display_company: str
    version_number: int | None = None
    evidence: CompanyIntelligenceEvidence | None = None


class ScoutCompanyIntelligenceLookup:
    """Cache company-scoped dossier reads for one Scout turn."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(timezone.utc)
        if self._now.tzinfo is None:
            self._now = self._now.replace(tzinfo=timezone.utc)
        self._cache: dict[str, ScoutCompanyIntelligenceSnapshot] = {}

    def lookup_many(
        self, companies: list[str]
    ) -> dict[str, ScoutCompanyIntelligenceSnapshot]:
        requested = _company_requests(companies)

        uncached = [row for row in requested if row.normalized_company not in self._cache]
        if uncached:
            loaded = load_company_intelligence_many(
                self._session, [row.display_company for row in uncached]
            )
            for row in uncached:
                evidence = loaded.get(row.normalized_company)
                if evidence is None:
                    snapshot = ScoutCompanyIntelligenceSnapshot(
                        status="missing",
                        normalized_company=row.normalized_company,
                        display_company=row.display_company,
                    )
                else:
                    expires_at = evidence.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    snapshot = ScoutCompanyIntelligenceSnapshot(
                        status="ready" if expires_at > self._now else "stale",
                        normalized_company=row.normalized_company,
                        display_company=evidence.display_company,
                        version_number=evidence.version_number,
                        evidence=evidence,
                    )
                self._cache[row.normalized_company] = snapshot
        return {
            row.normalized_company: self._cache[row.normalized_company]
            for row in requested
        }

    def get_saved_company_intelligence(self, companies: list[str]) -> str:
        """Read saved company research without refreshing it.

        Args:
            companies: Up to eight exact company names to look up together.
        """

        requested = _company_requests(companies)
        snapshots = self.lookup_many([row.display_company for row in requested])
        rows: list[dict] = []
        for request in requested:
            snapshot = snapshots.get(request.normalized_company)
            if snapshot is None or snapshot.evidence is None:
                rows.append(
                    {
                        "status": "missing",
                        "normalizedCompany": request.normalized_company,
                        "displayCompany": request.display_company,
                    }
                )
                continue
            evidence = snapshot.evidence
            clipped_fields: list[str] = []
            overview, overview_clipped = _clip(
                evidence.overview, _TOOL_OVERVIEW_CHAR_CAP
            )
            caveat, caveat_clipped = _clip(evidence.caveat, _TOOL_CAVEAT_CHAR_CAP)
            if overview_clipped:
                clipped_fields.append("overview")
            if caveat_clipped:
                clipped_fields.append("caveat")

            insight_rows: list[dict] = []
            cited_urls: list[str] = []
            for index, insight in enumerate(evidence.insights[:_TOOL_INSIGHT_CAP]):
                summary, summary_clipped = _clip(
                    insight.summary, _TOOL_SUMMARY_CHAR_CAP
                )
                why_it_matters, why_clipped = _clip(
                    insight.why_it_matters, _TOOL_WHY_CHAR_CAP
                )
                conflicting_evidence, conflict_clipped = _clip(
                    insight.conflicting_evidence, _TOOL_CONFLICT_CHAR_CAP
                )
                if summary_clipped:
                    clipped_fields.append(f"insights[{index}].summary")
                if why_clipped:
                    clipped_fields.append(f"insights[{index}].whyItMatters")
                if conflict_clipped:
                    clipped_fields.append(
                        f"insights[{index}].conflictingEvidence"
                    )
                raw_citations = insight.citations[:_TOOL_CITATION_CAP]
                citations = [
                    url for url in raw_citations if len(url) <= _TOOL_URL_CHAR_CAP
                ]
                if len(raw_citations) < len(insight.citations) or len(
                    citations
                ) < len(raw_citations):
                    clipped_fields.append(f"insights[{index}].citations")
                cited_urls.extend(url for url in citations if url not in cited_urls)
                insight_rows.append(
                    {
                        "axis": insight.axis,
                        "summary": summary,
                        "whyItMatters": why_it_matters,
                        "citations": citations,
                        "verificationState": insight.verification_state,
                        "asOf": insight.as_of.isoformat() if insight.as_of else None,
                        "conflictingEvidence": conflicting_evidence,
                    }
                )

            source_by_url = {source.url: source for source in evidence.sources}
            selected_source_urls = [
                url for url in cited_urls if url in source_by_url
            ][:_TOOL_SOURCE_CAP]
            source_rows: list[dict] = []
            for index, url in enumerate(selected_source_urls):
                source = source_by_url[url]
                title, title_clipped = _clip(
                    source.title, _TOOL_SOURCE_TITLE_CHAR_CAP
                )
                publisher, publisher_clipped = _clip(
                    source.publisher, _TOOL_SOURCE_PUBLISHER_CHAR_CAP
                )
                if title_clipped:
                    clipped_fields.append(f"sources[{index}].title")
                if publisher_clipped:
                    clipped_fields.append(f"sources[{index}].publisher")
                source_rows.append(
                    {
                        "title": title,
                        "url": source.url,
                        "publisher": publisher,
                        "sourceType": source.source_type,
                        "sourceTier": source.source_tier,
                        "publishedAt": (
                            source.published_at.isoformat()
                            if source.published_at
                            else None
                        ),
                        "lastVerifiedAt": (
                            source.last_verified_at.isoformat()
                            if source.last_verified_at
                            else None
                        ),
                    }
                )
            omitted_sources = len(
                {url for url in cited_urls if url in source_by_url}
            ) - len(selected_source_urls)
            omitted_insights = max(0, len(evidence.insights) - len(insight_rows))
            was_truncated = bool(
                clipped_fields or omitted_insights or omitted_sources
            )
            rows.append(
                {
                    "status": snapshot.status,
                    "normalizedCompany": snapshot.normalized_company,
                    "displayCompany": snapshot.display_company,
                    "versionNumber": snapshot.version_number,
                    "retrievedAt": evidence.retrieved_at.isoformat(),
                    "expiresAt": evidence.expires_at.isoformat(),
                    "overview": overview,
                    "insights": insight_rows,
                    "sources": source_rows,
                    "caveat": caveat,
                    "truncation": {
                        "applied": was_truncated,
                        "omittedInsights": omitted_insights,
                        "omittedSources": omitted_sources,
                        "clippedFields": clipped_fields,
                    },
                }
            )
        return json.dumps({"companies": rows}, ensure_ascii=False, separators=(",", ":"))
