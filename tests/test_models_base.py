from resume_agent.models.base import ExtensibleModel, FactItem, Source, new_id


def test_new_id_is_unique_and_short():
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12


def test_extensible_model_defaults():
    m = ExtensibleModel()
    assert m.schema_version == 1
    assert m.extra == {}


def test_extensible_model_ignores_unknown_keys():
    # Forward-compat: older code reading newer JSON must not crash.
    m = ExtensibleModel.model_validate({"future_field": 123})
    assert not hasattr(m, "future_field")


def test_fact_item_has_auto_id_and_default_source():
    f1, f2 = FactItem(), FactItem()
    assert f1.id != f2.id
    assert f1.source == Source.resume


def test_fact_item_source_round_trips():
    f = FactItem(source="github")
    assert f.source == Source.github
    assert f.model_dump()["source"] == "github"
