from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class DashboardSummaryOut(CamelModel):
    status_counts: dict[str, int]
    queues: dict[str, int]
    applied: int
