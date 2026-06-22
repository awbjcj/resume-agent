"""Read-only match-gap: skills target jobs demand that the profile lacks."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.schemas.match_gap import GapOut, MatchGapOut
from resume_agent.profile.store import load_facts
from resume_agent.tracking.match_gap import match_gap

router = APIRouter()

_FACTS_PATH = "data/profile/facts.json"


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    if not Path(_FACTS_PATH).exists():
        return MatchGapOut(target_total=0, gaps=[])
    report = match_gap(session, load_facts(_FACTS_PATH))
    return MatchGapOut(
        target_total=report.target_total,
        gaps=[GapOut.model_validate(g) for g in report.gaps],
    )
