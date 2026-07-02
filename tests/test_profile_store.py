import os

import pytest

import resume_agent.profile.store as store
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts, save_facts


def test_save_creates_parent_dirs_and_round_trips(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    out = tmp_path / "nested" / "facts.json"

    saved_path = save_facts(facts, out)
    assert saved_path.exists()

    loaded = load_facts(out)
    assert loaded.contact.name == "Ada Lovelace"


def test_saved_json_is_human_readable(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    out = tmp_path / "facts.json"
    save_facts(facts, out)
    text = out.read_text(encoding="utf-8")
    assert "\n" in text  # indented, not a single line
    assert "Ada" in text


def test_save_facts_atomically_replaces_and_cleans_failed_temp(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "facts.json"
    facts = ProfileFacts(contact=Contact(name="Ada"))
    real_replace = os.replace
    replacements = []

    def tracking_replace(source, destination):
        replacements.append((source, destination))
        assert source.exists()
        assert source.parent == path.parent
        real_replace(source, destination)

    monkeypatch.setattr(store.os, "replace", tracking_replace)
    save_facts(facts, path)
    assert len(replacements) == 1
    assert replacements[0][1] == path

    before = set(path.parent.iterdir())
    monkeypatch.setattr(
        store.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        save_facts(facts, path)
    assert set(path.parent.iterdir()) == before
