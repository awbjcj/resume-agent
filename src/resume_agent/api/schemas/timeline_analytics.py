"""Wire contracts for application pivots and timeline analytics."""

from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class PivotCellOut(CamelModel):
    occurred_at: datetime | None
    all_day: bool
    result: str
    modality: str | None
    platform: str | None
    platform_other: str | None
    interviewers: str | None
    notes: str | None


class PivotRowOut(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    status: str
    source: str
    fit_score: int | None
    cells: dict[str, PivotCellOut]
    custom_count: int
    total_comp: int | None
    comp_currency: str | None
    offer_deadline: datetime | None
    overflow_rounds: int = 0


class PivotTableOut(CamelModel):
    rows: list[PivotRowOut]
    technical_round_columns: int


class FlowEdgeOut(CamelModel):
    source: str
    target: str
    count: int


class CycleTimeOut(CamelModel):
    from_kind: str
    to_kind: str
    median_days: float
    sample_size: int


class LaneEventOut(CamelModel):
    kind: str
    sequence: int
    occurred_at: datetime
    all_day: bool
    result: str


class PipelineLaneOut(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    status: str
    events: list[LaneEventOut]


class OfferOut(CamelModel):
    event_id: int
    job_id: int
    company: str | None
    sequence: int
    occurred_at: datetime
    comp_base: int | None
    comp_bonus: int | None
    comp_equity_annual: int | None
    comp_signing: int | None
    comp_currency: str | None
    total_comp: int


class TimelineAnalyticsOut(CamelModel):
    flows: list[FlowEdgeOut]
    cycle_times: list[CycleTimeOut]
    active_pipeline: list[PipelineLaneOut]
    offers: list[OfferOut]
