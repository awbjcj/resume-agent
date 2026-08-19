"""The single I/O shell that resolves one profile's effective taxonomy.

Only this module knows where the persisted taxonomy inputs live. Downstream
callers receive one frozen ``EffectiveTaxonomy`` instead of composing pieces
independently.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from resume_agent.config import get_settings
from resume_agent.discovery.requirements import JOB_EXTRACTION_POLICY_REVISION
from resume_agent.matching.activation import (
    decide_uccm_activation,
    load_activation_report,
)
from resume_agent.matching.models import MATCHING_POLICY_REVISION
from resume_agent.profile.assertions import ASSERTION_POLICY_REVISION
from resume_agent.profile.matrix import load_overrides
from resume_agent.taxonomy.corrections import corrections_file_path
from resume_agent.taxonomy.custody import TaxonomyCustody
from resume_agent.taxonomy.graph_adapter import (
    CORRECTION_POLICY_VERSION,
    LEGACY_MATCHING_POLICY_VERSION,
    build_capability_snapshot,
    combine_projection_revision,
)
from resume_agent.taxonomy.graph_models import CareerCapabilityMode, TaxonomyRevision
from resume_agent.taxonomy.graph_validation import GraphValidationError
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy, TaxonomyManifest
from resume_agent.taxonomy.term_corrections import (
    load_term_type_corrections,
    term_type_corrections_file_path,
    term_type_corrections_revision,
)
from resume_agent.tenancy.paths import resolve_tenant_path

logger = logging.getLogger(__name__)
DEFAULT_UCCM_ACTIVATION_REPORT_PATH = Path(
    "data/evals/uccm_activation_report.json"
)


def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
    term_corrections_path: str | Path | None = None,
    mode: CareerCapabilityMode | None = None,
    activation_report_path: str | Path | None = None,
) -> EffectiveTaxonomy:
    """Build one coherent snapshot and record aggregate construction latency."""
    started = perf_counter()
    try:
        return _build_effective_taxonomy(
            profile_dir,
            corrections_path=corrections_path,
            term_corrections_path=term_corrections_path,
            mode=mode,
            activation_report_path=activation_report_path,
        )
    finally:
        logger.info(
            "Effective taxonomy snapshot built",
            extra={
                "uccm_snapshot_build_latency_ms": round(
                    (perf_counter() - started) * 1000, 3
                )
            },
        )


def _build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
    term_corrections_path: str | Path | None = None,
    mode: CareerCapabilityMode | None = None,
    activation_report_path: str | Path | None = None,
) -> EffectiveTaxonomy:
    """Read and resolve every taxonomy input for a profile exactly once."""
    profile_dir = Path(profile_dir)
    cluster_path = profile_dir / "cluster_map.json"
    if corrections_path is None:
        corrections_path = resolve_tenant_path(corrections_file_path())
    if term_corrections_path is None:
        term_corrections_path = resolve_tenant_path(term_type_corrections_file_path())

    snapshot = TaxonomyCustody(cluster_path, corrections_path).read()
    overrides = load_overrides(profile_dir / "overrides.yaml")
    resolved = EffectiveTaxonomy.from_parts(
        snapshot.generated,
        corrections=snapshot.corrections,
        overrides=overrides,
        state=snapshot.state,
    )
    term_type_corrections = load_term_type_corrections(term_corrections_path)
    term_correction_revision = term_type_corrections_revision(term_type_corrections)
    complete_semantic_revision = hashlib.sha256(
        json.dumps(
            {
                "taxonomy": resolved.semantic_revision,
                "term_type_corrections": term_correction_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    resolved = replace(
        resolved,
        term_type_corrections=tuple(term_type_corrections),
        semantic_revision=complete_semantic_revision,
        projection_revision=combine_projection_revision(
            resolved.projection_revision, term_correction_revision
        ),
    )
    override_payload = json.dumps(
        overrides.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    override_revision = hashlib.sha256(override_payload).hexdigest()
    requested_mode = mode or get_settings().career_capability_mode
    legacy_revision = TaxonomyRevision(
        internal_graph_version="",
        external_source_snapshots=(),
        crosswalk_revision=hashlib.sha256(b"[]").hexdigest(),
        tenant_overlay_revision=snapshot.corrections_sha256,
        generated_legacy_map_revision=snapshot.generated_sha256,
        correction_ledger_revision=snapshot.corrections_sha256,
        lifecycle_state_revision=snapshot.state_sha256,
        canonicalization_override_revision=override_revision,
        correction_policy_version=CORRECTION_POLICY_VERSION,
        matching_policy_version=LEGACY_MATCHING_POLICY_VERSION,
        effective_hash=resolved.semantic_revision,
    )
    base_manifest = TaxonomyManifest(
        generated=snapshot.generated_sha256,
        corrections=snapshot.corrections_sha256,
        term_type_corrections=term_correction_revision,
        state=snapshot.state_sha256,
        overrides=override_revision,
        semantic=resolved.semantic_revision,
        capability_mode=requested_mode,
        capability_effective_mode=requested_mode,
        capability_status="disabled",
        capability=legacy_revision,
    )
    resolved = replace(
        resolved,
        manifest=base_manifest,
    )
    if requested_mode == "legacy":
        return resolved

    try:
        capability = build_capability_snapshot(
            resolved.cluster_map,
            generated_revision=snapshot.generated_sha256,
            correction_revision=snapshot.corrections_sha256,
            lifecycle_revision=snapshot.state_sha256,
            override_revision=override_revision,
            base_effective_hash=resolved.semantic_revision,
            corrections=snapshot.corrections,
            overrides=overrides,
        )
    except GraphValidationError as error:
        logger.warning(
            "Capability graph activation failed; using the Phase 0 taxonomy",
            exc_info=True,
        )
        return replace(
            resolved,
            capability_snapshot=None,
            manifest=replace(
                base_manifest,
                capability_status="fallback",
                capability_error_code=error.issues[0].code,
            ),
        )

    effective_mode = requested_mode
    activation_error: str | None = None
    activation_report_revision: str | None = None
    if requested_mode == "uccm":
        report_path = activation_report_path
        if report_path is None:
            report_path = getattr(
                get_settings(),
                "uccm_evaluation_report_path",
                DEFAULT_UCCM_ACTIVATION_REPORT_PATH,
            )
        report = load_activation_report(resolve_tenant_path(report_path))
        decision = decide_uccm_activation(
            requested_mode,
            report,
            taxonomy_revision=capability.revision.effective_hash,
            assertion_policy_revision=ASSERTION_POLICY_REVISION,
            extraction_policy_revision=JOB_EXTRACTION_POLICY_REVISION,
            matching_policy_revision=MATCHING_POLICY_REVISION,
        )
        effective_mode = decision.effective_mode
        activation_report_revision = decision.report_revision
        if not decision.eligible:
            activation_error = decision.reason_code
    active_map = (
        capability.legacy_projection
        if effective_mode == "uccm"
        else resolved.cluster_map
    )
    status = (
        "active"
        if effective_mode == "uccm"
        else "fallback" if requested_mode == "uccm" else "shadow"
    )
    return replace(
        resolved,
        cluster_map=active_map,
        capability_snapshot=capability,
        semantic_revision=capability.revision.effective_hash,
        projection_revision=combine_projection_revision(
            resolved.projection_revision,
            capability.revision.effective_hash,
        ),
        manifest=replace(
            base_manifest,
            semantic=capability.revision.effective_hash,
            capability_effective_mode=effective_mode,
            capability_status=status,
            capability_error_code=activation_error,
            capability_activation_report_revision=activation_report_revision,
            capability=capability.revision,
        ),
    )
