"""Bounded, first-party-only careers-page discovery for Scout."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from resume_agent.discovery.connectors.detect import identify_host, targets_from_html
from resume_agent.discovery.source_resolution.catalog import canonical_target_url
from resume_agent.discovery.source_resolution.identity import (
    page_matches_company,
    registrable_domain,
)
from resume_agent.discovery.source_resolution.models import (
    CrawlCandidate,
    CrawlReport,
    SourceEvidence,
)
from resume_agent.security.outbound import (
    PublicTextResponse,
    fetch_public_text,
    validate_public_url,
)


MAX_FIRST_PARTY_PAGES = 5
MAX_ATS_CANDIDATES = 5
MAX_PAGE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 15.0
RESOLUTION_DEADLINE_SECONDS = 45.0
_CAREER_WORDS = ("career", "job", "join", "position", "opportunit", "vacanc")


class FirstPartyCrawler:
    """Discover ATS candidates without promoting arbitrary web pages to proof."""

    def __init__(
        self,
        fetcher: Callable[[str], PublicTextResponse] | None = None,
        *,
        validator: Callable[[str], None] = validate_public_url,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetcher or self._fetch_page
        self._validate = validator
        self._clock = clock

    @staticmethod
    def _fetch_page(url: str) -> PublicTextResponse:
        return fetch_public_text(
            url,
            max_bytes=MAX_PAGE_BYTES,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def crawl(self, company: str, candidate_url: str) -> CrawlReport:
        requested = candidate_url.strip()
        try:
            self._validate(requested)
        except ValueError:
            return CrawlReport(requested_url=requested, error_code="UNSAFE_URL")
        if target := identify_host(requested):
            canonical = canonical_target_url(target)
            if canonical:
                return CrawlReport(
                    requested_url=requested,
                    candidates=[
                        CrawlCandidate(
                            url=canonical,
                            evidence=[
                                SourceEvidence(
                                    kind="search_result",
                                    source_url=requested,
                                    target_url=canonical,
                                    summary="ATS candidate found by web research.",
                                )
                            ],
                        )
                    ],
                )
        return self._crawl_first_party(company, requested)

    def _crawl_first_party(self, company: str, requested_url: str) -> CrawlReport:
        deadline = self._clock() + RESOLUTION_DEADLINE_SECONDS
        queue = deque([requested_url])
        visited: set[str] = set()
        candidates: dict[str, CrawlCandidate] = {}
        evidence: list[SourceEvidence] = []
        first_party_domain = ""
        final_url = ""
        first_party_verified = False
        while queue and len(visited) < MAX_FIRST_PARTY_PAGES:
            if self._clock() >= deadline:
                return CrawlReport(
                    requested_url=requested_url,
                    final_first_party_url=final_url,
                    first_party_verified=first_party_verified,
                    candidates=list(candidates.values()),
                    evidence=evidence,
                    error_code="RESOLUTION_TIMEOUT",
                )
            url = queue.popleft()
            if url in visited:
                continue
            try:
                self._validate(url)
                page = self._fetch(url)
            except (httpx.HTTPError, OSError, ValueError):
                continue
            visited.add(url)
            final_url = final_url or page.final_url
            domain = registrable_domain(page.final_url)
            if not first_party_domain:
                first_party_domain = domain
            if domain != first_party_domain:
                self._add_redirect_candidate(candidates, url, page.final_url)
                continue
            strong = page_matches_company(company, page.final_url, page.text)
            first_party_verified = first_party_verified or strong
            if strong:
                evidence.append(
                    SourceEvidence(
                        kind="first_party_identity",
                        source_url=page.final_url,
                        summary="Company identity matched first-party careers metadata.",
                    )
                )
            self._add_candidates(candidates, page.final_url, page.text, strong)
            if not strong:
                continue
            for link in self._career_links(page.final_url, page.text):
                if registrable_domain(link) == first_party_domain and link not in visited:
                    queue.append(link)
        if candidates:
            return CrawlReport(
                requested_url=requested_url,
                final_first_party_url=final_url,
                first_party_verified=first_party_verified,
                candidates=list(candidates.values()),
                evidence=evidence,
            )
        return CrawlReport(
            requested_url=requested_url,
            final_first_party_url=final_url,
            first_party_verified=first_party_verified,
            evidence=evidence,
            error_code="ATS_NOT_FOUND" if final_url else "OFFICIAL_SITE_UNREACHABLE",
        )

    @staticmethod
    def _career_links(base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for selector, attr in (
            ("a[href]", "href"),
            ("iframe[src]", "src"),
            ("script[src]", "src"),
            ("form[action]", "action"),
        ):
            for tag in soup.select(selector):
                href = str(tag.get(attr) or "")
                text = tag.get_text(" ", strip=True)
                if not any(word in f"{href} {text}".casefold() for word in _CAREER_WORDS):
                    continue
                url = urljoin(base_url, href)
                parsed = urlsplit(url)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    links.append(url)
        return list(dict.fromkeys(links))

    @staticmethod
    def _add_redirect_candidate(
        candidates: dict[str, CrawlCandidate], source_url: str, redirected_url: str
    ) -> None:
        """A same-domain link that redirects off-domain to a supported ATS board
        is itself strong first-party proof (design: "a link or redirect from the
        company's first-party site to the exact canonical ATS board")."""
        if len(candidates) >= MAX_ATS_CANDIDATES:
            return
        target = identify_host(redirected_url)
        if target is None:
            return
        canonical = canonical_target_url(target)
        if not canonical or canonical in candidates:
            return
        candidates[canonical] = CrawlCandidate(
            url=canonical,
            strong_first_party=True,
            evidence=[
                SourceEvidence(
                    kind="first_party_redirect",
                    source_url=source_url,
                    target_url=canonical,
                    summary="First-party page redirected to this ATS board.",
                )
            ],
        )

    @staticmethod
    def _add_candidates(
        candidates: dict[str, CrawlCandidate],
        source_url: str,
        html: str,
        strong: bool,
    ) -> None:
        kind = "first_party_embed" if strong else "search_result"
        summary = (
            "First-party careers page embeds this ATS board."
            if strong
            else "ATS board appeared on a page without company proof."
        )
        for target in targets_from_html(html):
            canonical = canonical_target_url(target)
            if not canonical or canonical in candidates:
                continue
            if len(candidates) >= MAX_ATS_CANDIDATES:
                return
            candidates[canonical] = CrawlCandidate(
                url=canonical,
                strong_first_party=strong,
                evidence=[
                    SourceEvidence(
                        kind=kind,
                        source_url=source_url,
                        target_url=canonical,
                        summary=summary,
                    )
                ],
            )
