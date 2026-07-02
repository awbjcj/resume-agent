from typing import Literal

from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
    TailoredSkill,
)
from resume_agent.models.review import Severity
from resume_agent.tailor.provenance import (
    ProvenanceReport,
    check_provenance,
    index_facts,
    provenance_critique,
    referenced_ids,
    resolve_evidence,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Engineer",
                bullets=[Bullet(id="b1", text="Built X")],
            )
        ],
        projects=[Project(id="p1", name="Looms")],
        skills={"languages": [Skill(id="s1", name="Python")]},
    )


def _content(bullet_prov="b1", skill_prov="s1") -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[TailoredBullet(text="Built X", provenance=bullet_prov)],
            )
        ],
        projects=[TailoredProject(name="Looms", provenance="p1")],
        skills={"languages": [TailoredSkill(name="Python", provenance=skill_prov)]},
    )


def test_index_facts_collects_every_id():
    idx = index_facts(_facts())
    assert set(idx) == {"e1", "b1", "p1", "s1"}


def test_referenced_ids_walks_content():
    assert referenced_ids(_content()) == {"e1", "b1", "p1", "s1"}


def test_check_provenance_passes_when_all_resolve():
    report = check_provenance(_content(), _facts())
    assert isinstance(report, ProvenanceReport)
    assert report.ok is True
    assert report.missing == []


def test_check_provenance_flags_fabricated_id():
    report = check_provenance(_content(bullet_prov="ghost999"), _facts())
    assert report.ok is False
    assert report.missing == ["ghost999"]


def test_provenance_critique_passes_for_clean_content():
    crit = provenance_critique(_content(), _facts())
    assert crit.reviewer == "provenance"
    assert crit.passed is True
    assert crit.score == 100
    assert crit.issues == []


def test_provenance_critique_blocks_fabricated_id():
    crit = provenance_critique(_content(bullet_prov="ghost999"), _facts())
    assert crit.passed is False
    assert crit.score == 0
    assert crit.issues[0].severity == Severity.blocking
    assert "ghost999" in crit.issues[0].message


def test_resolve_evidence_returns_only_referenced_facts():
    facts = _facts()
    facts.skills["languages"].append(Skill(id="s2", name="Rust"))
    evidence = resolve_evidence(_content(), facts)
    assert set(evidence) == {"e1", "b1", "p1", "s1"}
    assert evidence["b1"]["text"] == "Built X"
    assert "s2" not in evidence


def _facts_with_inferred_skill(
    *,
    category: Literal["hard", "soft", "domain"] = "hard",
    evidence_fact_ids=None,
) -> tuple[ProfileFacts, Skill]:
    bullet = Bullet(id="proof", text="Deployed services on Kubernetes")
    skill = Skill(
        id="inferred",
        name="Kubernetes",
        inferred=True,
        category=category,
        evidence_fact_ids=[bullet.id] if evidence_fact_ids is None else evidence_fact_ids,
    )
    return (
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="e1", company="Acme", title="Engineer", bullets=[bullet]
                )
            ],
            projects=[Project(id="p1", name="Looms")],
            skills={category: [skill]},
        ),
        skill,
    )


def test_resolve_evidence_expands_inferred_skill_evidence():
    facts, skill = _facts_with_inferred_skill()
    content = _content(bullet_prov="proof", skill_prov=skill.id)
    evidence = resolve_evidence(content, facts)
    assert skill.id in evidence
    assert "proof" in evidence


def test_valid_inferred_hard_skill_is_allowed_only_in_skills_section():
    facts, skill = _facts_with_inferred_skill()
    assert provenance_critique(
        _content(bullet_prov="proof", skill_prov=skill.id), facts
    ).passed is True
    assert (
        provenance_critique(_content(bullet_prov=skill.id, skill_prov=skill.id), facts).passed
        is False
    )


def test_inferred_soft_or_domain_skill_is_rejected_from_skills_section():
    for category in ("soft", "domain"):
        facts, skill = _facts_with_inferred_skill(category=category)
        assert provenance_critique(
            _content(bullet_prov="proof", skill_prov=skill.id), facts
        ).passed is False


def test_inferred_skill_with_empty_or_missing_evidence_is_rejected():
    facts, _ = _facts_with_inferred_skill()
    empty = Skill.model_construct(
        id="empty",
        name="Kubernetes",
        inferred=True,
        category="hard",
        evidence_fact_ids=[],
    )
    facts.skills = {"hard": [empty]}
    assert provenance_critique(
        _content(bullet_prov="proof", skill_prov=empty.id), facts
    ).passed is False

    missing_facts, missing = _facts_with_inferred_skill(
        evidence_fact_ids=["does-not-exist"]
    )
    assert provenance_critique(
        _content(bullet_prov="proof", skill_prov=missing.id), missing_facts
    ).passed is False


def test_inferred_to_inferred_evidence_is_rejected():
    facts, backing = _facts_with_inferred_skill()
    derived = Skill(
        id="derived",
        name="Cloud Native",
        inferred=True,
        category="hard",
        evidence_fact_ids=[backing.id],
    )
    facts.skills["hard"].append(derived)
    assert provenance_critique(
        _content(bullet_prov="proof", skill_prov=derived.id), facts
    ).passed is False
