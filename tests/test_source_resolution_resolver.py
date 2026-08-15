from resume_agent.discovery.source_resolution.models import (
    CrawlCandidate,
    CrawlReport,
    SourceEvidence,
)
from resume_agent.discovery.source_resolution.resolver import CompanySourceResolver
from resume_agent.services.sources import SourcePreview


def strong_report(company: str, url: str) -> CrawlReport:
    return CrawlReport(
        requested_url=url,
        first_party_verified=True,
        candidates=[
            CrawlCandidate(
                url=url,
                strong_first_party=True,
                evidence=[
                    SourceEvidence(
                        kind="first_party_link",
                        source_url=f"https://careers.{company.casefold().replace(' ', '')}.example",
                        target_url=url,
                        summary="Official careers page links to this board.",
                    )
                ],
            )
        ],
    )


def test_first_party_board_verifies_without_provider_identity():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        crawler=strong_report,
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True, url=url, kind="lever", token="acme", role_count=3
        ),
    )

    result = resolver.resolve("Acme", "https://jobs.lever.co/acme")

    assert result.status == "verified"
    assert result.reason_code == "VERIFIED_FIRST_PARTY"


def test_populated_board_with_another_provider_company_is_conflict():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        crawler=lambda company, url: CrawlReport(
            requested_url=url,
            candidates=[CrawlCandidate(url=url)],
        ),
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True,
            url=url,
            kind="workday",
            token="tempus",
            role_count=5,
            observed_companies=("Tempus AI",),
        ),
    )

    result = resolver.resolve(
        "Intuitive Surgical", "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers"
    )

    assert result.status == "conflict"
    assert result.reason_code == "ATS_CONFLICT"


def test_direct_live_board_without_first_party_or_provider_identity_is_unverified():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        crawler=lambda company, url: CrawlReport(
            requested_url=url,
            candidates=[CrawlCandidate(url=url)],
        ),
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True, url=url, kind="lever", token="tempus", role_count=2
        ),
    )

    result = resolver.resolve("Tempus", "https://jobs.lever.co/tempus")

    assert result.status == "unverified"
    assert result.reason_code == "OWNERSHIP_NOT_PROVEN"


def test_provider_conflict_beats_a_first_party_link():
    resolver = CompanySourceResolver(
        search_path="search.yaml",
        crawler=strong_report,
        previewer=lambda url, **kwargs: SourcePreview(
            ok=True,
            url=url,
            kind="lever",
            token="other",
            observed_companies=("Other Company",),
        ),
    )

    result = resolver.resolve("Acme", "https://jobs.lever.co/acme")

    assert result.status == "conflict"
