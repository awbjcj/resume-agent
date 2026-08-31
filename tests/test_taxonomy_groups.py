import json
from types import SimpleNamespace

import pytest

from resume_tailor_harness.taxonomy.groups import (
    SKILL_GROUPS,
    SkillGroupAssignment,
    SkillGroupAssignments,
    classify_missing_groups,
    group_map_path,
    load_group_map,
    save_group_map,
)


class FakeRunner:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(content=content)

    async def arun(self, prompt: str):
        return self.run(prompt)


def assignments(*pairs: tuple[str, str]) -> SkillGroupAssignments:
    return SkillGroupAssignments(
        assignments=[
            SkillGroupAssignment(token=token, group=group) for token, group in pairs
        ]
    )


def test_groups_reexports_twenty_slug_vocabulary_with_other_last():
    slugs = list(SKILL_GROUPS)
    assert len(slugs) == 20
    assert slugs[-1] == "other"
    assert SKILL_GROUPS["cloud-infra"] == "Cloud & Infrastructure"


def test_group_map_path_uses_active_data_root(tmp_path):
    assert group_map_path(tmp_path / "data" / "profile") == (
        tmp_path / "data" / "taxonomy" / "skill_groups.json"
    )


def test_group_map_normalizes_filters_merges_and_round_trips_atomically(tmp_path):
    path = tmp_path / "skill_groups.json"
    save_group_map(
        {" Python ": "languages", "bad": "invented", "": "other"},
        path,
    )
    save_group_map({"python": "ai-ml", "Kubernetes": "cloud-infra"}, path)

    assert load_group_map(path) == {
        "kubernetes": "cloud-infra",
        "python": "languages",
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_load_group_map_drops_unknown_slugs_and_invalid_files(tmp_path):
    path = tmp_path / "skill_groups.json"
    path.write_text(
        json.dumps({"Python": "languages", "cobol": "retro", "x": 3}),
        encoding="utf-8",
    )
    assert load_group_map(path) == {"python": "languages"}
    path.write_text("not json", encoding="utf-8")
    assert load_group_map(path) == {}
    assert load_group_map(tmp_path / "missing.json") == {}


def test_load_group_map_upgrades_clean_legacy_slugs_and_drops_ambiguous(tmp_path):
    path = tmp_path / "skill_groups.json"
    path.write_text(
        json.dumps(
            {
                "Bash": "devops-tooling",  # clean 1:1 -> devops-automation
                "Postgres": "databases",  # clean 1:1 -> databases-storage
                "OAuth": "security",  # clean 1:1 -> security-compliance
                "Slack": "communication",  # clean 1:1 -> collaboration-communication
                "Mentoring": "leadership",  # clean 1:1 -> leadership-management
                "Pandas": "data-ml",  # ambiguous split -> dropped, re-classified
                "React": "frameworks",  # ambiguous split -> dropped, re-classified
                "Agile": "practices",  # ambiguous split -> dropped, re-classified
            }
        ),
        encoding="utf-8",
    )
    assert load_group_map(path) == {
        "bash": "devops-automation",
        "postgres": "databases-storage",
        "oauth": "security-compliance",
        "slack": "collaboration-communication",
        "mentoring": "leadership-management",
    }


def test_classifier_accepts_only_exact_batch_tokens_and_known_slugs():
    runner = FakeRunner(
        assignments(
            ("python", "languages"),
            ("Python", "ai-ml"),
            ("not-asked", "languages"),
            ("k8s", "made-up"),
        )
    )
    assert classify_missing_groups({"Python", "k8s"}, runner) == {"python": "languages"}
    assert json.loads(runner.prompts[0]) == ["k8s", "python"]


def test_classifier_shards_isolates_failures_and_keeps_first_duplicate():
    runner = FakeRunner(
        RuntimeError("rate limited"),
        assignments(("zeta", "languages"), ("zeta", "other")),
    )
    tokens = {f"skill-{index:02d}" for index in range(40)} | {"zeta"}
    assert classify_missing_groups(tokens, runner, batch_size=40) == {
        "zeta": "languages"
    }
    assert len(runner.prompts) == 2


def test_classifier_empty_input_and_invalid_batch_size():
    runner = FakeRunner()
    assert classify_missing_groups(set(), runner) == {}
    assert runner.prompts == []
    with pytest.raises(ValueError, match="batch_size"):
        classify_missing_groups({"python"}, runner, batch_size=0)
