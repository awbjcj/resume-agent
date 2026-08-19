"""Read-only UCCM views derived from profile capability assertions."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.assertions import CapabilityAssertion
from resume_agent.taxonomy.graph_models import CareerLayer
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

PROFILE_LAYER_ORDER: tuple[CareerLayer, ...] = (
    "career_core",
    "foundational",
    "transferable_function",
    "domain_industry",
    "occupation_role",
    "enabler",
)


class ProfileProjectionItem(ExtensibleModel):
    concept_id: str
    concept_type: str
    display: str
    assertion_ids: list[str] = Field(default_factory=list)
    evidence_fact_ids: list[str] = Field(default_factory=list)


class ProfileLayerProjection(ExtensibleModel):
    layer: CareerLayer
    items: list[ProfileProjectionItem] = Field(default_factory=list)


class EvidenceQualityProjection(ExtensibleModel):
    counts: dict[str, int] = Field(default_factory=dict)
    assertion_ids: list[str] = Field(default_factory=list)


DevelopmentReason = Literal[
    "unknown_type",
    "evidence_needed",
    "disputed",
    "level_unknown",
]


class DevelopmentNeed(ExtensibleModel):
    assertion_id: str
    concept_id: str
    display: str
    reason: DevelopmentReason


class UccmProfileProjection(ExtensibleModel):
    layers: list[ProfileLayerProjection] = Field(default_factory=list)
    evidence_quality: EvidenceQualityProjection = Field(
        default_factory=EvidenceQualityProjection
    )
    development_needs: list[DevelopmentNeed] = Field(default_factory=list)


def _fallback_layers(
    assertion: CapabilityAssertion,
    taxonomy: EffectiveTaxonomy,
) -> tuple[CareerLayer, ...]:
    concept_type = assertion.concept_type
    if concept_type in {"tool_technology", "artifact", "language", "credential"}:
        return ("enabler",)
    key = assertion.legacy_projection.key
    if key in taxonomy.cluster_map.domain_of:
        return ("domain_industry",)
    return ()


def _development_reason(
    assertion: CapabilityAssertion,
) -> DevelopmentReason | None:
    if assertion.concept_type == "unknown":
        return "unknown_type"
    if assertion.assertion_status == "disputed":
        return "disputed"
    if assertion.claimability in {"self_reported_unverified", "unknown"}:
        return "evidence_needed"
    if assertion.proficiency_level is None:
        return "level_unknown"
    return None


def build_profile_projection(
    assertions: list[CapabilityAssertion],
    taxonomy: EffectiveTaxonomy,
) -> UccmProfileProjection:
    graph_layers = {
        node.id: tuple(node.career_layers)
        for node in (
            taxonomy.capability_snapshot.graph.nodes
            if taxonomy.capability_snapshot is not None
            else []
        )
    }
    items_by_layer: dict[CareerLayer, list[ProfileProjectionItem]] = {
        layer: [] for layer in PROFILE_LAYER_ORDER
    }
    development_needs: list[DevelopmentNeed] = []
    for assertion in assertions:
        item = ProfileProjectionItem(
            concept_id=assertion.concept_id,
            concept_type=assertion.concept_type,
            display=assertion.legacy_projection.display,
            assertion_ids=[assertion.id],
            evidence_fact_ids=assertion.evidence_fact_ids,
        )
        layers = graph_layers.get(assertion.concept_id) or _fallback_layers(
            assertion, taxonomy
        )
        for layer in layers:
            items_by_layer[layer].append(item)
        if (reason := _development_reason(assertion)) is not None:
            development_needs.append(
                DevelopmentNeed(
                    assertion_id=assertion.id,
                    concept_id=assertion.concept_id,
                    display=assertion.legacy_projection.display,
                    reason=reason,
                )
            )
    counts = Counter(assertion.assertion_status for assertion in assertions)
    return UccmProfileProjection(
        layers=[
            ProfileLayerProjection(
                layer=layer,
                items=sorted(
                    items_by_layer[layer],
                    key=lambda item: (item.display.casefold(), item.concept_id),
                ),
            )
            for layer in PROFILE_LAYER_ORDER
        ],
        evidence_quality=EvidenceQualityProjection(
            counts=dict(sorted(counts.items())),
            assertion_ids=sorted(assertion.id for assertion in assertions),
        ),
        development_needs=sorted(
            development_needs,
            key=lambda need: (need.reason, need.display.casefold(), need.assertion_id),
        ),
    )
