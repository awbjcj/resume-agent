from __future__ import annotations

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.taxonomy.term_corrections import TermTypeCorrection
from resume_agent.taxonomy.term_typing import TermSource, type_term


def _correction(source: TermSource) -> TermTypeCorrection:
    decision = type_term(source)
    assert decision.concept_type == "unknown"
    return TermTypeCorrection.create(
        actor_id="reviewer:1",
        scope="profile",
        action="set_type",
        subject_decision_id=decision.id,
        prior_type="unknown",
        new_type="capability",
        rationale="Reviewed as a demonstrated cross-functional capability",
        evidence_refs=["review:1"],
        target_revision=decision.policy_revision,
        timestamp="2026-08-19T12:00:00+00:00",
    )


def test_profile_rebuild_replays_the_effective_term_type_correction(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.profile.matrix import build_matrix
    from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
    from resume_agent.taxonomy.term_corrections import save_term_type_corrections

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    save_cluster_map(ClusterMap(), profile_dir / "cluster_map.json")
    skill = Skill(id="skill:stakeholder", name="Stakeholder orchestration")
    facts = ProfileFacts(contact=Contact(name="Ada"), skills={"hard": [skill]})
    source = TermSource.without_offsets(
        source_kind="profile_skill",
        source_id=skill.id,
        original_text=skill.name,
    )
    term_path = tmp_path / "taxonomy" / "term_type_corrections.json"
    save_term_type_corrections([_correction(source)], term_path)

    before = build_effective_taxonomy(
        profile_dir,
        corrections_path=tmp_path / "missing-taxonomy-corrections.json",
        term_corrections_path=tmp_path / "missing-term-corrections.json",
    )
    after = build_effective_taxonomy(
        profile_dir,
        corrections_path=tmp_path / "missing-taxonomy-corrections.json",
        term_corrections_path=term_path,
    )
    matrix = build_matrix(facts, after)

    assert before.semantic_revision != after.semantic_revision
    assert after.manifest.term_type_corrections
    assert matrix.assertions[0].concept_type == "capability"
    assert matrix.assertions[0].term_decision_id == _correction(source).subject_decision_id


def test_job_requirement_binding_replays_the_scoped_term_type_correction():
    from resume_agent.discovery.requirements import bind_job_requirements

    text = "Stakeholder orchestration"
    jd_text = f"This role requires {text}."
    start = jd_text.index(text)
    source = TermSource.from_text(
        source_kind="job_description",
        source_id="job:42:must:0",
        source_text=jd_text,
        original_text=text,
        start=start,
    )

    bound = bind_job_requirements(
        JobCriteria(must_have_skills=[text]),
        job_id=42,
        jd_text=jd_text,
        taxonomy_revision="taxonomy-v1",
        term_corrections=[_correction(source)],
    )

    requirement = bound.typed_requirements[0]
    assert requirement.concept_type == "capability"
    assert requirement.term_decision_id == _correction(source).subject_decision_id
    assert requirement.parsed_concept_id is not None


def test_correction_application_service_rebuilds_the_profile_artifact(tmp_path):
    from resume_agent.profile.matrix import load_matrix
    from resume_agent.profile.store import save_facts
    from resume_agent.services.term_typing import correct_term_and_rebuild_profile
    from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map

    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    skill = Skill(id="skill:leadership", name="Leadership")
    save_facts(
        ProfileFacts(contact=Contact(name="Ada"), skills={"hard": [skill]}),
        facts_path,
    )
    save_cluster_map(ClusterMap(), profile_dir / "cluster_map.json")
    source = TermSource.without_offsets(
        source_kind="profile_skill",
        source_id=skill.id,
        original_text=skill.name,
    )
    decision = type_term(source)

    corrected = correct_term_and_rebuild_profile(
        source,
        decision_id=decision.id,
        new_type="capability",
        rationale="Reviewed candidate evidence",
        evidence_refs=["review:1"],
        actor_id="reviewer:1",
        corrections_path=tmp_path / "taxonomy" / "term_type_corrections.json",
        profile_dir=profile_dir,
        facts_path=facts_path,
    )

    matrix = load_matrix(profile_dir / "matrix.json")
    assert corrected.concept_type == "capability"
    assert matrix is not None
    assert matrix.assertions[0].concept_type == "capability"
    assert matrix.term_type_corrections[0].subject_decision_id == decision.id


def test_job_scoped_correction_rebinds_the_persisted_requirements(tmp_path):
    from sqlmodel import Session, SQLModel, create_engine

    from resume_agent.discovery.requirements import bind_job_requirements
    from resume_agent.profile.store import save_facts
    from resume_agent.services.term_typing import correct_term_and_rebuild_profile
    from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    save_facts(ProfileFacts(contact=Contact(name="Ada")), facts_path)
    save_cluster_map(ClusterMap(), profile_dir / "cluster_map.json")
    text = "Stakeholder orchestration"
    jd_text = f"This role requires {text}."
    criteria = bind_job_requirements(
        JobCriteria(must_have_skills=[text]),
        job_id=1,
        jd_text=jd_text,
        taxonomy_revision="before",
    )
    requirement = criteria.typed_requirements[0]
    source = TermSource.from_text(
        source_kind="job_description",
        source_id="job:1:must:0",
        source_text=jd_text,
        original_text=text,
        start=jd_text.index(text),
    )
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        job = save_job(
            session,
            Job(source="manual", jd_text=jd_text, criteria_json=criteria.model_dump(mode="json")),
        )
        assert job.id == 1

        correct_term_and_rebuild_profile(
            source,
            decision_id=requirement.term_decision_id,
            new_type="capability",
            rationale="Reviewed requirement semantics",
            evidence_refs=["review:job:1"],
            actor_id="reviewer:1",
            corrections_path=tmp_path / "taxonomy" / "term_type_corrections.json",
            profile_dir=profile_dir,
            facts_path=facts_path,
            session=session,
        )

        session.refresh(job)
        rebound = JobCriteria.model_validate(job.criteria_json)
        assert rebound.typed_requirements[0].concept_type == "capability"
        assert rebound.typed_requirements[0].taxonomy_revision != "before"
