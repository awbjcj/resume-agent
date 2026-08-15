"""Read-only, opt-in accuracy checks for Discovery Scout source resolution."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import field_validator

from resume_agent.discovery.source_resolution.models import CompanySourceResolution
from resume_agent.models.base import ExtensibleModel


class SourceResolver(Protocol):
    """The production resolver interface needed by the live evaluator."""

    def resolve(self, company: str, candidate_url: str) -> CompanySourceResolution: ...


class ScoutSourceCase(ExtensibleModel):
    company: str
    official_careers_url: str
    expected_ats: str
    expected_board_url: str
    evidence_checked_at: date

    @field_validator("official_careers_url", "expected_board_url")
    @classmethod
    def require_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("must be an absolute HTTPS URL")
        return value


class ScoutSourceEvalResult(ExtensibleModel):
    company: str
    expected_ats: str
    expected_board_url: str
    actual_ats: str | None = None
    actual_board_url: str = ""
    status: str = "error"
    reason_code: str = ""
    elapsed_seconds: float = 0.0
    passed: bool = False
    error: str | None = None


def load_source_cases(path: Path | str) -> list[ScoutSourceCase]:
    """Load a small manifest of timestamped, manually researched expectations."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Scout source cases must be a JSON array")
    return [ScoutSourceCase.model_validate(item) for item in raw]


def run_source_case(
    case: ScoutSourceCase,
    resolver: SourceResolver,
) -> ScoutSourceEvalResult:
    """Run one source through the production resolver and retain every verdict."""

    started = time.monotonic()
    try:
        resolution = resolver.resolve(case.company, case.official_careers_url)
    except Exception as exc:  # noqa: BLE001 - one remote board must not abort the report.
        return ScoutSourceEvalResult(
            company=case.company,
            expected_ats=case.expected_ats,
            expected_board_url=case.expected_board_url,
            elapsed_seconds=time.monotonic() - started,
            error=f"{type(exc).__name__}: {exc}",
        )

    board_url = resolution.canonical_board_url
    passed = (
        resolution.status == "verified"
        and resolution.ats == case.expected_ats
        and board_url == case.expected_board_url
    )
    return ScoutSourceEvalResult(
        company=case.company,
        expected_ats=case.expected_ats,
        expected_board_url=case.expected_board_url,
        actual_ats=resolution.ats,
        actual_board_url=board_url,
        status=resolution.status,
        reason_code=resolution.reason_code,
        elapsed_seconds=time.monotonic() - started,
        passed=passed,
    )


def run_source_cases(
    cases: Iterable[ScoutSourceCase],
    resolver: SourceResolver,
) -> list[ScoutSourceEvalResult]:
    return [run_source_case(case, resolver) for case in cases]
