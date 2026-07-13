"""Bounded CSV/JSON job import through the normal ingest policy."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.ingest import IngestOutcome, save_or_upgrade

_COLUMNS = ("title", "company", "url", "location", "jd_text", "posted_at")
_MISSING_JD = (
    "jd_text is required; use the URL-list import for postings you only have links for"
)
_MAX_ROWS = 10_000
_MAX_FIELD_CHARS = 2_000_000


class UnsupportedJobsFormatError(ValueError):
    pass


class InvalidJobsFileError(ValueError):
    pass


@dataclass
class JobsImportReport:
    added: int = 0
    upgraded: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


def _rows(filename: str, data: bytes) -> list[object]:
    suffix = Path(filename).suffix.casefold()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidJobsFileError("file must be UTF-8 encoded") from exc
    try:
        if suffix == ".csv":
            return list(csv.DictReader(io.StringIO(text)))
        if suffix == ".json":
            value = json.loads(text)
            if not isinstance(value, list):
                raise InvalidJobsFileError("JSON must contain an array of jobs")
            return value
    except (csv.Error, json.JSONDecodeError) as exc:
        raise InvalidJobsFileError(f"could not parse {suffix[1:].upper()} file") from exc
    raise UnsupportedJobsFormatError("only .csv and .json files are supported")


def import_jobs_file(
    session: Session, filename: str, data: bytes
) -> JobsImportReport:
    rows = _rows(filename, data)
    if len(rows) > _MAX_ROWS:
        raise InvalidJobsFileError(f"file exceeds the {_MAX_ROWS} row limit")
    report = JobsImportReport()
    for row_number, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            report.errors.append((row_number, "row must be an object"))
            continue
        values = {
            column: str(raw.get(column) or "").strip() for column in _COLUMNS
        }
        if any(len(value) > _MAX_FIELD_CHARS for value in values.values()):
            report.errors.append((row_number, "row contains an oversized field"))
            continue
        if not values["jd_text"]:
            report.errors.append((row_number, _MISSING_JD))
            continue
        _, outcome = save_or_upgrade(
            session,
            source="manual",
            jd_text=values["jd_text"],
            url=values["url"] or None,
            company=values["company"] or None,
            title=values["title"] or None,
            location=values["location"] or None,
            posted_at=parse_iso_datetime(values["posted_at"] or None),
            commit=False,
        )
        if outcome is IngestOutcome.inserted:
            report.added += 1
        elif outcome is IngestOutcome.upgraded:
            report.upgraded += 1
        else:
            report.skipped += 1
    session.commit()
    return report
