from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.build import BuildReport
from resume_agent.profile.manual_skills import ManualSkillEntry, ManualSkillsLedger, save_manual_skills
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts
from resume_agent.services.profile_build import run_corpus_build
from resume_agent.taxonomy.groups import group_map_path, load_group_map


def test_run_corpus_build_classifies_only_group_delta_in_active_data_root(
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
        "resume_agent.taxonomy.groups.build_group_classifier_agent",
    ):
        monkeypatch.setattr(target, lambda: object())

    calls: list[set[str]] = []

    def classify(tokens, _agent, batch_size=40):
        calls.append(set(tokens))
        return {
            "python": "languages",
            "kubernetes": "cloud-infra",
        }

    monkeypatch.setattr("resume_agent.taxonomy.groups.classify_missing_groups", classify)

    first = run_corpus_build(
        profile_dir=profile_dir,
        github_username=None,
        facts_out=facts_out,
    )
    assert calls == [{"python", "kubernetes"}]
    assert first["groupedRows"] == 2
    assert load_group_map(group_map_path(profile_dir)) == {
        "kubernetes": "cloud-infra",
        "python": "languages",
    }
    matrix = load_matrix(profile_dir / "matrix.json")
    assert matrix is not None
    assert {row.key: row.group for row in matrix.rows} == {
        "kubernetes": "cloud-infra",
        "python": "languages",
    }

    calls.clear()
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
        "resume_agent.taxonomy.groups.build_group_classifier_agent",
    ):
        monkeypatch.setattr(target, lambda: object())
    monkeypatch.setattr(
        "resume_agent.taxonomy.groups.classify_missing_groups", lambda *_a, **_k: {}
    )

    save_manual_skills(
        ManualSkillsLedger(
            entries=[ManualSkillEntry(name="Rust", added_at="2026-07-16T00:00:00+00:00")]
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
