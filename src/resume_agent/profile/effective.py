"""The single I/O shell that resolves one profile's effective taxonomy.

Only this module knows where the persisted taxonomy inputs live. Downstream
callers receive one frozen ``EffectiveTaxonomy`` instead of composing pieces
independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from resume_agent.profile.matrix import load_overrides
from resume_agent.taxonomy.corrections import corrections_file_path
from resume_agent.taxonomy.custody import TaxonomyCustody
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy, TaxonomyManifest
from resume_agent.tenancy.paths import resolve_tenant_path


def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
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
    return replace(
        resolved,
        manifest=TaxonomyManifest(
            generated=snapshot.generated_sha256,
            corrections=snapshot.corrections_sha256,
            state=snapshot.state_sha256,
            overrides=hashlib.sha256(override_payload).hexdigest(),
            semantic=resolved.semantic_revision,
        ),
    )
