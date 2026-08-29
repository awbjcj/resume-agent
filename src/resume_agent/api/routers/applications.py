"""Cross-application timeline grid and lossless CSV projections."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.timeline_analytics import (
    PivotCellOut,
    PivotRowOut,
    PivotTableOut,
)
from resume_agent.tracking.event_vocab import EventKind
from resume_agent.tracking.timeline_pivot import PivotRow, PivotTable, build_pivot

router = APIRouter()
link_router = APIRouter()


def _pivot_out(table: PivotTable) -> PivotTableOut:
    return PivotTableOut(
        rows=[
            PivotRowOut(
                job_id=row.job_id,
                company=row.company,
                title=row.title,
                status=row.status,
                source=row.source,
                fit_score=row.fit_score,
                cells={
                    key: PivotCellOut.model_validate(cell)
                    for key, cell in row.cells.items()
                },
                custom_count=row.custom_count,
                total_comp=row.total_comp,
                comp_currency=row.comp_currency,
                offer_deadline=row.offer_deadline,
                overflow_rounds=table.overflow_by_job.get(row.job_id, 0),
            )
            for row in table.rows
        ],
        technical_round_columns=table.technical_round_columns,
    )


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.isoformat().replace("+00:00", "Z")


def _blank_if_none(value: object | None) -> object:
    return "" if value is None else value


def _wide_fields(round_count: int) -> list[str]:
    stages = [
        kind.value
        for kind in EventKind
        if kind
        not in {EventKind.technical_round, EventKind.offer_deadline, EventKind.custom}
    ]
    return [
        "job_id",
        "company",
        "title",
        "status",
        "source",
        "fit_score",
        *stages,
        *(f"technical_round_{number}" for number in range(1, round_count + 1)),
        "offer_deadline",
        "total_comp",
        "comp_currency",
        "custom_count",
    ]


def _wide_row(row: PivotRow, fields: list[str]) -> dict[str, object]:
    values: dict[str, object] = {
        "job_id": row.job_id,
        "company": row.company or "",
        "title": row.title or "",
        "status": row.status,
        "source": row.source,
        "fit_score": row.fit_score if row.fit_score is not None else "",
        "offer_deadline": _iso(row.offer_deadline),
        "total_comp": row.total_comp if row.total_comp is not None else "",
        "comp_currency": row.comp_currency or "",
        "custom_count": row.custom_count,
    }
    for field in fields:
        if field in row.cells:
            values[field] = _iso(row.cells[field].occurred_at)
    return values


LONG_FIELDS = [
    "job_id",
    "company",
    "title",
    "kind",
    "custom_label",
    "sequence",
    "occurred_at",
    "all_day",
    "timezone",
    "duration_minutes",
    "modality",
    "platform",
    "platform_other",
    "location_or_link",
    "interviewers",
    "result",
    "notes",
    "reflection",
    "comp_base",
    "comp_bonus",
    "comp_equity_annual",
    "comp_signing",
    "comp_currency",
    "source",
]


def _long_rows(table: PivotTable):
    for row in table.rows:
        for event in row.events:
            yield {
                "job_id": row.job_id,
                "company": row.company or "",
                "title": row.title or "",
                "kind": event.kind,
                "custom_label": event.custom_label or "",
                "sequence": event.sequence,
                "occurred_at": _iso(event.occurred_at),
                "all_day": event.all_day,
                "timezone": event.timezone or "",
                "duration_minutes": _blank_if_none(event.duration_minutes),
                "modality": event.modality or "",
                "platform": event.platform or "",
                "platform_other": event.platform_other or "",
                "location_or_link": event.location_or_link or "",
                "interviewers": event.interviewers or "",
                "result": event.result,
                "notes": event.notes or "",
                "reflection": event.reflection or "",
                "comp_base": _blank_if_none(event.comp_base),
                "comp_bonus": _blank_if_none(event.comp_bonus),
                "comp_equity_annual": _blank_if_none(event.comp_equity_annual),
                "comp_signing": _blank_if_none(event.comp_signing),
                "comp_currency": event.comp_currency or "",
                "source": event.source,
            }


def _csv_response(fields: list[str], rows, filename: str) -> Response:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(
        {
            key: f"'{value}"
            if isinstance(value, str)
            and value.lstrip().startswith(("=", "+", "-", "@"))
            else value
            for key, value in row.items()
        }
        for row in rows
    )
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/applications", response_model=PivotTableOut)
def get_applications(session: Session = Depends(get_session)) -> PivotTableOut:
    return _pivot_out(build_pivot(session))


@link_router.get("/applications.csv")
def get_applications_csv(
    shape: str = "wide", session: Session = Depends(get_session)
) -> Response:
    if shape not in {"wide", "long"}:
        raise ApiException(422, "VALIDATION_ERROR", "shape must be wide or long")
    table = build_pivot(session, max_technical_rounds=None)
    if shape == "long":
        return _csv_response(LONG_FIELDS, _long_rows(table), "application-events.csv")
    fields = _wide_fields(table.technical_round_columns)
    return _csv_response(
        fields,
        (_wide_row(row, fields) for row in table.rows),
        "applications.csv",
    )
