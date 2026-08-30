"""Compare two or three roles using only stored evidence."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.role_comparison import (
    RoleComparisonIn,
    RoleComparisonItemOut,
    RoleComparisonOut,
)
from resume_agent.services.role_comparison import compare_roles

router = APIRouter()


@router.post(
    "/jobs/company-intelligence-comparisons", response_model=RoleComparisonOut
)
def create_role_comparison(
    body: RoleComparisonIn, session: Session = Depends(get_session)
) -> RoleComparisonOut:
    try:
        items = compare_roles(session, body.job_ids)
    except LookupError as exc:
        raise ApiException(404, "COMPARISON_JOB_NOT_FOUND", str(exc)) from exc
    return RoleComparisonOut(items=[RoleComparisonItemOut.from_item(item) for item in items])
