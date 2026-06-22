from resume_agent.api.schemas.match_gap import GapOut, MatchGapOut
from resume_agent.tracking.match_gap import GapRow


def test_gap_out_projects_demand_share():
    dto = GapRow(skill="Kubernetes", demand_count=3, target_total=4)
    out = GapOut.model_validate(dto)
    assert out.skill == "Kubernetes"
    assert out.demand_count == 3
    assert out.demand_share == 75  # derived property


def test_gap_out_serializes_camelcase():
    body = GapOut.model_validate(GapRow(skill="Go", demand_count=1, target_total=2)).model_dump(
        by_alias=True
    )
    assert set(body) == {"skill", "demandCount", "targetTotal", "demandShare"}


def test_match_gap_out_shape():
    out = MatchGapOut(target_total=0, gaps=[])
    assert out.model_dump(by_alias=True) == {"targetTotal": 0, "gaps": []}
