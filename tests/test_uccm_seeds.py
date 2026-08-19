from resume_agent.taxonomy.uccm_seeds import (
    CAREER_LAYERS,
    UCCM_SOURCE,
    uccm_seed_nodes,
)


def test_uccm_seed_catalog_has_six_layers_eight_core_and_twelve_functions():
    nodes = uccm_seed_nodes()
    core = [node for node in nodes if node.career_layers == ["career_core"]]
    functions = [
        node for node in nodes if node.career_layers == ["transferable_function"]
    ]
    assert [layer.id for layer in CAREER_LAYERS] == [
        "career_core",
        "foundational",
        "transferable_function",
        "domain_industry",
        "occupation_role",
        "enabler",
    ]
    assert len(core) == 8
    assert len(functions) == 12
    assert len(nodes) == len({node.id for node in nodes}) == 20


def test_governed_projection_families_are_not_candidate_claims():
    for node in uccm_seed_nodes():
        assert node.type_assignment_status == "governed"
        assert node.claim_policy == "never_candidate_claim"
        assert node.source_refs == [UCCM_SOURCE.id]


def test_seed_labels_and_ids_are_product_owned_and_stable():
    by_id = {node.id: node.preferred_label for node in uccm_seed_nodes()}
    assert by_id["internal:competency-family:reasoning-judgment-problem-solving"] == (
        "Reasoning, Judgment, and Problem Solving"
    )
    assert by_id["internal:work-function:monitor-assure"] == "Monitor and Assure"
