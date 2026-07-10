from datetime import date

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.profile.matrix import (
    MatrixRow,
    Overrides,
    SkillMatrix,
    build_matrix,
    build_skill_match_context,
    apply_skill_groups,
    effective_cluster_map,
    load_matrix,
    load_overrides,
    override_tokens,
    save_matrix,
)
from resume_agent.taxonomy.clusters import ClusterMap


def _facts():
    bullet = Bullet(text="Deployed services on Kubernetes clusters")
    experience = Experience(
        company="Acme",
        title="Engineer",
        start="2023",
        current=True,
        bullets=[bullet],
        tech=["Kubernetes"],
    )
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[experience],
        skills={
            "Platforms": [Skill(name="Kubernetes", aliases=["k8s"])],
            "soft": [
                Skill(
                    name="Mentorship",
                    inferred=True,
                    category="soft",
                    evidence_fact_ids=[bullet.id],
                )
            ],
        },
    )


def test_matrix_rows_are_canonical_with_deduplicated_evidence_and_recency():
    facts = _facts()
    matrix = build_matrix(facts, ClusterMap.empty(), Overrides(), today=date(2026, 7, 1))
    kubernetes = next(row for row in matrix.rows if row.key == "kubernetes")
    bullet = facts.experience[0].bullets[0]
    skill = facts.skills["Platforms"][0]
    assert kubernetes.display == "Kubernetes"
    assert "k8s" in kubernetes.aliases
    assert kubernetes.strength > 0
    assert kubernetes.last_used == "current"
    assert set(kubernetes.evidence_fact_ids) == {skill.id, bullet.id}
    assert facts.experience[0].id not in kubernetes.evidence_fact_ids


def test_matrix_inferred_means_inferred_only():
    facts = _facts()
    facts.skills["soft"].append(Skill(name="K8s", aliases=["Mentorship"]))
    cluster_map = ClusterMap(aliases={"mentorship": "k8s", "k8s": "k8s"})
    matrix = build_matrix(facts, cluster_map, Overrides(), today=date(2026, 7, 1))
    row = next(item for item in matrix.rows if item.key == "k8s")
    assert row.inferred is False


def test_overrides_ban_and_category():
    overrides = Overrides(ban=["mentorship"], category={"kubernetes": "hard"})
    matrix = build_matrix(_facts(), ClusterMap.empty(), overrides, today=date(2026, 7, 1))
    assert "mentorship" not in [row.key for row in matrix.rows]
    assert next(row for row in matrix.rows if row.key == "kubernetes").category == "hard"


def test_effective_cluster_map_force_then_forbid_wins():
    cluster_map = ClusterMap(
        aliases={"golang": "golang", "java": "jvm", "kotlin": "jvm"},
        theme_of={"golang": "languages", "jvm": "languages"},
    )
    overrides = Overrides(alias={"golang": "go"}, forbid_alias=[["java", "kotlin"]])
    fixed = effective_cluster_map(cluster_map, overrides)
    assert fixed.aliases["golang"] == "go"
    assert fixed.aliases["java"] == "java"
    assert fixed.aliases["kotlin"] == "kotlin"
    assert fixed.theme_of["java"] == "languages"
    assert fixed.theme_of["kotlin"] == "languages"


def test_override_tokens_covers_alias_forbid_and_category():
    overrides = Overrides(
        alias={"Golang": "Go"},
        forbid_alias=[["Java", "Kotlin"]],
        category={"Stakeholder Management": "soft"},
    )
    assert override_tokens(overrides) == {
        "golang",
        "go",
        "java",
        "kotlin",
        "stakeholder management",
    }


def test_matrix_deterministic_and_round_trips(tmp_path):
    facts = _facts()
    first = build_matrix(facts, ClusterMap.empty(), Overrides(), today=date(2026, 7, 1))
    second = build_matrix(facts, ClusterMap.empty(), Overrides(), today=date(2026, 7, 1))
    assert [(row.key, row.strength) for row in first.rows] == [
        (row.key, row.strength) for row in second.rows
    ]
    path = tmp_path / "matrix.json"
    save_matrix(first, path)
    loaded = load_matrix(path)
    assert loaded is not None
    assert [row.key for row in loaded.rows] == [row.key for row in first.rows]
    assert load_matrix(tmp_path / "missing.json") is None
    assert not list(tmp_path.glob("*.tmp"))


