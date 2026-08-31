from resume_tailor_harness.public_sources import (
    PublicSourceIndex,
    normalize_http_url,
    retain_frozen_citations,
)


def test_public_source_index_preserves_exact_transcript_urls_and_deduplicates():
    index = PublicSourceIndex.from_text(
        "Evidence HTTPS://Acme.Example/report?q=1#section, "
        "then https://acme.example/report?q=1 and https://other.example/item."
    )

    assert index.resolve("https://ACME.example/report?q=1#different") == (
        "HTTPS://Acme.Example/report?q=1#section"
    )
    assert index.retain(
        [
            "https://other.example/item",
            "https://acme.example/report?q=1",
            "https://acme.example/report?q=1",
        ]
    ) == [
        "HTTPS://Acme.Example/report?q=1#section",
        "https://other.example/item",
    ]


def test_public_source_index_rejects_invalid_and_non_http_urls():
    assert normalize_http_url("ftp://acme.example/report") is None
    assert normalize_http_url("https:///missing-host") is None
    assert normalize_http_url("https://[broken") is None
    assert PublicSourceIndex.from_text("mailto:test@example.com").retain(
        ["mailto:test@example.com"]
    ) == []


def test_public_source_authorities_collapse_subdomains():
    assert PublicSourceIndex.authorities(
        [
            "https://www.acme.com/report",
            "https://investors.acme.com/filing",
            "https://analysis.org/acme",
        ]
    ) == {"acme.com", "analysis.org"}


def test_frozen_citations_require_exact_snapshot_urls():
    allowed = ["HTTPS://Acme.Example/report#section"]

    assert retain_frozen_citations(allowed, allowed) == allowed
    assert retain_frozen_citations(["https://acme.example/report"], allowed) == []
