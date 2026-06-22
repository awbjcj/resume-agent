"""Read-only conversion analytics: by source and by fit-band."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.schemas.analytics import AnalyticsOut, CohortOut
from resume_agent.tracking.analytics import fit_band_stats, source_stats

router = APIRouter()


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(session: Session = Depends(get_session)):
    return AnalyticsOut(
        by_source=[CohortOut.model_validate(c) for c in source_stats(session)],
        by_band=[CohortOut.model_validate(c) for c in fit_band_stats(session)],
    )
