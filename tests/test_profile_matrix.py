from datetime import date

from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_tailor_harness.profile.matrix import (
    MatrixRow,
    Overrides,
    SkillMatrix,
    apply_skill_groups,
    build_decorated_matrix,
    build_matrix,
    build_skill_match_context,
    decorate_matrix_groups,
    effective_cluster_map,
    load_matrix,
    load_overrides,
    override_tokens,
    rebuild_saved_matrix,
    save_matrix,
)
from resume_tailor_harness.profile.group_corrections import (
    GroupCorrection,
    GroupCorrections,
    corrections_path,
    save_group_corrections,
)
from resume_tailor_harness.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_tailor_harness.taxonomy.groups import group_map_path, save_group_map
from resume_tailor_harness.taxonomy.snapshot import EffectiveTaxonomy


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


def _taxonomy(
    cluster_map: ClusterMap | None = None,
    overrides: Overrides | None = None,
) -> EffectiveTaxonomy:
    return EffectiveTaxonomy.from_parts(
        cluster_map if cluster_map is not None else ClusterMap.empty(),
        overrides=overrides,
    )


def test_matrix_rows_are_canonical_with_deduplicated_evidence_and_recency():
    facts = _facts()
    matrix = build_matrix(facts, _taxonomy(ClusterMap.empty()), today=date(2026, 7, 1))
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
    matrix = build_matrix(facts, _taxonomy(cluster_map), today=date(2026, 7, 1))
    row = next(item for item in matrix.rows if item.key == "k8s")
    assert row.inferred is False


def test_overrides_ban_and_category():
    overrides = Overrides(ban=["mentorship"], category={"kubernetes": "hard"})
    matrix = build_matrix(
        _facts(), _taxonomy(ClusterMap.empty(), overrides), today=date(2026, 7, 1)
    )
    assert "mentorship" not in [row.key for row in matrix.rows]
    assert (
        next(row for row in matrix.rows if row.key == "kubernetes").category == "hard"
    )


def test_effective_cluster_map_force_then_forbid_wins():
    cluster_map = ClusterMap(
        aliases={"golang": "golang", "java": "jvm", "kotlin": "jvm"},
        domain_of={"golang": "languages", "jvm": "languages"},
    )
    overrides = Overrides(alias={"golang": "go"}, forbid_alias=[["java", "kotlin"]])
    fixed = effective_cluster_map(cluster_map, overrides)
    assert fixed.aliases["golang"] == "go"
    assert fixed.aliases["java"] == "java"
    assert fixed.aliases["kotlin"] == "kotlin"
    assert fixed.domain_of["java"] == "languages"
    assert fixed.domain_of["kotlin"] == "languages"


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
    first = build_matrix(facts, _taxonomy(ClusterMap.empty()), today=date(2026, 7, 1))
    second = build_matrix(facts, _taxonomy(ClusterMap.empty()), today=date(2026, 7, 1))
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
    taxonomy = _taxonomy(ClusterMap.empty())
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(original, taxonomy), path)
    changed = original.model_copy(deep=True)
    changed.skills["Platforms"][0].name = "Nomad"
    assert load_matrix(path, facts=changed) is None
    changed_map = ClusterMap(aliases={"k8s": "kubernetes"})
    assert load_matrix(path, facts=original, taxonomy=_taxonomy(changed_map)) is None


def test_build_matrix_pins_the_semantic_revision():
    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))

    matrix = build_matrix(facts, taxonomy)

    assert matrix.taxonomy_revision == taxonomy.semantic_revision
    assert matrix.taxonomy_manifest is not None
    assert [row.key for row in matrix.rows] == ["python"]


def test_load_matrix_rebuilds_a_legacy_matrix_with_no_revision(tmp_path):
    """A pre-contract cache is unknown even if its legacy hash looks fresh."""
    path = tmp_path / "matrix.json"
    save_matrix(SkillMatrix(rows=[MatrixRow(key="python", display="Python")]), path)
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))

    assert load_matrix(path, taxonomy=taxonomy) is None


def test_load_matrix_accepts_a_matching_revision(tmp_path):
    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, taxonomy), path)

    assert load_matrix(path, taxonomy=taxonomy) is not None


def test_a_regroup_timestamp_does_not_invalidate_a_saved_matrix(tmp_path):
    from resume_tailor_harness.taxonomy.state import GroupingStatus, TaxonomyState

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    cluster_map = ClusterMap(aliases={"py": "python"})
    before = EffectiveTaxonomy.from_parts(cluster_map)
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, before), path)
    after = EffectiveTaxonomy.from_parts(
        cluster_map,
        state=TaxonomyState(
            grouping_status={"rust": GroupingStatus(reason="uncertain")}
        ),
    )

    assert load_matrix(path, taxonomy=after) is not None


def test_a_ban_does_invalidate_a_saved_matrix(tmp_path):
    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    cluster_map = ClusterMap(aliases={"py": "python"})
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, EffectiveTaxonomy.from_parts(cluster_map)), path)
    banned = EffectiveTaxonomy.from_parts(
        cluster_map, overrides=Overrides(ban=["python"])
    )

    assert load_matrix(path, taxonomy=banned) is None


def test_canonical_map_sha256_is_still_written_for_old_readers():
    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})

    matrix = build_matrix(facts, EffectiveTaxonomy.from_parts(ClusterMap()))

    assert matrix.canonical_map_sha256


