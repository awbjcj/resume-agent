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
