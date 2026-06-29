import json

from resume_agent.taxonomy.industries import (
    IndustryTaxonomy,
    canonical_industry,
    load_industry_taxonomy,
    merge_industry_taxonomy,
    normalize_company,
    normalize_industry,
    save_industry_taxonomy,
)


def test_industry_normalization_collapses_human_readable_variants():
    assert normalize_industry("  Autonomous_vehicle--Technology! ") == (
        "autonomous vehicle technology"
    )
    assert normalize_industry("7372") is None
    assert normalize_industry("Web3") == "web3"


def test_company_normalization_removes_only_identity_noise():
    assert normalize_company(" ACME, Incorporated ") == "acme"
    assert normalize_company("Acme Robotics LLC") == "acme robotics"
    assert normalize_company("Acme Health") != normalize_company("Acme")


def test_company_mapping_wins_before_alias_lookup():
    taxonomy = IndustryTaxonomy(
        aliases={"financial technology": "Fintech"},
        companies={"acme": "Healthcare"},
    )

    assert canonical_industry("Acme, Inc.", "Financial Technology", taxonomy) == "Healthcare"
    assert canonical_industry("Other", "Financial Technology", taxonomy) == "Fintech"


def test_taxonomy_merge_is_monotonic_and_persistence_is_idempotent(tmp_path):
    existing = IndustryTaxonomy(
        aliases={"fintech": "Fintech"},
        companies={"acme": "Fintech"},
    )
    merged = merge_industry_taxonomy(
        existing,
        aliases={"fintech": "Banking", "financial technology": "Fintech"},
        companies={"acme": "Banking", "waymo": "Autonomous Driving"},
    )

    assert merged.aliases == {
        "fintech": "Fintech",
        "financial technology": "Fintech",
    }
    assert merged.companies == {"acme": "Fintech", "waymo": "Autonomous Driving"}

    path = tmp_path / "industry_taxonomy.json"
    save_industry_taxonomy(merged, path)
    first = path.read_text("utf-8")
    save_industry_taxonomy(load_industry_taxonomy(path), path)

    assert path.read_text("utf-8") == first
    assert json.loads(first)["aliases"]["fintech"] == "Fintech"
