import pytest

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.group_corrections import (
    corrections_path,
    load_group_corrections,
)
from resume_agent.profile.matrix import load_matrix, rebuild_saved_matrix
from resume_agent.profile.store import load_facts, save_facts
from resume_agent.services.profile_groups import (
    GroupCorrectionNotFoundError,
    UnknownGroupError,
    clear_group,
    set_group,
)
from resume_agent.services.profile_skills import (
    ProfileNotBuiltError,
    SkillNotFoundError,
)
from resume_agent.taxonomy.groups import group_map_path, save_group_map


@pytest.fixture()
def profile_dir(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, profile / "facts.json")
    save_group_map({"python": "languages"}, group_map_path(profile))
    return profile


def test_set_group_raises_when_profile_not_built(tmp_path):
    with pytest.raises(ProfileNotBuiltError):
        set_group(tmp_path / "profile", "python", "data-ml")


def test_set_group_rejects_unknown_slug(profile_dir):
    with pytest.raises(UnknownGroupError):
        set_group(profile_dir, "python", "not-a-group")


def test_set_group_rejects_unknown_skill_without_persisting_matrix(profile_dir):
    matrix_path = profile_dir / "matrix.json"
    matrix_path.write_text("existing matrix", encoding="utf-8")

    with pytest.raises(SkillNotFoundError):
        set_group(profile_dir, "cobol", "languages")

    assert matrix_path.read_text(encoding="utf-8") == "existing matrix"


def test_set_group_writes_ledger_and_matrix(profile_dir):
    row = set_group(profile_dir, "python", "data-ml")

    assert (row.group, row.group_source) == ("data-ml", "correction")
    ledger = load_group_corrections(corrections_path(profile_dir))
    assert ledger.as_map() == {"python": "data-ml"}
    assert ledger.corrections["python"].corrected_at
    saved = load_matrix(profile_dir / "matrix.json")
    assert saved is not None
    assert (saved.rows[0].group, saved.rows[0].group_source) == (
        "data-ml",
        "correction",
    )


def test_set_group_resolves_aliases_to_the_canonical_token(profile_dir):
    row = set_group(profile_dir, "py", "data-ml")

    assert row.key == "python"
    assert load_group_corrections(corrections_path(profile_dir)).as_map() == {
        "python": "data-ml"
    }


def test_correction_survives_taxonomy_reset_and_rebuild(profile_dir):
    set_group(profile_dir, "python", "data-ml")
    group_map_path(profile_dir).unlink()

    facts = load_facts(profile_dir / "facts.json")
    matrix = rebuild_saved_matrix(profile_dir, facts)

    assert (matrix.rows[0].group, matrix.rows[0].group_source) == (
        "data-ml",
        "correction",
    )


def test_clear_group_reverts_to_taxonomy(profile_dir):
    set_group(profile_dir, "python", "data-ml")

    clear_group(profile_dir, "py")

    assert load_group_corrections(corrections_path(profile_dir)).corrections == {}
    saved = load_matrix(profile_dir / "matrix.json")
    assert saved is not None
    assert (saved.rows[0].group, saved.rows[0].group_source) == (
        "languages",
        "taxonomy",
    )


def test_clear_group_without_correction_raises_without_persisting_matrix(profile_dir):
    with pytest.raises(GroupCorrectionNotFoundError):
        clear_group(profile_dir, "python")

    assert not (profile_dir / "matrix.json").exists()
