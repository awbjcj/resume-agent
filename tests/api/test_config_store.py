"""ConfigStore seam: YAML round-trip, defaults on missing file, domain registry."""

import pytest

from resume_tailor_harness.api.schemas.config import (
    DOMAIN_SCHEMAS,
    PruneConfigDoc,
    SearchConfigDoc,
    StyleGuideDoc,
)
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.services.config_store import YamlConfigStore


@pytest.fixture()
def store(tmp_path):
    return YamlConfigStore(config_dir=tmp_path)


def test_get_missing_file_returns_defaults(store):
    doc = store.get("prune")
    assert isinstance(doc, PruneConfigDoc)
    assert doc.fit_threshold == 40
    assert doc.enable_rejected is True


def test_put_then_get_round_trips(store, tmp_path):
    doc = PruneConfigDoc(
        fit_threshold=55,
        stale_days=30,
        retention_days=7,
        enable_rejected=False,
        enable_low_fit=True,
        enable_stale=True,
    )
    store.put("prune", doc)
    assert (tmp_path / "prune.yaml").exists()
    again = store.get("prune")
    assert again.fit_threshold == 55
    assert again.enable_rejected is False


def test_yaml_on_disk_is_snake_case(store, tmp_path):
    store.put("prune", PruneConfigDoc())
    text = (tmp_path / "prune.yaml").read_text(encoding="utf-8")
    assert "fit_threshold" in text
    assert "fitThreshold" not in text


def test_style_guide_is_plain_text(store, tmp_path):
    store.put("style_guide", StyleGuideDoc(content="# Voice\nBe terse."))
    assert (tmp_path / "style_guide.md").read_text(
        encoding="utf-8"
    ) == "# Voice\nBe terse."
    assert store.get("style_guide").content == "# Voice\nBe terse."


def test_unknown_domain_raises_key_error(store):
    with pytest.raises(KeyError):
        store.get("connectors")  # connectors stays behind /api/sources


def test_search_doc_covers_search_config_fields():
    """Drift gate: every SearchConfig field exists on SearchConfigDoc.

    ``schema_version`` is inherited from ``ExtensibleModel`` (base-model
    bookkeeping, not a search field) and is deliberately absent from the wire
    doc, so exclude it from the comparison — otherwise the subset check fails.
    """
    assert set(SearchConfig.model_fields) - {"schema_version"} <= set(
        SearchConfigDoc.model_fields
    )


def test_domain_registry_contents():
    assert set(DOMAIN_SCHEMAS) == {
        "search",
        "review",
        "review_deep",
        "prune",
        "render",
        "style_guide",
        "profile",
    }
