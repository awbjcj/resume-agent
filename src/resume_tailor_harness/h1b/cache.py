"""Batched read access to the durable per-company H-1B evidence cache."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from sqlmodel import Session, select

from resume_tailor_harness.h1b.models import H1BSponsorshipEvidence
from resume_tailor_harness.taxonomy.industries import normalize_company
from resume_tailor_harness.tracking.tables import H1BCompanyEvidence

logger = logging.getLogger(__name__)


def load_company_evidence(
    session: Session, companies: Sequence[str | None]
) -> dict[str, H1BSponsorshipEvidence]:
    """Load cached evidence for these company labels, keyed by normalized name.

    One query for the whole batch -- callers derive the map once per request and
    pass it down, never per row.

    Expired rows are returned like any other: expiry is a display concern (the
    caller labels them stale), not a filter. A row whose ``evidence_json`` no
    longer validates is skipped rather than raised, so a single corrupt cache
    row can never fail a whole board page.
    """
    keys = {
        key
        for key in (normalize_company(company) for company in companies if company)
        if key
    }
    if not keys:
        return {}
    column = cast(Any, H1BCompanyEvidence.normalized_company)
    rows = session.exec(
        select(H1BCompanyEvidence).where(column.in_(sorted(keys)))
    ).all()
    loaded: dict[str, H1BSponsorshipEvidence] = {}
    for row in rows:
        try:
            loaded[row.normalized_company] = H1BSponsorshipEvidence.model_validate(
                row.evidence_json
            )
        except ValueError:
            logger.warning(
                "Skipping corrupt H-1B cache row for normalized company %s",
                row.normalized_company,
            )
    return loaded
