import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from resume_tailor_harness.models.profile import Contact, ProfileFacts, Skill
from resume_tailor_harness.profile.manual_skills import load_manual_skills
from resume_tailor_harness.profile.matrix import load_matrix
from resume_tailor_harness.profile.store import load_facts, save_facts
from resume_tailor_harness.services.profile_skills import (
    ProfileNotBuiltError,
    SkillAlreadyExistsError,
    SkillNotFoundError,
    add_alias,
    add_skill,
    list_skills,
)


@pytest.fixture()
def profile_dir(tmp_path):
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, tmp_path / "facts.json")
    return tmp_path


@pytest.fixture()
def built_profile_dir(tmp_path):
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"hard": [Skill(name="Kubernetes", category="hard")]},
    )
    save_facts(facts, tmp_path / "facts.json")
    return tmp_path


def test_add_skill_raises_when_profile_not_built(tmp_path):
    with pytest.raises(ProfileNotBuiltError):
        add_skill(tmp_path, "Rust", None)


def test_delete_skill_suppresses_and_removes(built_profile_dir):
    from resume_tailor_harness.services import profile_skills

    profile_skills.delete_skill(built_profile_dir, "kubernetes")
    facts = load_facts(built_profile_dir / "facts.json")
    assert all(
        s.name != "Kubernetes" for skills in facts.skills.values() for s in skills
    )
    assert [e.token for e in profile_skills.list_suppressed(built_profile_dir)] == [
        "kubernetes"
    ]


def test_delete_unknown_skill_raises(built_profile_dir):
    from resume_tailor_harness.services import profile_skills

    with pytest.raises(profile_skills.SkillNotFoundError):
        profile_skills.delete_skill(built_profile_dir, "nonexistent-token")


def test_restore_removes_suppression(built_profile_dir):
    from resume_tailor_harness.services import profile_skills

    profile_skills.delete_skill(built_profile_dir, "kubernetes")
    profile_skills.restore_skill(built_profile_dir, "kubernetes")
    assert profile_skills.list_suppressed(built_profile_dir) == []


def test_restore_unknown_raises(built_profile_dir):
    from resume_tailor_harness.services import profile_skills

    with pytest.raises(profile_skills.SuppressedSkillNotFoundError):
        profile_skills.restore_skill(built_profile_dir, "kubernetes")


def test_add_skill_restores_when_suppressed(built_profile_dir):
    from resume_tailor_harness.services import profile_skills

    profile_skills.delete_skill(built_profile_dir, "kubernetes")
    profile_skills.add_skill(built_profile_dir, "Kubernetes", "hard")
    facts = load_facts(built_profile_dir / "facts.json")
    assert any(s.name == "Kubernetes" for s in facts.skills.get("hard", []))
    assert profile_skills.list_suppressed(built_profile_dir) == []


def test_restore_brings_back_a_deleted_manual_skill(built_profile_dir):
    """A manually-added skill must return immediately on restore, not vanish."""
    from resume_tailor_harness.services import profile_skills

    profile_skills.add_skill(built_profile_dir, "Rust", "hard")
    profile_skills.delete_skill(built_profile_dir, "rust")
    gone = load_facts(built_profile_dir / "facts.json")
    assert all(s.name != "Rust" for skills in gone.skills.values() for s in skills)

    profile_skills.restore_skill(built_profile_dir, "rust")
    facts = load_facts(built_profile_dir / "facts.json")
    assert any(s.name == "Rust" for s in facts.skills.get("hard", []))
    assert profile_skills.list_suppressed(built_profile_dir) == []


def test_delete_by_alias_removes_the_skill(tmp_path):
    """Deleting via an alias token must actually remove the skill, not just log."""
    from resume_tailor_harness.models.profile import Contact, ProfileFacts, Skill
    from resume_tailor_harness.profile.store import save_facts
    from resume_tailor_harness.services import profile_skills

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"hard": [Skill(name="Kubernetes", category="hard", aliases=["k8s"])]},
    )
    save_facts(facts, tmp_path / "facts.json")

    profile_skills.delete_skill(tmp_path, "k8s")
    remaining = load_facts(tmp_path / "facts.json")
    assert all(
        s.name != "Kubernetes" for skills in remaining.skills.values() for s in skills
    )
    # The suppress entry is keyed on the skill's canonical token so it can be restored.
    assert [e.token for e in profile_skills.list_suppressed(tmp_path)] == ["kubernetes"]


def test_list_skills_returns_flat_entries(profile_dir):
    rows = list_skills(profile_dir)
    assert rows == [{"id": rows[0]["id"], "name": "Python", "category": None}]


def test_add_skill_persists_and_regenerates_matrix(profile_dir):
    entry = add_skill(profile_dir, "Rust", "hard")

    facts = load_facts(profile_dir / "facts.json")
    assert "Manually added" not in facts.skills
    assert any(s.name == "Rust" for s in facts.skills["hard"])

    ledger = load_manual_skills(profile_dir / "manual_skills.json")
    assert ledger.entries[0].id == entry.id

    matrix = load_matrix(profile_dir / "matrix.json")
    assert matrix is not None
    assert any(row.key == "rust" for row in matrix.rows)


def test_add_skill_rejects_a_duplicate(profile_dir):
    with pytest.raises(SkillAlreadyExistsError):
        add_skill(profile_dir, "python", None)


def test_concurrent_skill_additions_preserve_both_entries(profile_dir, monkeypatch):
    from resume_tailor_harness.services import profile_skills as service

    original_load = service.load_manual_skills
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def synchronized_load(path):
        nonlocal call_count
        ledger = original_load(path)
        with call_lock:
            call_count += 1
            current = call_count
        if current == 1:
            first_loaded.set()
            second_loaded.wait(timeout=0.25)
        elif current == 2:
            second_loaded.set()
        return ledger

    monkeypatch.setattr(service, "load_manual_skills", synchronized_load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(add_skill, profile_dir, "Rust", None)
        assert first_loaded.wait(timeout=1)
        second = pool.submit(add_skill, profile_dir, "Go", None)
        first.result(timeout=2)
        second.result(timeout=2)

    ledger = load_manual_skills(profile_dir / "manual_skills.json")
    assert {entry.name for entry in ledger.entries if entry.kind == "new_skill"} == {
        "Go",
        "Rust",
    }


def test_add_alias_attaches_to_the_chosen_skill(profile_dir):
    skill_id = list_skills(profile_dir)[0]["id"]
    assert skill_id is not None

    entry = add_alias(profile_dir, skill_id, "Python3")

    facts = load_facts(profile_dir / "facts.json")
    assert "Python3" in facts.skills["Languages"][0].aliases
    ledger = load_manual_skills(profile_dir / "manual_skills.json")
    assert ledger.entries[0].id == entry.id


def test_add_alias_rejects_unknown_skill_id(profile_dir):
    with pytest.raises(SkillNotFoundError):
        add_alias(profile_dir, "nonexistent", "Python3")


def test_add_alias_rejects_a_duplicate_alias(profile_dir):
    skill_id = list_skills(profile_dir)[0]["id"]
    assert skill_id is not None

    with pytest.raises(SkillAlreadyExistsError):
        add_alias(profile_dir, skill_id, "py")