def test_load_matrix_rejects_different_facts_or_effective_map(tmp_path):
    original = _facts()
    effective = effective_cluster_map(ClusterMap.empty(), Overrides())
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(original, effective, Overrides()), path)
    changed = original.model_copy(deep=True)
    changed.skills["Platforms"][0].name = "Nomad"
    assert load_matrix(path, facts=changed) is None
    changed_map = ClusterMap(aliases={"k8s": "kubernetes"})
    assert load_matrix(path, facts=original, cluster_map=changed_map) is None


def test_undated_project_has_unknown_last_used():
    project = Project(name="API", tech=["FastAPI"])
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[project],
        skills={"Frameworks": [Skill(name="FastAPI")]},
    )
    matrix = build_matrix(facts, ClusterMap.empty(), Overrides())
    assert matrix.rows[0].last_used is None


def test_explicit_bullet_and_owner_evidence_count_as_one_signal():
    bullet = Bullet(text="Mentored engineers")
    experience = Experience(
        company="Acme", title="Engineer", current=True, bullets=[bullet]
    )
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[experience],
        skills={
            "soft": [
                Skill(
                    name="Mentorship",
                    inferred=True,
                    category="soft",
                    evidence_fact_ids=[experience.id, bullet.id],
                )
            ]
        },
    )
    matrix = build_matrix(facts, ClusterMap.empty(), Overrides())
    assert matrix.rows[0].strength == 1.0


def test_build_skill_match_context_covers_alias_adjacent_gap_and_compounds():
    matrix = SkillMatrix(
        rows=[
            MatrixRow(key="kubernetes", display="Kubernetes", strength=4),
            MatrixRow(key="flask", display="Flask", strength=3),
            MatrixRow(key="django", display="Django", strength=2),
        ]
    )
    cluster_map = ClusterMap(
        aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
        theme_of={"fastapi": "web", "flask": "web", "django": "web"},
    )
    criteria = JobCriteria(
        must_have_skills=["k8s", "FastAPI", "Rust and Go"],
        nice_to_have_skills=["Django"],
    )
    context = build_skill_match_context(criteria, matrix, cluster_map)
    by_requirement = {match.requirement: match for match in context.matches}
    assert by_requirement["k8s"].coverage == "covered"
    assert by_requirement["FastAPI"].coverage == "adjacent"
    assert by_requirement["FastAPI"].row is not None
    assert by_requirement["FastAPI"].row.key == "flask"
    assert by_requirement["Rust"].coverage == "gap"
    assert by_requirement["Go"].coverage == "gap"
    assert by_requirement["Django"].coverage == "covered"


def test_forced_and_forbidden_aliases_control_match_context():
    raw = ClusterMap(aliases={"java": "jvm", "kotlin": "jvm"})
    effective = effective_cluster_map(
        raw,
        Overrides(alias={"golang": "go"}, forbid_alias=[["java", "kotlin"]]),
    )
    matrix = SkillMatrix(
        rows=[
            MatrixRow(key="go", display="Go", strength=1),
            MatrixRow(key="java", display="Java", strength=1),
        ]
    )
    criteria = JobCriteria(must_have_skills=["Golang", "Kotlin"])
    context = build_skill_match_context(criteria, matrix, effective)
    assert [match.coverage for match in context.matches] == ["covered", "gap"]


def test_load_overrides_missing_is_empty(tmp_path):
    overrides = load_overrides(tmp_path / "overrides.yaml")
    assert overrides.ban == [] and overrides.alias == {}


def test_apply_groups_uses_taxonomy_and_alias_aware_override_precedence():
    matrix = SkillMatrix(
        rows=[
            MatrixRow(key="python", display="Python"),
            MatrixRow(key="kubernetes", display="Kubernetes", aliases=["k8s"]),
            MatrixRow(key="mystery", display="Mystery"),
        ]
    )
    overrides = Overrides(group={"K8s": "devops-tooling"})
    apply_skill_groups(
        matrix,
        {"python": "languages", "kubernetes": "cloud-infra"},
        overrides,
    )
    assert {row.key: row.group for row in matrix.rows} == {
        "python": "languages",
        "kubernetes": "devops-tooling",
        "mystery": None,
    }


def test_group_validation_drops_unknown_values_without_expanding_override_tokens():
    matrix = SkillMatrix(
        rows=[MatrixRow(key="python", display="Python", group="invented")]
    )
    overrides = Overrides(
        group={"Python": "data-ml", "Terraform": "invented"},
    )
    assert matrix.rows[0].group is None
    assert overrides.group == {"python": "data-ml"}
    assert "python" not in override_tokens(overrides)
    apply_skill_groups(matrix, {"python": "invented"}, Overrides())
    assert matrix.rows[0].group is None
