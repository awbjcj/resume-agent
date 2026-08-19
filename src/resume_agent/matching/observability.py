"""Privacy-safe operational measurements for UCCM shadow and primary runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True)
class UccmRuntimeObservation:
    profile_assertions_by_status: dict[str, int]
    profile_assertions_by_type: dict[str, int]
    unresolved_term_rate: float
    match_status_distribution: dict[str, int]
    false_transfer_adjudications: int
    correction_rate: float
    fallback_rate: float
    stale_artifact_incidents: int
    provider_cost_micros: int | None
    provider_latency_ms: float | None

    def log_fields(self) -> dict[str, object]:
        """Return aggregate fields only; raw profile and job text never enters logs."""
        return asdict(self)


def build_uccm_observation(
    *,
    assertion_statuses: Iterable[str],
    assertion_types: Iterable[str],
    requirement_types: Iterable[str],
    match_statuses: Iterable[str],
    correction_count: int = 0,
    false_transfer_adjudications: int = 0,
    fallback: bool = False,
    stale: bool = False,
    provider_cost_micros: int | None = None,
    provider_latency_ms: float | None = None,
) -> UccmRuntimeObservation:
    assertion_statuses = tuple(assertion_statuses)
    assertion_types = tuple(assertion_types)
    requirement_types = tuple(requirement_types)
    observed_term_count = len(assertion_types) + len(requirement_types)
    return UccmRuntimeObservation(
        profile_assertions_by_status=_counts(assertion_statuses),
        profile_assertions_by_type=_counts(assertion_types),
        unresolved_term_rate=_rate(
            sum(value == "unknown" for value in requirement_types),
            len(requirement_types),
        ),
        match_status_distribution=_counts(match_statuses),
        false_transfer_adjudications=false_transfer_adjudications,
        correction_rate=_rate(correction_count, observed_term_count),
        fallback_rate=float(fallback),
        stale_artifact_incidents=int(stale),
        provider_cost_micros=provider_cost_micros,
        provider_latency_ms=provider_latency_ms,
    )
