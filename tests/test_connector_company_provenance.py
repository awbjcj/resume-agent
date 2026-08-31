from resume_tailor_harness.discovery.connectors.breezy import apply_detail as apply_breezy_detail
from resume_tailor_harness.discovery.connectors.breezy import parse_breezy
from resume_tailor_harness.discovery.connectors.recruitee import parse_recruitee
from resume_tailor_harness.discovery.connectors.workable import parse_workable


def test_provider_owned_company_fields_are_distinguished_from_board_tokens():
    workable = parse_workable(
        {"name": "Acme Corporation", "jobs": [{"title": "Engineer"}]}, "acme"
    )[0]
    recruitee = parse_recruitee(
        {"offers": [{"company_name": "Acme Corporation", "title": "Engineer"}]}, "acme"
    )[0]
    breezy = parse_breezy(
        [{"company": {"name": "Acme Corporation"}, "name": "Engineer"}], "acme"
    )[0]

    assert [row.company_provenance for row in (workable, recruitee, breezy)] == [
        "provider",
        "provider",
        "provider",
    ]


def test_detail_metadata_can_upgrade_token_provenance_to_provider_identity():
    row = parse_breezy([{"name": "Engineer"}], "acme")[0]

    apply_breezy_detail(
        row,
        {
            "html": """
              <script type="application/ld+json">{
                "@type":"JobPosting", "title":"Engineer", "description":"Work",
                "hiringOrganization":{"name":"Acme Corporation"}
              }</script>
            """
        },
    )

    assert row.company == "Acme Corporation"
    assert row.company_provenance == "provider"
