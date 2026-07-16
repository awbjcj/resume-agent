from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.manual_skills import (
    MANUAL_SKILLS_BUCKET,
    ManualAliasEntry,
    ManualSkillEntry,
    ManualSkillsLedger,
    apply_manual_skill_entry,
    apply_manual_skills,
    load_manual_skills,
    remove_manual_skill_entry,
    save_manual_skills,
)
from resume_agent.tracking.match_gap import normalize_skill


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )


def test_new_skill_entry_adds_a_skill_to_the_manual_bucket():
    facts = _facts()
    entry = ManualSkillEntry(name="Rust", category="hard", added_at="2026-07-16T00:00:00+00:00")

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    added = updated.skills[MANUAL_SKILLS_BUCKET]
    assert len(added) == 1
    assert added[0].name == "Rust"
    assert added[0].category == "hard"
    assert added[0].inferred is False


def test_new_skill_entry_is_a_noop_when_the_skill_already_exists():
    facts = _facts()
    entry = ManualSkillEntry(name="python", added_at="2026-07-16T00:00:00+00:00")

    updated, warning = apply_manual_skill_entry(facts, entry)

    assert warning is None
    assert MANUAL_SKILLS_BUCKET not in updated.skills


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
    assert len(once.skills[MANUAL_SKILLS_BUCKET]) == 1
    assert len(twice.skills[MANUAL_SKILLS_BUCKET]) == 1
    assert twice.skills["Languages"][0].aliases == ["py", "Python3"]


def test_remove_new_skill_entry_deletes_it_from_the_manual_bucket():
    facts = _facts()
    entry = ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00")
    with_skill, _ = apply_manual_skill_entry(facts, entry)

    reverted = remove_manual_skill_entry(with_skill, entry)

    assert MANUAL_SKILLS_BUCKET not in reverted.skills


def test_remove_alias_entry_strips_the_alias_but_keeps_the_skill():
    facts = _facts()
    entry = ManualAliasEntry(
        target_skill_token=normalize_skill("Python"),
        target_skill_display="Python",
        alias_text="Python3",
        added_at="2026-07-16T00:00:00+00:00",
    )
    with_alias, _ = apply_manual_skill_entry(facts, entry)

    reverted = remove_manual_skill_entry(with_alias, entry)

    assert reverted.skills["Languages"][0].aliases == ["py"]


def test_save_and_load_manual_skills_roundtrip(tmp_path):
    path = tmp_path / "manual_skills.json"
    ledger = ManualSkillsLedger(
        entries=[ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00")]
    )

    save_manual_skills(ledger, path)
    loaded = load_manual_skills(path)

    loaded_entry = loaded.entries[0]
    assert isinstance(loaded_entry, ManualSkillEntry)
    assert loaded_entry.name == "Rust"


def test_load_manual_skills_missing_file_returns_empty_ledger(tmp_path):
    loaded = load_manual_skills(tmp_path / "nope.json")
    assert loaded.entries == []
