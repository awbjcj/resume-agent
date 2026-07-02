from datetime import datetime, timezone

from resume_agent.api.schemas.match_gap import (
    DemandEdgeOut,
    MatchGapOut,
    SkillNodeOut,
    SuggestionStatusOut,
    ThemeOut,
)
from resume_agent.tracking.match_gap import DemandEdge, SkillNode, ThemeNode


def test_skill_node_out_camelizes_stable_identity_and_counts():
    out = SkillNodeOut.model_validate(
        SkillNode(
            "Kubernetes",
            "t1",
            False,
            "kubernetes",
            {"K8s": 1, "Kubernetes": 2},
            must=2,
            nice=1,
            job_count=2,
        )
    )
    assert out.model_dump(by_alias=True) == {
        "skill": "Kubernetes",
        "themeId": "t1",
        "covered": False,
        "coverage": "gap",
        "key": "kubernetes",
        "members": {"K8s": 1, "Kubernetes": 2},
        "must": 2,
        "nice": 1,
        "tech": 0,
        "jobCount": 2,
    }


def test_demand_edge_out_camelizes_stable_skill_key():
    out = DemandEdgeOut.model_validate(DemandEdge(7, "Go", "must", "go"))
    assert out.model_dump(by_alias=True) == {
        "jobId": 7,
        "skill": "Go",
        "source": "must",
        "skillKey": "go",
    }


def test_theme_and_suggestion_status_out_use_named_fields():
    theme = ThemeOut.model_validate(ThemeNode("backend", "Backend", 9, 3, 2, 2, 1))
    generated_at = datetime(2026, 6, 27, tzinfo=timezone.utc)
    status = SuggestionStatusOut(
        kind="skill",
        key="python",
        state="ready",
        generated_at=generated_at,
    )

    assert theme.model_dump(by_alias=True) == {
        "id": "backend",
        "label": "Backend",
        "essentialScore": 9,
        "popularScore": 3,
        "jobCount": 2,
        "skillCount": 2,
        "gapCount": 1,
        "adjacentCount": 0,
    }
    assert status.model_dump(by_alias=True)["generatedAt"] == generated_at


def test_match_gap_out_shape():
    out = MatchGapOut(
        target_total=0,
        clusters_stale=False,
        jobs=[],
        skills=[],
        edges=[],
        themes=[],
    )
    dumped = out.model_dump(by_alias=True)
    assert set(dumped) == {
        "targetTotal",
        "clustersStale",
        "jobs",
        "skills",
        "edges",
        "themes",
        "suggestionStatuses",
    }
    assert dumped["suggestionStatuses"] == []


def test_skill_node_out_serializes_adjacent_coverage():
    node = SkillNodeOut(
        skill="FastAPI",
        coverage="adjacent",
        covered=False,
        key="fastapi",
        members={"FastAPI": 1},
        must=1,
        nice=0,
        tech=0,
        job_count=1,
    )
    assert node.model_dump(by_alias=True)["coverage"] == "adjacent"
