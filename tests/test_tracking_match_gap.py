from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.match_gap import (
    GapRow,
    MatchGapReport,
    match_gap,
    normalize_skill,
    profile_skill_tokens,
)
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(session, status, must_have):
    return save_job(
        session,
        Job(
            source="manual",
            company="C",
            title="T",
            status=status,
            criteria_json={"must_have_skills": must_have},
        ),
    )


def _facts(skills):
    return ProfileFacts(contact=Contact(name="A"), skills=skills)


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize_skill("  Kubernetes  ") == "kubernetes"
    assert normalize_skill("Amazon  Web   Services") == "amazon web services"


def test_normalize_keeps_plus_hash_dot_drops_other_punct():
    assert normalize_skill("C++") == "c++"
    assert normalize_skill("C#") == "c#"
    assert normalize_skill("Node.js") == "node.js"
    assert normalize_skill("CI/CD") == "ci cd"


def test_profile_skill_tokens_includes_names_and_aliases():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        skills={
            "languages": [Skill(name="Python"), Skill(name="Go")],
            "infra": [Skill(name="Kubernetes", aliases=["k8s", "K8S"])],
        },
    )

    assert profile_skill_tokens(facts) == {"python", "go", "kubernetes", "k8s"}


def test_profile_skill_tokens_empty_profile():
    assert profile_skill_tokens(ProfileFacts(contact=Contact(name="A"))) == set()


def test_match_gap_aggregates_by_frequency():
    with _session() as session:
        _job(session, JobStatus.shortlisted.value, ["Kubernetes", "Python"])
        _job(session, JobStatus.approved.value, ["Kubernetes", "Go"])

        report = match_gap(session, _facts({"lang": [Skill(name="Python")]}))

        assert report.target_total == 2
        pairs = [(g.skill, g.demand_count) for g in report.gaps]
        assert pairs[0] == ("Kubernetes", 2)
        assert ("Go", 1) in pairs
        assert all(g.skill != "Python" for g in report.gaps)


def test_match_gap_excludes_pre_shortlist_jobs():
    with _session() as session:
        _job(session, JobStatus.filtered.value, ["Rust"])
        _job(session, JobStatus.rejected.value, ["Scala"])
        _job(session, JobStatus.shortlisted.value, ["Kubernetes"])

        report = match_gap(session, _facts({}))

        assert report.target_total == 1
        assert {g.skill for g in report.gaps} == {"Kubernetes"}


def test_match_gap_alias_is_not_a_gap():
    with _session() as session:
        job = _job(session, JobStatus.shortlisted.value, ["k8s"])

        report = match_gap(
            session,
            _facts({"infra": [Skill(name="Kubernetes", aliases=["k8s"])]}),
        )

        assert report.gaps == []
        assert report.per_job[job.id] == []


def test_match_gap_per_job_lists_missing():
    with _session() as session:
        job = _job(session, JobStatus.shortlisted.value, ["Kubernetes", "Python"])

        report = match_gap(session, _facts({"lang": [Skill(name="Python")]}))

        assert report.per_job[job.id] == ["Kubernetes"]


def test_match_gap_honors_canonicalizer():
    with _session() as session:
        _job(session, JobStatus.shortlisted.value, ["k8s"])

        def canon(tokens):
            return {t: ("kubernetes" if t in {"k8s", "kubernetes"} else t) for t in tokens}

        report = match_gap(
            session,
            _facts({"infra": [Skill(name="Kubernetes")]}),
            canonicalizer=canon,
        )

        assert report.gaps == []


def test_match_gap_empty_db():
    with _session() as session:
        report = match_gap(session, _facts({}))

        assert report == MatchGapReport(target_total=0, gaps=[], per_job={})


def test_gap_row_demand_share():
    assert GapRow(skill="X", demand_count=2, target_total=3).demand_share == 67
