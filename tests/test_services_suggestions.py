import pytest
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.github.repos import RepoMeta
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.services.suggestions import (
    SuggestionContext,
    SuggestionTargetNotFound,
    generate_suggestion,
    resolve_suggestion_context,
    suggestion_fingerprint,
)
from resume_agent.suggestions.agents import (
    ProjectIdea,
    RepoRef,
    ResourceRef,
    SuggestionDraft,
)
from resume_agent.tracking.match_gap import (
    DemandEdge,
    DemandGraph,
    JobLite,
    SkillNode,
    ThemeNode,
)
from resume_agent.tracking.tables import SkillSuggestion


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return _Result(self.content)


def _facts():
    return ProfileFacts(
        contact=Contact(name="A"),
        skills={"infrastructure": [Skill(name="Docker")]},
    )


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def _graph():
    return DemandGraph(
        target_total=2,
        clusters_stale=False,
        jobs=[
            JobLite(1, "Stripe", "Backend", "senior"),
            JobLite(2, "Datadog", "Platform", "mid"),
        ],
        skills=[
            SkillNode("Kubernetes", "infra", False),
            SkillNode("Terraform", "infra", False),
        ],
        edges=[
            DemandEdge(1, "Kubernetes", "must"),
            DemandEdge(2, "Kubernetes", "tech"),
            DemandEdge(2, "Terraform", "must"),
        ],
        themes=[ThemeNode("infra", "Cloud / Infrastructure")],
    )


def test_resolve_suggestion_context_uses_server_graph_for_skill_and_theme():
    skill = resolve_suggestion_context(_graph(), kind="skill", key="Kubernetes")
    theme = resolve_suggestion_context(_graph(), kind="theme", key="infra")

    assert skill.members == ("Kubernetes",)
    assert skill.demanding_job_ids == (1, 2)
    assert theme.label == "Cloud / Infrastructure"
    assert theme.members == ("Kubernetes", "Terraform")
    assert theme.demanding_job_ids == (1, 2)
    assert theme.jobs_context == "Stripe — Backend; Datadog — Platform"


def test_resolve_suggestion_context_rejects_unknown_target():
    with pytest.raises(SuggestionTargetNotFound):
        resolve_suggestion_context(_graph(), kind="theme", key="unknown")


def test_fingerprint_changes_with_coverage_members_and_jobs():
    context = SuggestionContext(
        kind="skill",
        key="Kubernetes",
        label="Kubernetes",
        members=("Kubernetes",),
        demanding_job_ids=(1,),
        jobs_context="Stripe — Backend",
    )

    baseline = suggestion_fingerprint(context, {"docker"})
    assert baseline != suggestion_fingerprint(context, {"docker", "kubernetes"})
    assert baseline != suggestion_fingerprint(
        SuggestionContext(**{**context.__dict__, "demanding_job_ids": (1, 2)}),
        {"docker"},
    )


def test_generate_grounds_links_verifies_repos_and_upserts():
    draft = SuggestionDraft(
        repos=[
            RepoRef(name="ok", url="https://github.com/foo/bar", why="Reference"),
            RepoRef(name="dead", url="https://github.com/foo/ghost", why="Dead"),
            RepoRef(name="ungrounded", url="https://github.com/foo/other", why="Missing"),
        ],
        resources=[
            ResourceRef(title="Docs", url="https://k8s.io/docs", kind="doc"),
            ResourceRef(title="Invented", url="https://example.com/invented", kind="tutorial"),
        ],
        project=ProjectIdea(
            title="Mini scheduler",
            summary="Build a scheduler",
            skills_demonstrated=["Go"],
        ),
        bridge="You already know Docker.",
    )

    def verify(_owner, name):
        if name == "bar":
            return RepoMeta("foo/bar", "https://github.com/foo/bar", 9, "A repo")
        return None

    context = resolve_suggestion_context(_graph(), kind="skill", key="Kubernetes")
    engine = _engine()
    with Session(engine) as session:
        row = generate_suggestion(
            session,
            context=context,
            search_agent=_Agent(
                "Research: https://github.com/foo/bar https://github.com/foo/ghost "
                "https://k8s.io/docs"
            ),
            formatter=_Agent(draft),
            verify=verify,
            facts=_facts(),
        )

        assert [repo["url"] for repo in row.payload_json["repos"]] == [
            "https://github.com/foo/bar"
        ]
        assert row.payload_json["repos"][0]["stars"] == 9
        assert [resource["url"] for resource in row.payload_json["resources"]] == [
            "https://k8s.io/docs"
        ]
        assert row.payload_json["project"]["title"] == "Mini scheduler"

        updated = generate_suggestion(
            session,
            context=context,
            search_agent=_Agent("Grounded prose"),
            formatter=_Agent(SuggestionDraft(bridge="Updated")),
            verify=verify,
            facts=_facts(),
        )
        rows = session.exec(
            select(SkillSuggestion).where(
                SkillSuggestion.kind == "skill",
                SkillSuggestion.key == "Kubernetes",
            )
        ).all()

    assert updated.id == row.id
    assert len(rows) == 1
    assert rows[0].payload_json["bridge"] == "Updated"


def test_generation_failure_preserves_last_good_cache():
    context = resolve_suggestion_context(_graph(), kind="skill", key="Kubernetes")
    engine = _engine()
    with Session(engine) as session:
        original = generate_suggestion(
            session,
            context=context,
            search_agent=_Agent("Grounded prose"),
            formatter=_Agent(SuggestionDraft(bridge="Keep me")),
            verify=lambda _owner, _name: None,
            facts=_facts(),
        )

        with pytest.raises(ValueError, match="empty suggestion"):
            generate_suggestion(
                session,
                context=context,
                search_agent=_Agent("Grounded prose"),
                formatter=_Agent(SuggestionDraft()),
                verify=lambda _owner, _name: None,
                facts=_facts(),
            )
        session.expire_all()
        cached = session.get(SkillSuggestion, original.id)

    assert cached is not None
    assert cached.payload_json["bridge"] == "Keep me"
