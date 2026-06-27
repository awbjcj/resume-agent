from resume_agent.api.schemas.match_gap import (
    DemandEdgeOut,
    MatchGapOut,
    SkillNodeOut,
)
from resume_agent.tracking.match_gap import DemandEdge, SkillNode


def test_skill_node_out_camelizes_theme_id():
    out = SkillNodeOut.model_validate(SkillNode("Kubernetes", "t1", False))
    assert out.model_dump(by_alias=True) == {
        "skill": "Kubernetes",
        "themeId": "t1",
        "covered": False,
    }


def test_demand_edge_out_camelizes_job_id():
    out = DemandEdgeOut.model_validate(DemandEdge(7, "Go", "must"))
    assert out.model_dump(by_alias=True) == {
        "jobId": 7,
        "skill": "Go",
        "source": "must",
    }


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
    }
