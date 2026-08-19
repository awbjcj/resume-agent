from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from resume_agent.taxonomy.graph_models import CareerLayer, ConceptNode, SourceManifest

UCCM_MODEL_VERSION = "0.1.0-design"


@dataclass(frozen=True)
class CareerLayerDefinition:
    id: CareerLayer
    label: str


CAREER_LAYERS = (
    CareerLayerDefinition("career_core", "Career Core Capabilities"),
    CareerLayerDefinition(
        "foundational", "Foundational Literacies and Work Methods"
    ),
    CareerLayerDefinition("transferable_function", "Transferable Work Functions"),
    CareerLayerDefinition("domain_industry", "Domain and Industry Knowledge"),
    CareerLayerDefinition("occupation_role", "Occupation and Role Capabilities"),
    CareerLayerDefinition(
        "enabler", "Tools, Technologies, Standards, and Artifacts"
    ),
)

CORE_FAMILIES = (
    ("career-navigation-continuous-learning", "Career Navigation and Continuous Learning"),
    ("reasoning-judgment-problem-solving", "Reasoning, Judgment, and Problem Solving"),
    ("communication-sensemaking", "Communication and Sensemaking"),
    ("collaboration-relationship-management", "Collaboration and Relationship Management"),
    ("professional-responsibility-execution", "Professional Responsibility and Execution"),
    ("leadership-influence-mobilization", "Leadership, Influence, and Mobilization"),
    ("inclusive-intercultural-practice", "Inclusive and Intercultural Practice"),
    ("digital-data-ai-fluency", "Digital, Data, and AI Fluency"),
)

WORK_FUNCTIONS = (
    ("discover-research", "Discover and Research"),
    ("analyze-diagnose", "Analyze and Diagnose"),
    ("decide-advise", "Decide and Advise"),
    ("design-create", "Design and Create"),
    ("plan-coordinate", "Plan and Coordinate"),
    ("execute-operate", "Execute and Operate"),
    ("monitor-assure", "Monitor and Assure"),
    ("communicate-influence", "Communicate and Influence"),
    ("collaborate-facilitate", "Collaborate and Facilitate"),
    ("serve-support-care", "Serve, Support, and Care"),
    ("teach-develop", "Teach and Develop"),
    ("lead-manage", "Lead and Manage"),
)


def _seed_checksum() -> str:
    payload = {
        "career_layers": [asdict(layer) for layer in CAREER_LAYERS],
        "core_families": CORE_FAMILIES,
        "work_functions": WORK_FUNCTIONS,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


UCCM_SOURCE = SourceManifest(
    id="source:internal:uccm",
    namespace="internal",
    source_id="uccm",
    source_version=UCCM_MODEL_VERSION,
    source_uri="repo://docs/uccm-reference-model.yaml",
    license_id="internal-proprietary",
    attribution="Resume Agent UCCM reference model",
    checksum=_seed_checksum(),
    mapping_status="native",
    tenant_scope="global",
)


def _seed_node(
    *, namespace: str, row: tuple[str, str], layer: CareerLayer
) -> ConceptNode:
    slug, label = row
    return ConceptNode(
        id=f"internal:{namespace}:{slug}",
        type="competency_family" if layer == "career_core" else "work_activity",
        preferred_label=label,
        normalized_label=label.casefold(),
        career_layers=[layer],
        granularity="family",
        reusability="transversal" if layer == "career_core" else "cross_sectoral",
        claim_policy="never_candidate_claim",
        type_assignment_status="governed",
        source_refs=[UCCM_SOURCE.id],
    )


def uccm_seed_nodes() -> tuple[ConceptNode, ...]:
    nodes = [
        _seed_node(namespace="competency-family", row=row, layer="career_core")
        for row in CORE_FAMILIES
    ]
    nodes.extend(
        _seed_node(
            namespace="work-function",
            row=row,
            layer="transferable_function",
        )
        for row in WORK_FUNCTIONS
    )
    return tuple(sorted(nodes, key=lambda node: node.id))
