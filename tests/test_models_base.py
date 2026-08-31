from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel, FactItem, Source, new_id


def test_new_id_is_unique_and_short():
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12


def test_extensible_model_defaults():
    m = ExtensibleModel()
    assert m.schema_version == 1


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
    f = FactItem(source=Source.github)
    assert f.source == Source.github
    assert f.model_dump()["source"] == "github"


class _CollectionModel(ExtensibleModel):
    items: list[str] = Field(default_factory=list)
    mapping: dict[str, int] = Field(default_factory=dict)
    maybe: list[str] | None = None


def test_null_list_field_coerced_to_empty():
    # JSON-mode LLM providers may emit ``null`` for an empty non-nullable list
    # despite the schema; coerce it rather than failing the whole structured result.
    m = _CollectionModel.model_validate({"items": None})
    assert m.items == []


def test_null_dict_field_coerced_to_empty():
    m = _CollectionModel.model_validate({"mapping": None})
    assert m.mapping == {}


def test_nullable_collection_field_keeps_none():
    # A genuinely Optional collection must stay None -- coercion only applies to
    # non-nullable fields where None could never be valid anyway.
    m = _CollectionModel.model_validate({"maybe": None})
    assert m.maybe is None


def test_profilefacts_coerces_null_collections():
    from resume_tailor_harness.models.profile import ProfileFacts

    facts = ProfileFacts.model_validate(
        {
            "contact": {"name": "X"},
            "experience": None,
            "skills": None,
            "interests": None,
        }
    )
    assert facts.experience == []
    assert facts.skills == {}
    assert facts.interests == []
