"""Taxonomy edit use-cases write complete durable intents atomically."""

import pytest

import resume_tailor_harness.services.taxonomy as service
from resume_tailor_harness.services.taxonomy import (
    AliasCycleError,
    DomainMergeCycleError,
    NewDomainSpec,
    UnknownCategoryError,
    UnknownDomainError,
    UnknownSkillError,
    add_skill,
    add_skill_alias,
    merge_domains,
    move_skill,
    patch_domain,
    remove_skill,
)
from resume_tailor_harness.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_tailor_harness.taxonomy.corrections import load_taxonomy_corrections


def _paths(tmp_path):
    corrections_path = tmp_path / "taxonomy_corrections.json"
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"react": "react", "javascript": "javascript", "js": "javascript"},
            domain_of={"react": "web", "javascript": "languages"},
            domain_label={"web": "Web", "languages": "Languages"},
            category_of={"web": "frontend-web", "languages": "languages"},
        ),
        cluster_path,
    )
    return corrections_path, cluster_path


def test_new_domain_writes_all_three_intents_in_one_transaction(tmp_path, monkeypatch):
    corrections_path, cluster_path = _paths(tmp_path)
    writes = 0
    real_update = service.update_taxonomy_corrections

    def tracked_update(*args, **kwargs):
        nonlocal writes
        writes += 1
        return real_update(*args, **kwargs)

    monkeypatch.setattr(service, "update_taxonomy_corrections", tracked_update)
    move_skill(
        corrections_path,
        cluster_path,
        "react",
        new_domain=NewDomainSpec("UI Toolkits", "frontend-web"),
    )

    ledger = load_taxonomy_corrections(corrections_path)
    assert writes == 1
    assert ledger.skill_domain == {"react": "ui-toolkits"}
    assert ledger.domain_renames == {"ui-toolkits": "UI Toolkits"}
    assert ledger.domain_category == {"ui-toolkits": "frontend-web"}


def test_new_domain_id_avoids_existing_collision(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    move_skill(
        corrections_path,
        cluster_path,
        "react",
        new_domain=NewDomainSpec("Web", "frontend-web"),
    )
    assert load_taxonomy_corrections(corrections_path).skill_domain["react"] == "web-2"


def test_move_requires_exactly_one_valid_target(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        move_skill(corrections_path, cluster_path, "react")
    with pytest.raises(UnknownDomainError):
        move_skill(corrections_path, cluster_path, "react", domain_id="ghost")
    with pytest.raises(UnknownCategoryError):
        move_skill(
            corrections_path,
            cluster_path,
            "react",
            new_domain=NewDomainSpec("X", "ghost"),
        )


def test_add_and_remove_each_persist_once_and_readd_clears_removal(
    tmp_path, monkeypatch
):
    corrections_path, cluster_path = _paths(tmp_path)
    writes = 0
    real_update = service.update_taxonomy_corrections

    def tracked_update(*args, **kwargs):
        nonlocal writes
        writes += 1
        return real_update(*args, **kwargs)

    monkeypatch.setattr(service, "update_taxonomy_corrections", tracked_update)
    add_skill(corrections_path, cluster_path, "GraphQL", domain_id="web")
    remove_skill(corrections_path, "GraphQL")
    add_skill(corrections_path, cluster_path, "GraphQL", domain_id="web")

    ledger = load_taxonomy_corrections(corrections_path)
    assert writes == 3
    assert ledger.added_skills == ["graphql"]
    assert ledger.removed_skills == []
    assert ledger.skill_domain == {"graphql": "web"}


def test_compound_patch_validates_before_single_write(tmp_path, monkeypatch):
    corrections_path, cluster_path = _paths(tmp_path)
    writes = 0
    real_update = service.update_taxonomy_corrections

    def tracked_update(*args, **kwargs):
        nonlocal writes
        writes += 1
        return real_update(*args, **kwargs)

    monkeypatch.setattr(service, "update_taxonomy_corrections", tracked_update)
    with pytest.raises(UnknownCategoryError):
        patch_domain(
            corrections_path,
            cluster_path,
            "web",
            label="Frontend Frameworks",
            category="ghost",
        )
    assert writes == 1
    assert load_taxonomy_corrections(corrections_path).domain_renames == {}

    patch_domain(
        corrections_path,
        cluster_path,
        "web",
        label="Frontend Frameworks",
        category="tools-platforms",
    )
    ledger = load_taxonomy_corrections(corrections_path)
    assert writes == 2
    assert ledger.domain_renames["web"] == "Frontend Frameworks"
    assert ledger.domain_category["web"] == "tools-platforms"


def test_merge_rejects_unknown_self_and_cycle(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    with pytest.raises(UnknownDomainError):
        merge_domains(corrections_path, cluster_path, "ghost", "web")
    with pytest.raises(DomainMergeCycleError):
        merge_domains(corrections_path, cluster_path, "web", "web")
    merge_domains(corrections_path, cluster_path, "web", "languages")
    with pytest.raises(DomainMergeCycleError):
        merge_domains(corrections_path, cluster_path, "languages", "web")


def test_alias_requires_two_known_skills_and_rejects_cycles(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    with pytest.raises(UnknownSkillError):
        add_skill_alias(corrections_path, cluster_path, "ghost", "react")
    with pytest.raises(UnknownSkillError):
        add_skill_alias(corrections_path, cluster_path, "react", "ghost")
    add_skill_alias(corrections_path, cluster_path, "js", "javascript")
    with pytest.raises(AliasCycleError):
        add_skill_alias(corrections_path, cluster_path, "javascript", "js")


def test_move_accepts_demanded_but_unclustered_skill(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    # "rust" is demanded (shown in the graph) but not yet in the cluster map.
    with pytest.raises(UnknownSkillError):
        move_skill(corrections_path, cluster_path, "rust", domain_id="web")
    move_skill(
        corrections_path,
        cluster_path,
        "rust",
        domain_id="web",
        known_tokens={"rust"},
    )
    assert load_taxonomy_corrections(corrections_path).skill_domain["rust"] == "web"


def test_alias_accepts_demanded_but_unclustered_skills(tmp_path):
    corrections_path, cluster_path = _paths(tmp_path)
    add_skill_alias(
        corrections_path,
        cluster_path,
        "rustlang",
        "rust",
        known_tokens={"rust", "rustlang"},
    )
    assert load_taxonomy_corrections(corrections_path).aliases["rustlang"] == "rust"
