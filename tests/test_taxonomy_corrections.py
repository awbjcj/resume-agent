"""Corrections ledger sanitization, persistence, replay, and transactions."""

import json
from concurrent.futures import ThreadPoolExecutor

from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    added_canonical_tokens,
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
    removed_canonical_tokens,
    save_taxonomy_corrections,
    update_taxonomy_corrections,
)


def _base_map() -> ClusterMap:
    return ClusterMap(
        aliases={"js": "javascript", "javascript": "javascript", "react": "react"},
        domain_of={"javascript": "web-langs", "react": "web-frameworks"},
        domain_label={"web-langs": "Web Languages", "web-frameworks": "Web Frameworks"},
        category_of={"web-langs": "languages", "web-frameworks": "frontend-web"},
    )


def test_round_trip_normalizes_and_applies_added_over_removed(tmp_path):
    path = tmp_path / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(
            skill_domain={"React ": "web-frameworks"},
            domain_category={"web-frameworks": "frontend-web", "x": "bad-slug"},
            added_skills=["GraphQL", "graphql"],
            removed_skills=["cobol", "graphql"],
        ),
        path,
    )

    loaded = load_taxonomy_corrections(path)

    assert loaded.skill_domain == {"react": "web-frameworks"}
    assert loaded.domain_category == {"web-frameworks": "frontend-web"}
    assert loaded.added_skills == ["graphql"]
    assert loaded.removed_skills == ["cobol"]


def test_load_salvages_valid_neighbors_of_bad_types_and_cycles(tmp_path):
    path = tmp_path / "taxonomy_corrections.json"
    path.write_text(
        json.dumps(
            {
                "skill_domain": {"react": "web-frameworks", "bad": 3},
                "aliases": {"a": "b", "b": "a", "js": "javascript"},
                "domain_merges": {"a": "b", "b": "a", "old": "current"},
                "domain_category": {"current": "frontend-web", "x": "invalid"},
                "added_skills": ["GraphQL", 7],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_taxonomy_corrections(path)

    assert loaded.skill_domain == {"react": "web-frameworks"}
    assert loaded.aliases == {"js": "javascript"}
    assert loaded.domain_merges == {"old": "current"}
    assert loaded.domain_category == {"current": "frontend-web"}
    assert loaded.added_skills == ["graphql"]


def test_load_unreadable_is_empty(tmp_path):
    path = tmp_path / "taxonomy_corrections.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_taxonomy_corrections(path) == TaxonomyCorrections()


def test_apply_moves_skill_and_reconstructs_user_domain():
    corrected = apply_taxonomy_corrections(
        _base_map(),
        TaxonomyCorrections(
            skill_domain={"react": "ui-toolkits"},
            domain_renames={"ui-toolkits": "UI Toolkits"},
            domain_category={"ui-toolkits": "frontend-web"},
        ),
    )

    assert corrected.domain_of["react"] == "ui-toolkits"
    assert corrected.domain_label["ui-toolkits"] == "UI Toolkits"
    assert corrected.category_of["ui-toolkits"] == "frontend-web"


def test_apply_dangling_move_is_inert():
    corrected = apply_taxonomy_corrections(
        _base_map(), TaxonomyCorrections(skill_domain={"react": "ghost"})
    )
    assert corrected.domain_of["react"] == "web-frameworks"


def test_apply_merges_domains_then_applies_survivor_rename():
    corrected = apply_taxonomy_corrections(
        _base_map(),
        TaxonomyCorrections(
            domain_merges={"web-frameworks": "web-langs"},
            domain_renames={"web-langs": "Web Stack"},
        ),
    )

    assert corrected.domain_of == {"javascript": "web-langs", "react": "web-langs"}
    assert corrected.domain_label["web-langs"] == "Web Stack"
    assert "web-frameworks" not in corrected.category_of


def test_alias_terminal_domain_wins_regardless_of_map_order():
    cmap = ClusterMap(
        aliases={"reactjs": "reactjs", "react": "react"},
        domain_of={"reactjs": "loser", "react": "winner"},
        domain_label={"loser": "Loser", "winner": "Winner"},
        category_of={"loser": "other", "winner": "frontend-web"},
    )

    corrected = apply_taxonomy_corrections(
        cmap, TaxonomyCorrections(aliases={"reactjs": "react"})
    )

    assert corrected.aliases["reactjs"] == "react"
    assert corrected.domain_of["react"] == "winner"


def test_apply_is_idempotent():
    corrections = TaxonomyCorrections(
        skill_domain={"react": "ui-toolkits"},
        domain_renames={"ui-toolkits": "UI Toolkits"},
        domain_category={"ui-toolkits": "frontend-web"},
        domain_merges={"web-langs": "ui-toolkits"},
    )
    once = apply_taxonomy_corrections(_base_map(), corrections)
    assert apply_taxonomy_corrections(once, corrections) == once


def test_added_and_removed_canonical_helpers():
    corrections = TaxonomyCorrections(added_skills=["graphql"], removed_skills=["js"])
    aliases = {"js": "javascript"}
    assert added_canonical_tokens(corrections, aliases) == {"graphql"}
    assert removed_canonical_tokens(corrections, aliases) == {"javascript"}


def test_update_transaction_preserves_concurrent_intents(tmp_path):
    path = tmp_path / "taxonomy_corrections.json"

    def add(token: str) -> None:
        def mutate(ledger: TaxonomyCorrections) -> None:
            ledger.added_skills.append(token)

        update_taxonomy_corrections(path, mutate)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, [f"skill-{index}" for index in range(40)]))

    assert set(load_taxonomy_corrections(path).added_skills) == {
        f"skill {index}" for index in range(40)
    }
