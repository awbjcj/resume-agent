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

from resume_agent.config import get_settings
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
from resume_agent.tenancy.paths import resolve_tenant_path

logger = logging.getLogger(__name__)


def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
    mode: CareerCapabilityMode | None = None,
) -> EffectiveTaxonomy:
    """Read and resolve every taxonomy input for a profile exactly once."""
    profile_dir = Path(profile_dir)
    cluster_path = profile_dir / "cluster_map.json"
    if corrections_path is None:
        corrections_path = resolve_tenant_path(corrections_file_path())

    snapshot = TaxonomyCustody(cluster_path, corrections_path).read()
    overrides = load_overrides(profile_dir / "overrides.yaml")
    resolved = EffectiveTaxonomy.from_parts(
        snapshot.generated,
        corrections=snapshot.corrections,
        overrides=overrides,
        state=snapshot.state,
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
        state=snapshot.state_sha256,
        overrides=override_revision,
        semantic=resolved.semantic_revision,
        capability_mode=requested_mode,
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

    active_map = (
        capability.legacy_projection
        if requested_mode == "uccm"
        else resolved.cluster_map
    )
    status = "active" if requested_mode == "uccm" else "shadow"
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
            capability_status=status,
            capability=capability.revision,
        ),
    )
