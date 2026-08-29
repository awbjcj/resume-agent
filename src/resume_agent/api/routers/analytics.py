"""Read-only conversion analytics: by source and by fit-band."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from datetime import timezone

from resume_agent.api.schemas.analytics import AnalyticsOut, CohortOut
from resume_agent.api.schemas.timeline_analytics import (
    CycleTimeOut,
    FlowEdgeOut,
    LaneEventOut,
    OfferOut,
    PipelineLaneOut,
    TimelineAnalyticsOut,
)
from resume_agent.tracking.analytics import fit_band_stats, source_stats
from resume_agent.tracking.funnel import stage_cycle_times, stage_flows
from resume_agent.tracking.timeline_pivot import build_pivot

router = APIRouter()


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(session: Session = Depends(get_session)):
    return AnalyticsOut(
        by_source=[CohortOut.model_validate(c) for c in source_stats(session)],
        by_band=[CohortOut.model_validate(c) for c in fit_band_stats(session)],
    )


@router.get("/analytics/timeline", response_model=TimelineAnalyticsOut)
def get_timeline_analytics(
    session: Session = Depends(get_session),
) -> TimelineAnalyticsOut:
    table = build_pivot(session, max_technical_rounds=None)
    active_pipeline: list[PipelineLaneOut] = []
    offers: list[OfferOut] = []
    for row in table.rows:
        dated_events = [event for event in row.events if event.occurred_at is not None]
        if row.status not in {"rejected", "closed"} and dated_events:
            active_pipeline.append(
                PipelineLaneOut(
                    job_id=row.job_id,
                    company=row.company,
                    title=row.title,
                    status=row.status,
                    events=[
                        LaneEventOut(
                            kind=event.kind,
                            sequence=event.sequence,
                            occurred_at=(
                                event.occurred_at.replace(tzinfo=timezone.utc)
                                if event.occurred_at.tzinfo is None
                                else event.occurred_at
                            ),
                            all_day=event.all_day,
                            result=event.result,
                        )
                        for event in dated_events
                    ],
                )
            )
        offer_events = [
            event
            for event in dated_events
            if event.kind == "offer_received"
            and any(
                value is not None
                for value in (
                    event.comp_base,
                    event.comp_bonus,
                    event.comp_equity_annual,
                    event.comp_signing,
                )
            )
        ]
        for offer in offer_events:
            parts = (
                offer.comp_base,
                offer.comp_bonus,
                offer.comp_equity_annual,
                offer.comp_signing,
            )
            total = sum(value for value in parts if value is not None)
            offers.append(
                OfferOut(
                    event_id=offer.id or 0,
                    job_id=row.job_id,
                    company=row.company,
                    sequence=offer.sequence,
                    occurred_at=(
                        offer.occurred_at.replace(tzinfo=timezone.utc)
                        if offer.occurred_at.tzinfo is None
                        else offer.occurred_at
                    ),
                    comp_base=offer.comp_base,
                    comp_bonus=offer.comp_bonus,
                    comp_equity_annual=offer.comp_equity_annual,
                    comp_signing=offer.comp_signing,
                    comp_currency=offer.comp_currency,
                    total_comp=total,
                )
            )
    offers.sort(key=lambda offer: offer.occurred_at, reverse=True)
    return TimelineAnalyticsOut(
        flows=[FlowEdgeOut.model_validate(edge) for edge in stage_flows(session)],
        cycle_times=[
            CycleTimeOut.model_validate(item) for item in stage_cycle_times(session)
        ],
        active_pipeline=active_pipeline,
        offers=offers,
    )
