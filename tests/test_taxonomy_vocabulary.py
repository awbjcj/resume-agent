"""Fixed category vocabulary invariants."""

from resume_agent.taxonomy.vocabulary import (
    LEGACY_GROUP_REMAP,
    SKILL_GROUPS,
    SOFT_CATEGORY_SLUGS,
    category_kind,
)


def test_vocabulary_has_exactly_twenty_slugs_ending_with_other():
    assert len(SKILL_GROUPS) == 20
    assert list(SKILL_GROUPS)[-1] == "other"


def test_hard_and_soft_partition():
    assert SOFT_CATEGORY_SLUGS == {
        "leadership-management",
        "collaboration-communication",
        "product-business",
        "process-methodology",
        "domain-knowledge",
    }
    assert SOFT_CATEGORY_SLUGS < set(SKILL_GROUPS)
    assert category_kind("languages") == "hard"
    assert category_kind("product-business") == "soft"
    assert category_kind("other") == "hard"


def test_legacy_remap_targets_live_slugs_and_sources_are_dead():
    for old, new in LEGACY_GROUP_REMAP.items():
        assert old not in SKILL_GROUPS
        assert new in SKILL_GROUPS


def test_legacy_remap_covers_clean_renames_but_not_ambiguous_splits():
    # Clean 1:1 renames must upgrade deterministically.
    assert LEGACY_GROUP_REMAP["devops-tooling"] == "devops-automation"
    assert LEGACY_GROUP_REMAP["databases"] == "databases-storage"
    assert LEGACY_GROUP_REMAP["security"] == "security-compliance"
    # Ambiguous splits are deliberately absent so they drop and get re-classified.
    for ambiguous in ("data-ml", "frameworks", "practices"):
        assert ambiguous not in LEGACY_GROUP_REMAP


def test_groups_module_reexports_vocabulary():
    from resume_agent.taxonomy import groups

    assert groups.SKILL_GROUPS is SKILL_GROUPS
