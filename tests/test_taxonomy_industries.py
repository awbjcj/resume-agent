import json

from resume_tailor_harness.taxonomy.industries import (
    IndustryTaxonomy,
    canonical_industry,
    clean_industry_label,
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


def test_industry_display_labels_capitalize_each_word_without_corrupting_acronyms():
    assert clean_industry_label("financial technology") == "Financial Technology"
    assert clean_industry_label("AI & machine learning") == "AI & Machine Learning"
    assert clean_industry_label("e-commerce") == "E-Commerce"


def test_company_normalization_removes_only_identity_noise():
    assert normalize_company(" ACME, Incorporated ") == "acme"
    assert normalize_company("Acme Robotics LLC") == "acme robotics"
    assert normalize_company("Acme Health") != normalize_company("Acme")


def test_company_normalization_canonicalizes_dotted_abbreviations_and_legal_phrases():
    assert normalize_company("Woven by Toyota, U.S., Inc.") == "woven by toyota us"
    assert normalize_company("WOVEN BY TOYOTA US INC") == "woven by toyota us"
    assert normalize_company("Example, L.L.C.") == "example"
    assert normalize_company("Example Limited Liability Company") == "example"
    assert normalize_company("The Example, P.L.C.") == "example"
    assert normalize_company("Example Professional Corporation") == "example"


def test_company_mapping_wins_before_alias_lookup():
    taxonomy = IndustryTaxonomy(
        aliases={"financial technology": "Fintech"},
        companies={"acme": "Healthcare"},
    )

    assert (
        canonical_industry("Acme, Inc.", "Financial Technology", taxonomy)
        == "Healthcare"
    )
    assert canonical_industry("Other", "Financial Technology", taxonomy) == "Fintech"


def test_taxonomy_normalizes_existing_lowercase_canonical_labels():
    taxonomy = merge_industry_taxonomy(
        IndustryTaxonomy(
            aliases={"financial technology": "financial technology"},
            companies={"acme": "health care"},
        )
    )

    assert taxonomy.aliases == {"financial technology": "Financial Technology"}
    assert taxonomy.companies == {"acme": "Health Care"}


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


def test_concurrent_taxonomy_saves_merge_monotonically(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "industry_taxonomy.json"
    barrier = Barrier(2)

    def save(taxonomy: IndustryTaxonomy) -> None:
        barrier.wait()
        save_industry_taxonomy(taxonomy, path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(save, IndustryTaxonomy(aliases={"fintech": "Fintech"})),
            executor.submit(
                save,
                IndustryTaxonomy(aliases={"health tech": "Healthcare"}),
            ),
        ]
        for future in futures:
            future.result()

    assert load_industry_taxonomy(path).aliases == {
        "fintech": "Fintech",
        "health tech": "Healthcare",
    }
