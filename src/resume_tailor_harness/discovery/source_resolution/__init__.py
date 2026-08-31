"""Deterministic company-to-board resolution for Discovery Scout."""

from resume_tailor_harness.discovery.source_resolution.catalog import (
    BOARD_FAMILIES,
    BoardFamily,
    canonical_target_url,
    targeted_ats_query_templates,
)
from resume_tailor_harness.discovery.source_resolution.models import CompanySourceResolution

__all__ = [
    "BOARD_FAMILIES",
    "BoardFamily",
    "canonical_target_url",
    "CompanySourceResolution",
    "targeted_ats_query_templates",
]
