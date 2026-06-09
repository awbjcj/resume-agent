from resume_agent.models.base import ExtensibleModel, FactItem, Source, new_id


def test_new_id_is_unique_and_short():
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12


def test_extensible_model_defaults():
    m = ExtensibleModel()
    assert m.schema_version == 1
    assert m.extra == {}


def test_extensible_model_preserves_unknown_keys():
    # Forward-compat: unknown keys are preserved (not dropped) so a load->save
    # round-trip of newer JSON doesn't lose data the model doesn't model yet.
    m = ExtensibleModel.model_validate({"future_field": 123})
    assert m.model_dump()["future_field"] == 123
    restored = ExtensibleModel.model_validate_json(m.model_dump_json())
    assert restored.model_dump()["future_field"] == 123


def test_fact_item_has_auto_id_and_default_source():
    f1, f2 = FactItem(), FactItem()
    assert f1.id != f2.id
    assert f1.source == Source.resume


def test_fact_item_source_round_trips():
    f = FactItem(source="github")
    assert f.source == Source.github
    assert f.model_dump()["source"] == "github"
