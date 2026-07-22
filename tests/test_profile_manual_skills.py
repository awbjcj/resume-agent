from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.manual_skills import (
    ManualAliasEntry,
    ManualSkillEntry,
    ManualSkillsLedger,
    ManualSuppressEntry,
    apply_manual_skill_entry,
    apply_manual_skills,
    load_manual_skills,
    save_manual_skills,
)
from resume_agent.tracking.match_gap import normalize_skill


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )


def test_new_skill_entry_adds_a_skill_to_its_real_category_bucket():
    facts = _facts()
    entry = ManualSkillEntry(name="Rust", category="hard", added_at="2026-07-16T00:00:00+00:00")

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    assert "Manually added" not in updated.skills
    added = updated.skills["hard"]
    assert len(added) == 1
    assert added[0].name == "Rust"
    assert added[0].category == "hard"
    assert added[0].inferred is False


def test_new_skill_without_category_defaults_to_hard():
    facts, _ = apply_manual_skill_entry(
        ProfileFacts(contact=Contact(name="Ada")), ManualSkillEntry(name="GraphQL")
    )
    assert any(
        s.name == "GraphQL" and s.category == "hard" for s in facts.skills["hard"]
    )


def test_new_skill_entry_is_a_noop_when_the_skill_already_exists():
    facts = _facts()
    entry = ManualSkillEntry(name="python", added_at="2026-07-16T00:00:00+00:00")

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    assert "hard" not in updated.skills


def test_alias_entry_attaches_to_the_matching_skill_by_normalized_name():
    facts = _facts()
    entry = ManualAliasEntry(
        target_skill_token=normalize_skill("Python"),
        target_skill_display="Python",
        alias_text="Python3",
        added_at="2026-07-16T00:00:00+00:00",
    )

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    assert "Python3" in updated.skills["Languages"][0].aliases


def test_alias_entry_is_a_noop_when_already_present():
    facts = _facts()
    entry = ManualAliasEntry(
        target_skill_token=normalize_skill("Python"),
        target_skill_display="Python",
        alias_text="py",
        added_at="2026-07-16T00:00:00+00:00",
    )

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    assert updated.skills["Languages"][0].aliases == ["py"]


def test_alias_entry_warns_when_target_skill_is_gone():
    facts = _facts()
    entry = ManualAliasEntry(
        target_skill_token="cobol",
        target_skill_display="COBOL",
        alias_text="cobol-legacy",
        added_at="2026-07-16T00:00:00+00:00",
    )

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is not None
    assert "COBOL" in warning
    assert updated.model_dump() == facts.model_dump()


def test_apply_manual_skills_replays_every_entry_and_is_idempotent():
    facts = _facts()
    ledger = ManualSkillsLedger(
        entries=[
            ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00"),
            ManualAliasEntry(
                target_skill_token=normalize_skill("Python"),
                target_skill_display="Python",
                alias_text="Python3",
                added_at="2026-07-16T00:00:00+00:00",
            ),
        ]
    )

    once, warnings_once = apply_manual_skills(facts, ledger)
    twice, warnings_twice = apply_manual_skills(once, ledger)

    assert warnings_once == []
    assert warnings_twice == []
    assert len(once.skills["hard"]) == 1
    assert len(twice.skills["hard"]) == 1
    assert twice.skills["Languages"][0].aliases == ["py", "Python3"]


def test_suppress_removes_matching_skill_after_adds():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"hard": [Skill(name="Kubernetes", category="hard")]},
    )
    ledger = ManualSkillsLedger(
        entries=[ManualSuppressEntry(token="kubernetes", display="Kubernetes")]
    )
    facts, warnings = apply_manual_skills(facts, ledger)
    assert warnings == []
    assert all(s.name != "Kubernetes" for s in facts.skills.get("hard", []))


def test_suppress_applies_after_add_of_same_token():
    ledger = ManualSkillsLedger(
        entries=[
            ManualSkillEntry(name="Rust", category="hard"),
            ManualSuppressEntry(token="rust", display="Rust"),
        ]
    )
    facts, _ = apply_manual_skills(ProfileFacts(contact=Contact(name="Ada")), ledger)
    assert all(s.name != "Rust" for s in facts.skills.get("hard", []))


def test_save_and_load_manual_skills_roundtrip(tmp_path):
    path = tmp_path / "manual_skills.json"
    ledger = ManualSkillsLedger(
        entries=[
            ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00"),
            ManualSuppressEntry(token="kubernetes", display="Kubernetes"),
        ]
    )

    save_manual_skills(ledger, path)
    loaded = load_manual_skills(path)

    assert isinstance(loaded.entries[0], ManualSkillEntry)
    assert loaded.entries[0].name == "Rust"
    assert isinstance(loaded.entries[1], ManualSuppressEntry)
    assert loaded.entries[1].token == "kubernetes"


def test_load_manual_skills_missing_file_returns_empty_ledger(tmp_path):
    loaded = load_manual_skills(tmp_path / "nope.json")
    assert loaded.entries == []
