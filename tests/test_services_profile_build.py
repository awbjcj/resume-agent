from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.build import BuildReport
from resume_agent.profile.manual_skills import (
    ManualSkillEntry,
    ManualSkillsLedger,
    save_manual_skills,
)
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.profile.store import load_facts
from resume_agent.services.profile_build import run_corpus_build
from resume_agent.taxonomy.groups import group_map_path, load_group_map
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.state import load_taxonomy_state


def test_run_corpus_build_derives_groups_from_the_shared_taxonomy_tree(
    tmp_path, monkeypatch
):
    profile_dir = tmp_path / "data" / "profile"
    facts_out = profile_dir / "facts.json"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "Languages": [Skill(name="Python")],
            "Platforms": [Skill(name="Kubernetes")],
        },
    )

    def fake_build(*_args, **_kwargs):
        return facts, BuildReport()

    monkeypatch.setattr("resume_agent.profile.build.build_corpus_profile", fake_build)
    for target in (
        "resume_agent.profile.inference.build_inference_agent",
        "resume_agent.profile.merge.build_bullet_dedup_agent",
        "resume_agent.profile.synthesis.build_synthesis_agent",
        "resume_agent.profile.synthesis.build_entailment_agent",
        "resume_agent.profile.project_extractor.build_project_extractor_agent",
        "resume_agent.tracking.canonicalize.build_incremental_canonicalizer_agent",
        "resume_agent.tracking.canonicalize.build_incremental_themer_agent",
    ):
        monkeypatch.setattr(target, lambda: object())

    legacy_path = group_map_path(profile_dir)
    from resume_agent.taxonomy.groups import save_group_map

    save_group_map({"python": "languages", "kubernetes": "cloud-infra"}, legacy_path)
    calls: list[set[str]] = []
    hints: list[dict[str, str]] = []

    def refresh(_session, *, path, demanded_tokens, category_hints, **_kwargs):
        calls.append(set(demanded_tokens))
        hints.append(category_hints)
        save_cluster_map(
            ClusterMap(
                aliases={token: token for token in demanded_tokens},
                domain_of={"python": "languages", "kubernetes": "infra"},
                domain_label={"languages": "Languages", "infra": "Infrastructure"},
                category_of={"languages": "languages", "infra": "cloud-infra"},
            ),
            path,
        )
        return {}

    monkeypatch.setattr("resume_agent.services.match_gap.refresh_clusters", refresh)

    first = run_corpus_build(
        profile_dir=profile_dir,
        github_username=None,
        facts_out=facts_out,
    )
    assert calls == [{"python", "kubernetes"}]
    assert first["groupedRows"] == 2
    assert hints == [{"kubernetes": "cloud-infra", "python": "languages"}]
    assert load_group_map(legacy_path) == {
        "kubernetes": "cloud-infra",
        "python": "languages",
    }
    assert load_taxonomy_state(profile_dir / "cluster_map.json").legacy_group_map_sha256
    matrix = load_matrix(profile_dir / "matrix.json")
    assert matrix is not None
    assert matrix.taxonomy_revision == build_effective_taxonomy(
        profile_dir
    ).semantic_revision
    assert {row.key: row.group for row in matrix.rows} == {
        "kubernetes": "cloud-infra",
        "python": "languages",
    }

    calls.clear()
    # Once the legacy artifact has been imported, neither the build path nor
    # the matrix decorator may consult it again.  A later edit is deliberately
    # not an implicit taxonomy correction.
    monkeypatch.setattr(
        "resume_agent.taxonomy.groups.load_group_map",
        lambda _path: (_ for _ in ()).throw(AssertionError("legacy map reread")),
    )
    run_corpus_build(
        profile_dir=profile_dir,
        github_username=None,
        facts_out=facts_out,
    )
    assert calls == []


def test_run_corpus_build_replays_manual_skills_onto_fresh_facts(tmp_path, monkeypatch):
    profile_dir = tmp_path / "data" / "profile"
    facts_out = profile_dir / "facts.json"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python")]},
    )

    monkeypatch.setattr(
        "resume_agent.profile.build.build_corpus_profile",
        lambda *_a, **_k: (facts, BuildReport()),
    )
    for target in (
        "resume_agent.profile.inference.build_inference_agent",
        "resume_agent.profile.merge.build_bullet_dedup_agent",
        "resume_agent.profile.synthesis.build_synthesis_agent",
        "resume_agent.profile.synthesis.build_entailment_agent",
        "resume_agent.profile.project_extractor.build_project_extractor_agent",
        "resume_agent.tracking.canonicalize.build_incremental_canonicalizer_agent",
        "resume_agent.tracking.canonicalize.build_incremental_themer_agent",
    ):
        monkeypatch.setattr(target, lambda: object())

    def refresh(_session, *, path, demanded_tokens, **_kwargs):
        save_cluster_map(
            ClusterMap(
                aliases={token: token for token in demanded_tokens},
                domain_of={token: "languages" for token in demanded_tokens},
                domain_label={"languages": "Languages"},
                category_of={"languages": "languages"},
            ),
            path,
        )
        return {}

    monkeypatch.setattr("resume_agent.services.match_gap.refresh_clusters", refresh)

    save_manual_skills(
        ManualSkillsLedger(
            entries=[
                ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00")
            ]
        ),
        profile_dir / "manual_skills.json",
    )

    run_corpus_build(profile_dir=profile_dir, github_username=None, facts_out=facts_out)

    rebuilt = load_facts(facts_out)
    assert "Manually added" not in rebuilt.skills
    assert any(s.name == "Rust" for s in rebuilt.skills["hard"])


def test_run_corpus_build_validates_repo_limit(tmp_path):
    for limit in (0, 101):
        try:
            run_corpus_build(
                profile_dir=tmp_path / "profile",
                github_username=None,
                facts_out=tmp_path / "profile" / "facts.json",
                github_limit=limit,
            )
        except ValueError as error:
            assert "limit" in str(error)
        else:
            raise AssertionError("invalid github limit was accepted")