def test_undated_project_has_unknown_last_used():
    project = Project(name="API", tech=["FastAPI"])
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[project],
        skills={"Frameworks": [Skill(name="FastAPI")]},
    )
    matrix = build_matrix(facts, _taxonomy(ClusterMap.empty()))
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
    matrix = build_matrix(facts, _taxonomy(ClusterMap.empty()))
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
        domain_of={"fastapi": "web", "flask": "web", "django": "web"},
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
    overrides = Overrides(group={"K8s": "devops-automation"})
    apply_skill_groups(
        matrix,
        {"python": "languages", "kubernetes": "cloud-infra"},
        overrides.group,
    )
    assert {row.key: row.group for row in matrix.rows} == {
        "python": "languages",
        "kubernetes": "devops-automation",
        "mystery": None,
    }


def test_group_validation_drops_unknown_values_without_expanding_override_tokens():
    matrix = SkillMatrix(
        rows=[MatrixRow(key="python", display="Python", group="invented")]
    )
    overrides = Overrides(
        group={"Python": "ai-ml", "Terraform": "invented"},
    )
    assert matrix.rows[0].group is None
    assert overrides.group == {"python": "ai-ml"}
    assert "python" not in override_tokens(overrides)
    apply_skill_groups(matrix, {"python": "invented"}, Overrides().group)
    assert matrix.rows[0].group is None


def test_apply_groups_correction_beats_override_and_taxonomy():
    matrix = SkillMatrix(rows=[MatrixRow(key="python", display="Python")])

    apply_skill_groups(
        matrix,
        {"python": "languages"},
        Overrides(group={"python": "frontend-web"}).group,
        corrections={"python": "ai-ml"},
    )

    assert (matrix.rows[0].group, matrix.rows[0].group_source) == (
        "ai-ml",
        "correction",
    )


def test_apply_groups_records_override_taxonomy_and_none_sources():
    matrix = SkillMatrix(
        rows=[
            MatrixRow(key="python", display="Python"),
            MatrixRow(key="sql", display="SQL"),
            MatrixRow(key="mystery", display="Mystery"),
        ]
    )

    apply_skill_groups(
        matrix,
        {"python": "languages"},
        Overrides(group={"sql": "databases-storage"}).group,
    )

    by_key = {row.key: row for row in matrix.rows}
    assert (by_key["python"].group, by_key["python"].group_source) == (
        "languages",
        "taxonomy",
    )
    assert (by_key["sql"].group, by_key["sql"].group_source) == (
        "databases-storage",
        "override",
    )
    assert (by_key["mystery"].group, by_key["mystery"].group_source) == (None, None)


def test_apply_groups_uses_aliases_for_corrections_and_taxonomy():
    correction_row = MatrixRow(
        key="postgresql", display="PostgreSQL", aliases=["postgres"]
    )
    taxonomy_row = MatrixRow(key="kubernetes", display="Kubernetes", aliases=["k8s"])
    matrix = SkillMatrix(rows=[correction_row, taxonomy_row])

    apply_skill_groups(
        matrix,
        {"k8s": "cloud-infra"},
        Overrides().group,
        corrections={"postgres": "databases-storage"},
    )

    assert (correction_row.group, correction_row.group_source) == (
        "databases-storage",
        "correction",
    )
    assert (taxonomy_row.group, taxonomy_row.group_source) == (
        "cloud-infra",
        "taxonomy",
    )


def test_decorated_matrix_uses_the_canonical_tree_then_overrides_and_corrections(
    tmp_path,
):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python")]},
    )
    tree = ClusterMap(
        aliases={"python": "python"},
        domain_of={"python": "languages"},
        domain_label={"languages": "Languages"},
        category_of={"languages": "languages"},
    )
    save_cluster_map(tree, profile_dir / "cluster_map.json")
    # A conflicting legacy map must not override a canonical tree that exists.
    save_group_map({"python": "ai-ml"}, group_map_path(profile_dir))
    overrides = Overrides(group={"python": "frontend-web"})
    taxonomy = _taxonomy(tree, overrides)
    matrix = build_matrix(facts, taxonomy)

    decorate_matrix_groups(matrix, profile_dir, taxonomy)
    assert (matrix.rows[0].group, matrix.rows[0].group_source) == (
        "frontend-web",
        "override",
    )

    save_group_corrections(
        GroupCorrections(
            corrections={"python": GroupCorrection(group="databases-storage")}
        ),
        corrections_path(profile_dir),
    )
    decorate_matrix_groups(matrix, profile_dir, taxonomy)
    assert (matrix.rows[0].group, matrix.rows[0].group_source) == (
        "databases-storage",
        "correction",
    )


def test_matrix_row_without_valid_group_source_still_loads():
    assert (
        MatrixRow.model_validate({"key": "python", "display": "Python"}).group_source
        is None
    )
    assert (
        MatrixRow.model_validate(
            {"key": "python", "display": "Python", "group_source": "bogus"}
        ).group_source
        is None
    )


def test_build_decorated_matrix_does_not_persist_and_rebuild_does(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python")]},
    )
    save_group_corrections(
        GroupCorrections(corrections={"python": GroupCorrection(group="ai-ml")}),
        corrections_path(profile_dir),
    )

    matrix = build_decorated_matrix(profile_dir, facts)

    assert (matrix.rows[0].group, matrix.rows[0].group_source) == (
        "ai-ml",
        "correction",
    )
    assert not (profile_dir / "matrix.json").exists()

    rebuilt = rebuild_saved_matrix(profile_dir, facts)
    reloaded = load_matrix(profile_dir / "matrix.json")
    assert rebuilt.rows[0].group_source == "correction"
    assert reloaded is not None
    assert (reloaded.rows[0].group, reloaded.rows[0].group_source) == (
        "ai-ml",
        "correction",
    )
