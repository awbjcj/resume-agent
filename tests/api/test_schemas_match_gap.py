from datetime import datetime, timezone

from resume_agent.api.schemas.match_gap import (
    CategoryOut,
    DemandEdgeOut,
    DomainOut,
    MatchGapOut,
    RefreshClustersIn,
    SkillNodeOut,
    SuggestionStatusOut,
)
from resume_agent.tracking.match_gap import DemandEdge, DomainNode, SkillNode


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
        "domainId": "t1",
        "covered": False,
        "coverage": "gap",
        "key": "kubernetes",
        "members": {"K8s": 1, "Kubernetes": 2},
        "must": 2,
        "nice": 1,
        "tech": 0,
        "jobCount": 2,
        "groupingStatus": None,
    }


def test_demand_edge_out_camelizes_stable_skill_key():
    out = DemandEdgeOut.model_validate(DemandEdge(7, "Go", "must", "go"))
    assert out.model_dump(by_alias=True) == {
        "jobId": 7,
        "skill": "Go",
        "source": "must",
        "skillKey": "go",
    }


def test_domain_category_and_suggestion_status_use_named_fields():
    domain = DomainOut.model_validate(
        DomainNode("backend", "Backend", 9, 3, 2, 2, 1, category="backend-apis")
    )
    category = CategoryOut(slug="backend-apis", label="Backend & APIs", kind="hard")
    generated_at = datetime(2026, 6, 27, tzinfo=timezone.utc)
    status = SuggestionStatusOut(
        kind="skill",
        key="python",
        state="ready",
        generated_at=generated_at,
    )

    assert domain.model_dump(by_alias=True) == {
        "id": "backend",
        "label": "Backend",
        "category": "backend-apis",
        "essentialScore": 9,
        "popularScore": 3,
        "jobCount": 2,
        "skillCount": 2,
        "gapCount": 1,
        "adjacentCount": 0,
    }
    assert category.model_dump(by_alias=True) == {
        "slug": "backend-apis",
        "label": "Backend & APIs",
        "kind": "hard",
    }
    assert status.model_dump(by_alias=True)["generatedAt"] == generated_at


def test_match_gap_out_shape():
    out = MatchGapOut(
        target_total=0,
        clusters_stale=False,
        jobs=[],
        skills=[],
        edges=[],
        domains=[],
        categories=[],
    )
    dumped = out.model_dump(by_alias=True)
    assert set(dumped) == {
        "targetTotal",
        "clustersStale",
        "jobs",
        "skills",
        "edges",
        "domains",
        "categories",
        "suggestionStatuses",
        "taxonomyGeneration",
        "taxonomyAlgorithmVersion",
        "taxonomyMaintenanceDue",
        "unassignedCount",
        "taxonomyUndoAvailable",
        "taxonomyRevision",
        "taxonomyManifest",
        "overrideConflicts",
        "retiredSkills",
    }
    assert dumped["suggestionStatuses"] == []
    assert dumped["taxonomyAlgorithmVersion"] == "legacy"
    assert dumped["taxonomyRevision"] == ""
    assert dumped["taxonomyManifest"] is None
    assert dumped["overrideConflicts"] == []


def test_refresh_cluster_input_normalizes_deduplicates_and_bounds_keys():
    request = RefreshClustersIn(skill_keys=[" Python ", "python", "C++"])

    assert request.skill_keys == ["python", "c++"]


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
