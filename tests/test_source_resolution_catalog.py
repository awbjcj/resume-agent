from resume_agent.discovery.connectors.detect import AtsTarget, identify_host, targets_from_html
from resume_agent.discovery.connectors.registry import discoverable_board_families
from resume_agent.discovery.source_resolution.catalog import (
    BOARD_FAMILIES,
    canonical_target_url,
    render_supported_board_guidance,
    targeted_ats_query_templates,
)


EXPECTED = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "smartrecruiters",
    "workable",
    "recruitee",
    "personio",
    "breezy",
    "jazzhr",
    "bamboohr",
}


def test_every_supported_ats_is_registered_detectable_and_searchable():
    assert {family.kind for family in BOARD_FAMILIES} == EXPECTED
    assert {family.kind for family in discoverable_board_families()} == EXPECTED
    for family in BOARD_FAMILIES:
        target = identify_host(family.sample_url)
        assert target is not None and target.ats == family.kind
        assert canonical_target_url(target)


def test_generated_guidance_and_three_queries_cover_every_supported_host_once():
    guidance = render_supported_board_guidance(max_search_uses=5)
    assert "five web searches" in guidance
    templates = targeted_ats_query_templates()
    assert len(templates) == 3
    expected = sorted(host for family in BOARD_FAMILIES for host in family.search_hosts)
    actual = sorted(
        token.removeprefix("site:")
        for template in templates
        for token in template.split()
        if token.startswith("site:")
    )
    assert actual == expected
    for host in expected:
        assert host in guidance


def test_smartrecruiters_posting_canonicalizes_to_public_careers_board():
    target = AtsTarget("smartrecruiters", "Intuitive")
    assert canonical_target_url(target) == "https://careers.smartrecruiters.com/Intuitive"


def test_html_extraction_returns_every_supported_target_not_only_the_first_marker():
    html = "\n".join(
        f'<script>const board = "{family.sample_url}";</script>'
        for family in BOARD_FAMILIES
    )
    assert {target.ats for target in targets_from_html(html)} == EXPECTED
