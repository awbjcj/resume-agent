from resume_agent.api.schemas.analytics import AnalyticsOut, CohortOut
from resume_agent.tracking.analytics import CohortStat


def test_cohort_out_projects_rates_from_dto():
    dto = CohortStat(label="greenhouse", applications=10, responses=4, interviews=2, offers=1)
    out = CohortOut.model_validate(dto)
    assert out.label == "greenhouse"
    assert out.applications == 10
    assert out.interview_rate == 20  # derived property on the dataclass
    assert out.offer_rate == 10


def test_cohort_out_serializes_camelcase():
    dto = CohortStat(label="x", applications=1, responses=0, interviews=0, offers=0)
    body = CohortOut.model_validate(dto).model_dump(by_alias=True)
    assert "interviewRate" in body and "offerRate" in body and "responseRate" in body


def test_analytics_out_holds_two_cohort_lists():
    out = AnalyticsOut(by_source=[], by_band=[])
    assert out.model_dump(by_alias=True) == {"bySource": [], "byBand": []}
