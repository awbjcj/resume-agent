from resume_agent.discovery.source_resolution.identity import (
    company_claims_from_html,
    company_names_match,
    page_matches_company,
    registrable_domain,
)


def test_company_matching_is_conservative_about_similarly_named_companies():
    assert company_names_match("Intuitive Surgical, Inc.", "Intuitive")
    assert company_names_match("Tempus AI, Inc.", "Tempus AI")
    assert not company_names_match("Intuitive Surgical", "Intuitive Machines")
    assert not company_names_match("Acme Healthcare", "Acme Manufacturing")


def test_registrable_domain_handles_subdomains_and_public_suffixes_offline():
    assert registrable_domain("https://careers.intuitive.com/en/") == "intuitive.com"
    assert registrable_domain("https://jobs.acme.co.uk/openings") == "acme.co.uk"


def test_page_claims_and_company_match_read_only_identity_metadata():
    html = """
    <html><head>
      <title>Careers at Intuitive</title>
      <meta property="og:site_name" content="Intuitive Surgical Careers">
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Organization","name":"Intuitive Surgical","alternateName":"Intuitive"}
      </script>
    </head></html>
    """
    assert company_claims_from_html(html) == (
        "Careers at Intuitive",
        "Intuitive",
        "Intuitive Surgical",
        "Intuitive Surgical Careers",
    )
    assert page_matches_company("Intuitive Surgical", "https://careers.intuitive.com/en/", html)
    assert not page_matches_company("Intuitive Machines", "https://careers.intuitive.com/en/", html)
