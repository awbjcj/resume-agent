"""Ownership-aware final verdicts for Scout ATS candidates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from resume_agent.discovery.source_resolution.crawler import FirstPartyCrawler
from resume_agent.discovery.source_resolution.identity import (
    company_names_match,
    normalize_company_name,
)
from resume_agent.discovery.source_resolution.models import (
    CompanySourceResolution,
    CrawlCandidate,
    CrawlReport,
    SourceEvidence,
)
from resume_agent.services.sources import SourcePreview, board_root_url, preview_source


def resolution_cache_key(company: str, url: str) -> tuple[str, str]:
    return normalize_company_name(company), board_root_url(url.strip())


class CompanySourceResolverLike(Protocol):
    """Structural interface used by Scout orchestration and test doubles."""

    def resolve(self, company: str, candidate_url: str) -> CompanySourceResolution: ...


class CompanySourceResolver:
    """Resolve a source candidate without trusting model confidence or reachability."""

    def __init__(
        self,
        search_path: str,
        *,
        crawler: Callable[[str, str], CrawlReport] | None = None,
        previewer: Callable[..., SourcePreview] = preview_source,
    ) -> None:
        self.search_path = search_path
        self._crawler = crawler or FirstPartyCrawler().crawl
        self._preview = previewer

    def resolve(self, company: str, candidate_url: str) -> CompanySourceResolution:
        report = self._crawler(company, candidate_url)
        inspected = [self._inspect(company, candidate_url, candidate) for candidate in report.candidates]
        for status in ("verified", "unverified", "conflict", "failed"):
            if result := next((row for row in inspected if row.status == status), None):
                return result
        if report.first_party_verified:
            return CompanySourceResolution(
                company=company,
                requested_url=candidate_url,
                canonical_board_url=report.final_first_party_url or candidate_url,
                status="unverified",
                reason_code="ATS_NOT_FOUND",
                evidence=report.evidence,
            )
        return CompanySourceResolution(
            company=company,
            requested_url=candidate_url,
            status="failed",
            reason_code=report.error_code or "ATS_NOT_FOUND",
            evidence=report.evidence,
        )

    def _inspect(
        self, company: str, requested_url: str, candidate: CrawlCandidate
    ) -> CompanySourceResolution:
        try:
            preview = self._preview(
                candidate.url,
                search_path=self.search_path,
                limit=5,
                browser=False,
            )
        except Exception:  # noqa: BLE001 - an individual candidate must not abort its siblings.
            return CompanySourceResolution(
                company=company,
                requested_url=requested_url,
                canonical_board_url=candidate.url,
                status="failed",
                reason_code="OFFICIAL_SITE_UNREACHABLE",
                evidence=candidate.evidence,
            )
        canonical = board_root_url(preview.url or candidate.url)
        base = {
            "company": company,
            "requested_url": requested_url,
            "canonical_board_url": canonical,
            "ats": preview.kind,
            "token": preview.token,
            "role_count": preview.role_count,
            "evidence": [*candidate.evidence],
        }
        if not preview.ok:
            return CompanySourceResolution(
                **base,
                status="failed",
                reason_code="OFFICIAL_SITE_UNREACHABLE",
            )
        observed = tuple(name for name in preview.observed_companies if name.strip())
        matched = tuple(name for name in observed if company_names_match(company, name))
        provider_evidence = [
            SourceEvidence(
                kind="provider_company" if name in matched else "provider_conflict",
                source_url=canonical,
                summary=f"Provider metadata identifies the board as {name}.",
            )
            for name in observed
        ]
        if observed and not matched:
            return CompanySourceResolution(
                **{**base, "evidence": [*base["evidence"], *provider_evidence]},
                status="conflict",
                reason_code="ATS_CONFLICT",
            )
        if matched:
            return CompanySourceResolution(
                **{**base, "evidence": [*base["evidence"], *provider_evidence]},
                status="verified",
                reason_code="VERIFIED_PROVIDER_METADATA",
            )
        if candidate.strong_first_party:
            return CompanySourceResolution(
                **base,
                status="verified",
                reason_code="VERIFIED_FIRST_PARTY",
            )
        return CompanySourceResolution(
            **base,
            status="unverified",
            reason_code="OWNERSHIP_NOT_PROVEN",
        )
