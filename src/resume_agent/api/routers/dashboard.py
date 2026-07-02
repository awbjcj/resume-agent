from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.schemas.dashboard import DashboardSummaryOut
from resume_agent.services.dashboard import summarize_dashboard

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(session: Session = Depends(get_session)):
    return DashboardSummaryOut.model_validate(summarize_dashboard(session))
