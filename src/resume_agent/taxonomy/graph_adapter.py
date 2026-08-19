"""Compatibility projection between legacy cluster maps and capability graphs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from urllib.parse import quote

from resume_agent.profile.matrix import Overrides
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.graph_models import (
    CareerCapabilityGraph,
    ConceptEdge,
    ConceptNode,
    CorrectionEvent,
    EffectiveCapabilitySnapshot,
    LegacyProjectionMetadata,
    SourceManifest,
    SourceMapping,
    TaxonomyRevision,
)
from resume_agent.taxonomy.graph_validation import (
    GraphValidationError,
    validate_capability_graph,
)
from resume_agent.taxonomy.uccm_seeds import (
    UCCM_MODEL_VERSION,
    UCCM_SOURCE,
    uccm_seed_nodes,
)
from resume_agent.tracking.match_gap import normalize_skill

_LEGACY_CLUSTER_MAP_URI = "repo://data/profile/cluster_map.json"
_TAXONOMY_CORRECTIONS_URI = "repo://data/taxonomy/taxonomy_corrections.json"
_PROFILE_OVERRIDES_URI = "repo://data/profile/overrides.yaml"
_LEGACY_NODE_SOURCE_URI = "workspace://profile/cluster_map.json"

CORRECTION_POLICY_VERSION = "taxonomy-corrections-v1"
LEGACY_MATCHING_POLICY_VERSION = "legacy-exact-adjacent-gap-v1"


def legacy_concept_id(token: str) -> str:
    """Return the stable graph ID for one normalized legacy skill token."""
    normalized = normalize_skill(token)
    if not normalized:
        raise ValueError("legacy concept token must normalize to a non-empty value")
    return f"legacy:skill:{quote(normalized, safe='')}"


def _stable_id(namespace: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{namespace}:{hashlib.sha256(encoded).hexdigest()[:24]}"


def _normalized_token(token: str) -> str:
    normalized = normalize_skill(token)
    if not normalized:
        raise ValueError("legacy concept token must normalize to a non-empty value")
    return normalized


def _component_source(
    *,
    identifier: str,
    namespace: str,
    source_id: str,
    revision: str,
    source_uri: str,
    attribution: str,
    tenant_scope: str,
) -> SourceManifest:
    return SourceManifest(
        id=identifier,
        namespace=namespace,
        source_id=source_id,
        source_version=revision,
        source_uri=source_uri,
        license_id="workspace-private",
        attribution=attribution,
        checksum=revision,
        mapping_status="adapted",
        tenant_scope=tenant_scope,
    )


def _component_sources(
    *,
    generated_revision: str,
    correction_revision: str,
    override_revision: str,
) -> tuple[SourceManifest, SourceManifest, SourceManifest]:
    generated = _component_source(
        identifier=f"source:legacy-cluster-map:{generated_revision}",
        namespace="legacy_cluster_map",
        source_id="legacy-cluster-map",
        revision=generated_revision,
        source_uri=_LEGACY_CLUSTER_MAP_URI,
        attribution="Resume Agent legacy cluster map",
        tenant_scope="workspace",
    )
    corrections = _component_source(
        identifier=f"source:tenant-corrections:{correction_revision}",
        namespace="tenant_corrections",
        source_id="tenant-corrections",
        revision=correction_revision,
        source_uri=_TAXONOMY_CORRECTIONS_URI,
        attribution="Resume Agent taxonomy correction ledger",
        tenant_scope="tenant",
    )
    overrides = _component_source(
        identifier=f"source:profile-overrides:{override_revision}",
        namespace="profile_overrides",
        source_id="profile-overrides",
        revision=override_revision,
        source_uri=_PROFILE_OVERRIDES_URI,
        attribution="Resume Agent profile overrides",
        tenant_scope="profile",
    )
    return generated, corrections, overrides


def _legacy_node(token: str, generated_source: SourceManifest) -> ConceptNode:
    return ConceptNode(
        id=legacy_concept_id(token),
        type="skill",
        preferred_label=token,
        normalized_label=token,
        claim_policy="evidence_required",
        type_assignment_status="legacy_placeholder",
        source_refs=[generated_source.id],
        source_mappings=[
            SourceMapping(
                namespace=generated_source.namespace,
                source_id=token,
                source_label=token,
                source_version=generated_source.source_version,
                source_uri=_LEGACY_NODE_SOURCE_URI,
                license_id=generated_source.license_id,
                attribution=generated_source.attribution,
                import_checksum=generated_source.checksum,
                mapping_status="adapted",
            )
        ],
    )


def _normalized_aliases(cmap: ClusterMap) -> dict[str, str]:
    return {
        _normalized_token(token): _normalized_token(target)
        for token, target in cmap.aliases.items()
    }


def _normalized_alias_keys(aliases: Mapping[str, str]) -> set[str]:
    return {
        normalize_skill(token)
        for token in aliases
        if isinstance(token, str) and normalize_skill(token)
    }


def _profile_alias_tokens(overrides: Overrides | None) -> set[str]:
    if overrides is None:
        return set()

    tokens = _normalized_alias_keys(overrides.alias)
    for pair in overrides.forbid_alias:
        if len(pair) != 2:
            continue
        first, second = (normalize_skill(token) for token in pair)
        if first and second and first != second:
            tokens.update((first, second))
    return tokens


def _alias_source(
    *,
    token: str,
    generated_source: SourceManifest,
    correction_source: SourceManifest,
    override_source: SourceManifest,
    correction_alias_tokens: set[str],
    profile_alias_tokens: set[str],
) -> SourceManifest:
    if token in profile_alias_tokens:
        return override_source
    if token in correction_alias_tokens:
        return correction_source
    return generated_source


def _correction_events(
    corrections: TaxonomyCorrections | None,
    overrides: Overrides | None,
    *,
    correction_revision: str,
    override_revision: str,
) -> tuple[CorrectionEvent, ...]:
    events: list[CorrectionEvent] = []

    def add(
        scope: str,
        operation: str,
        subject: str,
        object_: str | None,
        payload: dict[str, object],
        source_revision: str,
    ) -> None:
        event_payload = dict(payload)
        identifier = _stable_id(
            "event",
            (scope, operation, subject, object_, event_payload, source_revision),
        )
        events.append(
            CorrectionEvent(
                id=identifier,
                scope=scope,
                operation=operation,
                subject=subject,
                object=object_,
                payload=event_payload,
                source_revision=source_revision,
            )
        )

    if corrections is not None:
        for token, target in sorted(corrections.aliases.items()):
            add("tenant", "alias", token, target, {}, correction_revision)
        for token in sorted(corrections.added_skills):
            add("tenant", "add_skill", token, None, {}, correction_revision)
        for token in sorted(corrections.removed_skills):
            add("tenant", "remove_skill", token, None, {}, correction_revision)
        for token, domain in sorted(corrections.skill_domain.items()):
            add("tenant", "move_skill", token, domain, {}, correction_revision)
        for domain, label in sorted(corrections.domain_renames.items()):
            add("tenant", "rename_domain", domain, label, {}, correction_revision)
        for loser, winner in sorted(corrections.domain_merges.items()):
            add("tenant", "merge_domain", loser, winner, {}, correction_revision)
        for domain, category in sorted(corrections.domain_category.items()):
            add(
                "tenant",
                "set_domain_category",
                domain,
                category,
                {},
                correction_revision,
            )

    if overrides is not None:
        for token, target in sorted(overrides.alias.items()):
            add("profile", "alias", token, target, {}, override_revision)
        for pair in sorted(
            tuple(sorted(pair)) for pair in overrides.forbid_alias if len(pair) == 2
        ):
            add("profile", "forbid_alias", pair[0], pair[1], {}, override_revision)
        for token in sorted(overrides.ban):
            add("profile", "ban_skill", token, None, {}, override_revision)
        for token, category in sorted(overrides.category.items()):
            add(
                "profile",
                "set_profile_category",
                token,
                category,
                {},
                override_revision,
            )
        for token, group in sorted(overrides.group.items()):
            add(
                "profile",
                "set_profile_group",
                token,
                group,
                {},
                override_revision,
            )

    return tuple(sorted(events, key=lambda event: event.id))


def cluster_map_to_graph(
    cmap: ClusterMap,
    *,
    generated_revision: str,
    correction_revision: str,
    override_revision: str,
    corrections: TaxonomyCorrections | None = None,
    overrides: Overrides | None = None,
) -> tuple[CareerCapabilityGraph, tuple[CorrectionEvent, ...]]:
    """Project one effective legacy map into its typed, provenance-rich graph."""
    generated_source, correction_source, override_source = _component_sources(
        generated_revision=generated_revision,
        correction_revision=correction_revision,
        override_revision=override_revision,
    )
    aliases = _normalized_aliases(cmap)
    correction_alias_tokens = (
        _normalized_alias_keys(corrections.aliases) if corrections is not None else set()
    )
    profile_alias_tokens = _profile_alias_tokens(overrides)
    domain_of = {
        legacy_concept_id(token): domain
        for token, domain in cmap.domain_of.items()
    }
    legacy_tokens = set(aliases)
    legacy_tokens.update(aliases.values())
    legacy_tokens.update(_normalized_token(token) for token in cmap.domain_of)
    concept_tokens = {
        legacy_concept_id(token): token for token in sorted(legacy_tokens)
    }
    legacy_nodes = [
        _legacy_node(token, generated_source)
        for _, token in sorted(concept_tokens.items())
    ]

    edges: list[ConceptEdge] = []
    for token, target in aliases.items():
        source = _alias_source(
            token=token,
            generated_source=generated_source,
            correction_source=correction_source,
            override_source=override_source,
            correction_alias_tokens=correction_alias_tokens,
            profile_alias_tokens=profile_alias_tokens,
        )
        scope = "profile" if source.tenant_scope == "profile" else "tenant"
        subject_id = legacy_concept_id(token)
        object_id = legacy_concept_id(target)
        edges.append(
            ConceptEdge(
                id=_stable_id(
                    "edge",
                    {
                        "subject_id": subject_id,
                        "predicate": "lexical_alias_of",
                        "object_id": object_id,
                        "source_id": source.id,
                        "scope": scope,
                        "revision_created": source.source_version,
                    },
                ),
                subject_id=subject_id,
                predicate="lexical_alias_of",
                object_id=object_id,
                source_refs=[source.id],
                scope=scope,
                revision_created=source.source_version,
            )
        )

    graph = CareerCapabilityGraph(
        model_version=UCCM_MODEL_VERSION,
        nodes=sorted([*legacy_nodes, *uccm_seed_nodes()], key=lambda node: node.id),
        edges=sorted(edges, key=lambda edge: edge.id),
        sources=sorted(
            [UCCM_SOURCE, generated_source, correction_source, override_source],
            key=lambda source: source.id,
        ),
        legacy_projection=LegacyProjectionMetadata(
            concept_tokens=dict(sorted(concept_tokens.items())),
            domain_of=dict(sorted(domain_of.items())),
            domain_label=dict(sorted(cmap.domain_label.items())),
            category_of=dict(sorted(cmap.category_of.items())),
        ),
    )
    validate_capability_graph(graph)
    return graph, _correction_events(
        corrections,
        overrides,
        correction_revision=correction_revision,
        override_revision=override_revision,
    )


def _flatten_legacy_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    """Flatten directed aliases while allowing only canonical self-anchors."""
    flattened: dict[str, str] = {}
    for alias in sorted(aliases):
        if alias in flattened:
            continue

        path: list[str] = []
        seen: set[str] = set()
        token = alias
        while True:
            if token in flattened:
                terminal = flattened[token]
                break
            if token in seen:
                raise ValueError(f"alias cycle detected at {token!r}")

            target = aliases.get(token)
            if target is None:
                terminal = token
                break
            if target == token:
                flattened[token] = token
                terminal = token
                break

            seen.add(token)
            path.append(token)
            token = target

        for path_token in path:
            flattened[path_token] = terminal

    return {alias: flattened[alias] for alias in sorted(aliases)}


def graph_to_cluster_map(graph: CareerCapabilityGraph) -> ClusterMap:
    """Recover a compatibility map from only its legacy projection and aliases."""
    projection = graph.legacy_projection
    concept_tokens = dict(projection.concept_tokens)
    aliases: dict[str, str] = {}
    for edge in graph.edges:
        if edge.predicate != "lexical_alias_of" or edge.status != "approved":
            continue
        subject = concept_tokens.get(edge.subject_id)
        object_ = concept_tokens.get(edge.object_id)
        if subject is None or object_ is None:
            continue
        existing = aliases.get(subject)
        if existing is not None and existing != object_:
            raise ValueError(f"conflicting alias edges for {subject!r}")
        aliases[subject] = object_

    domain_of = {
        token: domain
        for concept_id, domain in projection.domain_of.items()
        if (token := concept_tokens.get(concept_id)) is not None
    }
    return ClusterMap(
        aliases=_flatten_legacy_aliases(aliases),
        domain_of=dict(sorted(domain_of.items())),
        domain_label=dict(sorted(projection.domain_label.items())),
        category_of=dict(sorted(projection.category_of.items())),
    )


def canonical_graph_json(graph: CareerCapabilityGraph) -> str:
    """Serialize graph semantics canonically for deterministic identity."""
    payload = graph.model_dump(mode="json", exclude_none=True)
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["id"])
    payload["edges"] = sorted(payload["edges"], key=lambda item: item["id"])
    payload["sources"] = sorted(payload["sources"], key=lambda item: item["id"])
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def graph_revision(graph: CareerCapabilityGraph) -> str:
    """Return the content hash of one canonical capability graph."""
    return hashlib.sha256(canonical_graph_json(graph).encode()).hexdigest()


def combine_projection_revision(
    base_projection_revision: str, effective_hash: str
) -> str:
    """Bind the compatibility projection revision to graph semantics."""
    return _digest(
        {
            "base_projection_revision": base_projection_revision,
            "effective_hash": effective_hash,
        }
    )


def _crosswalk_revision(graph: CareerCapabilityGraph) -> str:
    crosswalk_edges = [
        edge.model_dump(mode="json", exclude_none=True)
        for edge in sorted(graph.edges, key=lambda edge: edge.id)
        if edge.status == "approved"
        and edge.predicate in {"same_as", "equivalent_in_context", "aligned_to"}
    ]
    return _digest(crosswalk_edges)


def build_capability_snapshot(
    cmap: ClusterMap,
    *,
    generated_revision: str,
    correction_revision: str,
    lifecycle_revision: str,
    override_revision: str,
    base_effective_hash: str,
    corrections: TaxonomyCorrections | None = None,
    overrides: Overrides | None = None,
) -> EffectiveCapabilitySnapshot:
    """Build and validate an immutable graph snapshot of an effective map."""
    graph, correction_events = cluster_map_to_graph(
        cmap,
        generated_revision=generated_revision,
        correction_revision=correction_revision,
        override_revision=override_revision,
        corrections=corrections,
        overrides=overrides,
    )
    validate_capability_graph(graph)
    legacy_projection = graph_to_cluster_map(graph)
    if legacy_projection != cmap:
        raise GraphValidationError.single(
            "legacy_projection_mismatch", "legacy projection"
        )

    internal_graph_version = graph_revision(graph)
    crosswalk_revision = _crosswalk_revision(graph)
    effective_hash = _digest(
        {
            "base_effective_hash": base_effective_hash,
            "internal_graph_version": internal_graph_version,
            "crosswalk_revision": crosswalk_revision,
            "correction_policy_version": CORRECTION_POLICY_VERSION,
            "matching_policy_version": LEGACY_MATCHING_POLICY_VERSION,
        }
    )
    revision = TaxonomyRevision(
        internal_graph_version=internal_graph_version,
        external_source_snapshots=(),
        crosswalk_revision=crosswalk_revision,
        tenant_overlay_revision=correction_revision,
        generated_legacy_map_revision=generated_revision,
        correction_ledger_revision=correction_revision,
        lifecycle_state_revision=lifecycle_revision,
        canonicalization_override_revision=override_revision,
        correction_policy_version=CORRECTION_POLICY_VERSION,
        matching_policy_version=LEGACY_MATCHING_POLICY_VERSION,
        effective_hash=effective_hash,
    )
    return EffectiveCapabilitySnapshot(
        graph=graph,
        legacy_projection=legacy_projection,
        correction_events=correction_events,
        revision=revision,
    )
