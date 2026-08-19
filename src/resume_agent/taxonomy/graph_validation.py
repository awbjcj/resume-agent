"""Deterministic integrity checks for capability graphs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import re

from resume_agent.taxonomy.graph_models import (
    CareerCapabilityGraph,
    ConceptEdge,
    ConceptNode,
    SourceManifest,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS

CAPABILITY_LIKE = frozenset(
    {
        "competency_family",
        "capability",
        "skill",
        "work_activity",
        "task",
        "method",
    }
)
KNOWLEDGE_LIKE = frozenset({"knowledge", "knowledge_domain"})
DOMAIN_TYPES = frozenset({"industry_domain", "knowledge_domain"})
ROLE_TYPES = frozenset({"occupation_role"})
TOOL_TYPES = frozenset({"tool_technology", "language"})
ARTIFACT_TYPES = frozenset({"artifact"})
CREDENTIAL_TYPES = frozenset({"credential", "standard"})
ALL_TYPES = frozenset(
    {
        "competency_family",
        "capability",
        "skill",
        "knowledge",
        "work_activity",
        "task",
        "method",
        "standard",
        "tool_technology",
        "artifact",
        "work_style",
        "language",
        "occupation_role",
        "industry_domain",
        "knowledge_domain",
        "credential",
        "requirement",
        "work_context",
        "learning_outcome",
    }
)

EDGE_SIGNATURES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "lexical_alias_of": (ALL_TYPES, ALL_TYPES),
    "same_as": (ALL_TYPES, ALL_TYPES),
    "equivalent_in_context": (ALL_TYPES, ALL_TYPES),
    "broader_than": (
        ALL_TYPES - frozenset({"requirement"}),
        ALL_TYPES - frozenset({"requirement"}),
    ),
    "narrower_than": (
        ALL_TYPES - frozenset({"requirement"}),
        ALL_TYPES - frozenset({"requirement"}),
    ),
    "version_of": (
        ALL_TYPES - frozenset({"requirement", "work_context"}),
        ALL_TYPES - frozenset({"requirement", "work_context"}),
    ),
    "member_of_family": (
        CAPABILITY_LIKE | TOOL_TYPES | CREDENTIAL_TYPES,
        frozenset(
            {"competency_family", "capability", "tool_technology", "standard"}
        ),
    ),
    "requires_knowledge": (CAPABILITY_LIKE | ROLE_TYPES, KNOWLEDGE_LIKE),
    "requires_capability": (
        CAPABILITY_LIKE | ROLE_TYPES,
        frozenset({"capability", "skill"}),
    ),
    "uses_tool": (CAPABILITY_LIKE | ROLE_TYPES, TOOL_TYPES),
    "produces_artifact": (CAPABILITY_LIKE | ROLE_TYPES, ARTIFACT_TYPES),
    "supports_task": (
        frozenset({"capability", "skill", "knowledge", "method", "tool_technology"}),
        frozenset({"task", "work_activity"}),
    ),
    "essential_for_role": (
        CAPABILITY_LIKE | KNOWLEDGE_LIKE | TOOL_TYPES | CREDENTIAL_TYPES,
        ROLE_TYPES,
    ),
    "optional_for_role": (
        CAPABILITY_LIKE | KNOWLEDGE_LIKE | TOOL_TYPES | CREDENTIAL_TYPES,
        ROLE_TYPES,
    ),
    "applies_in_domain": (ALL_TYPES - frozenset({"requirement"}), DOMAIN_TYPES),
    "transferable_to": (CAPABILITY_LIKE, CAPABILITY_LIKE),
    "prerequisite_for": (
        CAPABILITY_LIKE | KNOWLEDGE_LIKE | CREDENTIAL_TYPES,
        CAPABILITY_LIKE | ROLE_TYPES | frozenset({"learning_outcome"}),
    ),
    "validated_by": (CAPABILITY_LIKE | KNOWLEDGE_LIKE, CREDENTIAL_TYPES),
    "aligned_to": (ALL_TYPES, ALL_TYPES),
}

_BIDIRECTIONAL_PREDICATES = frozenset({"same_as", "equivalent_in_context"})
_EXTERNAL_NAMESPACES = frozenset(
    {"internal", "legacy_cluster_map", "tenant_corrections", "profile_overrides"}
)
_NODE_ID = re.compile(r"^[^:\s]+:[^:\s]+:[^:\s]+$")
_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GraphValidationIssue:
    """One stable graph-invariant violation."""

    code: str
    subject: str


class GraphValidationError(ValueError):
    """All deterministic graph-validation issues found in a single pass."""

    def __init__(self, issues: Iterable[GraphValidationIssue]):
        self.issues = tuple(
            sorted(set(issues), key=lambda issue: (issue.code, issue.subject))
        )
        message = "; ".join(
            f"{issue.code}: {issue.subject}" for issue in self.issues
        )
        super().__init__(message or "Capability graph validation failed")

    @classmethod
    def single(cls, code: str, subject: str) -> GraphValidationError:
        """Create a one-issue error for a deterministic caller-side fallback."""

        return cls([GraphValidationIssue(code, subject)])


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue_subject(value: object) -> str:
    return value if isinstance(value, str) and value else "<empty>"


def _is_node_id(value: object) -> bool:
    return isinstance(value, str) and bool(_NODE_ID.fullmatch(value))


def _has_prefixed_id(value: object, prefix: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and len(value) > len(prefix)
        and not any(character.isspace() for character in value)
    )


def _first_by_id(records: Iterable[object]) -> dict[str, object]:
    records_by_id: dict[str, object] = {}
    for record in records:
        identifier = getattr(record, "id", None)
        if isinstance(identifier, str) and identifier and identifier not in records_by_id:
            records_by_id[identifier] = record
    return records_by_id


def _validate_ids(
    records: Iterable[object],
    *,
    kind: str,
    is_valid: Callable[[object], bool],
    issues: set[GraphValidationIssue],
) -> None:
    seen: set[str] = set()
    for record in records:
        identifier = getattr(record, "id", None)
        subject = _issue_subject(identifier)
        if not _has_text(identifier):
            issues.add(GraphValidationIssue(f"empty_{kind}_id", subject))
        if not is_valid(identifier):
            issues.add(GraphValidationIssue(f"invalid_{kind}_id", subject))
        if isinstance(identifier, str):
            if identifier in seen:
                issues.add(GraphValidationIssue(f"duplicate_{kind}_id", subject))
            seen.add(identifier)


def _reference_items(value: object) -> tuple[object, ...]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return ()


def _validate_source_references(
    *,
    owner: str,
    source_refs: object,
    source_ids: set[str],
    issues: set[GraphValidationIssue],
) -> None:
    for source_ref in _reference_items(source_refs):
        if not isinstance(source_ref, str) or source_ref not in source_ids:
            issues.add(
                GraphValidationIssue(
                    "dangling_source_ref",
                    f"{owner}->{_issue_subject(source_ref)}",
                )
            )


def _validate_external_source(
    source: SourceManifest,
    issues: set[GraphValidationIssue],
) -> None:
    if getattr(source, "namespace", None) in _EXTERNAL_NAMESPACES:
        return

    subject = _issue_subject(getattr(source, "id", None))
    required_fields = (
        ("source_version", "missing_external_source_version"),
        ("source_uri", "missing_external_source_uri"),
        ("license_id", "missing_external_source_license"),
        ("attribution", "missing_external_source_attribution"),
    )
    for field_name, code in required_fields:
        if not _has_text(getattr(source, field_name, None)):
            issues.add(GraphValidationIssue(code, subject))
    if not isinstance(source.checksum, str) or not _CHECKSUM.fullmatch(source.checksum):
        issues.add(GraphValidationIssue("invalid_external_source_checksum", subject))


def _known_sources(
    source_refs: object, source_by_id: Mapping[str, object]
) -> tuple[SourceManifest, ...]:
    sources: list[SourceManifest] = []
    for source_ref in _reference_items(source_refs):
        source = source_by_id.get(source_ref) if isinstance(source_ref, str) else None
        if isinstance(source, SourceManifest):
            sources.append(source)
    return tuple(sources)


def _edge_sources_match_scope(
    edge: ConceptEdge, sources: tuple[SourceManifest, ...]
) -> bool:
    if not sources:
        return True

    source_scopes = {source.tenant_scope for source in sources}
    if edge.scope == "global":
        return source_scopes == {"global"}
    if edge.scope == "tenant":
        return bool(source_scopes & {"workspace", "tenant"}) and not bool(
            source_scopes & {"profile", "proposed_shared"}
        )
    if edge.scope == "profile":
        return "profile" in source_scopes and "proposed_shared" not in source_scopes
    if edge.scope == "proposed_shared":
        return "proposed_shared" in source_scopes and not bool(
            source_scopes & {"workspace", "tenant", "profile"}
        )
    return False


def _add_relation(
    relations: dict[str, set[str]], subject_id: str, object_id: str
) -> None:
    relations.setdefault(subject_id, set()).add(object_id)


def _cyclic_subjects(relations: Mapping[str, set[str]]) -> tuple[str, ...]:
    """Return one stable representative for every cyclic strongly connected set."""

    node_ids = set(relations)
    for object_ids in relations.values():
        node_ids.update(object_ids)
    if not node_ids:
        return ()

    reverse_relations = {node_id: set() for node_id in node_ids}
    for subject_id, object_ids in relations.items():
        for object_id in object_ids:
            reverse_relations[object_id].add(subject_id)

    visited: set[str] = set()
    finish_order: list[str] = []

    for node_id in sorted(node_ids):
        if node_id not in visited:
            stack: list[tuple[str, bool]] = [(node_id, False)]
            while stack:
                current_id, expanded = stack.pop()
                if expanded:
                    finish_order.append(current_id)
                    continue
                if current_id in visited:
                    continue
                visited.add(current_id)
                stack.append((current_id, True))
                for object_id in reversed(sorted(relations.get(current_id, ()))):
                    if object_id not in visited:
                        stack.append((object_id, False))

    components: list[set[str]] = []
    visited.clear()

    for node_id in reversed(finish_order):
        if node_id in visited:
            continue
        component: set[str] = set()
        stack = [node_id]
        visited.add(node_id)
        while stack:
            current_id = stack.pop()
            component.add(current_id)
            for subject_id in reversed(sorted(reverse_relations[current_id])):
                if subject_id not in visited:
                    visited.add(subject_id)
                    stack.append(subject_id)
        components.append(component)

    cyclic_subjects = []
    for component in components:
        subject_id = min(component)
        if len(component) > 1 or subject_id in relations.get(subject_id, set()):
            cyclic_subjects.append(subject_id)
    return tuple(sorted(cyclic_subjects))


def _mapping_items(value: object) -> tuple[tuple[object, object], ...]:
    if isinstance(value, Mapping):
        return tuple(value.items())
    return ()


def _validate_legacy_projection(
    graph: CareerCapabilityGraph,
    node_by_id: Mapping[str, object],
    issues: set[GraphValidationIssue],
) -> None:
    projection = graph.legacy_projection
    concept_tokens = _mapping_items(getattr(projection, "concept_tokens", {}))
    domain_of = _mapping_items(getattr(projection, "domain_of", {}))
    domain_label = _mapping_items(getattr(projection, "domain_label", {}))
    category_of = _mapping_items(getattr(projection, "category_of", {}))

    concept_ids = {concept_id for concept_id, _ in concept_tokens}
    concept_ids.update(concept_id for concept_id, _ in domain_of)
    for concept_id in concept_ids:
        if not isinstance(concept_id, str) or concept_id not in node_by_id:
            issues.add(
                GraphValidationIssue(
                    "dangling_legacy_concept", _issue_subject(concept_id)
                )
            )

    projected_domains = {
        domain_id for _, domain_id in domain_of if isinstance(domain_id, str)
    }
    for domain_id, _ in domain_label:
        if not isinstance(domain_id, str) or domain_id not in projected_domains:
            issues.add(
                GraphValidationIssue(
                    "unprojected_legacy_domain_label", _issue_subject(domain_id)
                )
            )
    for domain_id, category in category_of:
        if not isinstance(domain_id, str) or domain_id not in projected_domains:
            issues.add(
                GraphValidationIssue(
                    "unprojected_legacy_category", _issue_subject(domain_id)
                )
            )
        if not isinstance(category, str) or category not in SKILL_GROUPS:
            issues.add(
                GraphValidationIssue("invalid_legacy_category", _issue_subject(domain_id))
            )


def validate_capability_graph(graph: CareerCapabilityGraph) -> None:
    """Raise one deterministically ordered error when graph invariants fail."""

    issues: set[GraphValidationIssue] = set()
    _validate_ids(
        graph.nodes,
        kind="node",
        is_valid=_is_node_id,
        issues=issues,
    )
    _validate_ids(
        graph.edges,
        kind="edge",
        is_valid=lambda value: _has_prefixed_id(value, "edge:"),
        issues=issues,
    )
    _validate_ids(
        graph.sources,
        kind="source",
        is_valid=lambda value: _has_prefixed_id(value, "source:"),
        issues=issues,
    )

    node_by_id = _first_by_id(graph.nodes)
    source_by_id = _first_by_id(graph.sources)
    source_ids = set(source_by_id)

    for source in graph.sources:
        _validate_external_source(source, issues)

    for node in graph.nodes:
        node_id = _issue_subject(node.id)
        _validate_source_references(
            owner=node_id,
            source_refs=node.source_refs,
            source_ids=source_ids,
            issues=issues,
        )
        for definition in node.definitions:
            _validate_source_references(
                owner=f"{node_id}:definition",
                source_refs=[definition.source_ref],
                source_ids=source_ids,
                issues=issues,
            )
        for alias in node.aliases:
            _validate_source_references(
                owner=f"{node_id}:alias",
                source_refs=[alias.source_ref],
                source_ids=source_ids,
                issues=issues,
            )

    alias_relations: dict[str, set[str]] = {}
    hierarchy_relations: dict[str, set[str]] = {}
    for edge in graph.edges:
        edge_id = _issue_subject(edge.id)
        _validate_source_references(
            owner=edge_id,
            source_refs=edge.source_refs,
            source_ids=source_ids,
            issues=issues,
        )
        if not _edge_sources_match_scope(
            edge, _known_sources(edge.source_refs, source_by_id)
        ):
            issues.add(GraphValidationIssue("invalid_edge_scope", edge_id))

        expected_direction = (
            "bidirectional"
            if edge.predicate in _BIDIRECTIONAL_PREDICATES
            else "directed"
        )
        if edge.direction != expected_direction:
            issues.add(GraphValidationIssue("invalid_edge_direction", edge_id))

        subject_node = (
            node_by_id.get(edge.subject_id)
            if isinstance(edge.subject_id, str)
            else None
        )
        object_node = (
            node_by_id.get(edge.object_id)
            if isinstance(edge.object_id, str)
            else None
        )
        if subject_node is None:
            issues.add(GraphValidationIssue("dangling_subject", edge_id))
        if object_node is None:
            issues.add(GraphValidationIssue("dangling_object", edge_id))
        if not isinstance(subject_node, ConceptNode) or not isinstance(
            object_node, ConceptNode
        ):
            continue

        signature = EDGE_SIGNATURES.get(edge.predicate)
        if signature is None:
            issues.add(GraphValidationIssue("unknown_edge_predicate", edge_id))
            continue
        subject_types, object_types = signature
        if subject_node.type not in subject_types or object_node.type not in object_types:
            issues.add(GraphValidationIssue("invalid_edge_signature", edge_id))

        if edge.predicate == "lexical_alias_of":
            if subject_node.type != object_node.type:
                issues.add(GraphValidationIssue("alias_type_mismatch", edge_id))
            # ClusterMap uses self-aliases as canonical anchors. They are
            # semantically no-ops, not alias cycles, while multi-node loops
            # remain forbidden.
            if edge.subject_id != edge.object_id:
                _add_relation(alias_relations, edge.subject_id, edge.object_id)
        elif edge.predicate == "broader_than":
            _add_relation(hierarchy_relations, edge.subject_id, edge.object_id)
        elif edge.predicate == "narrower_than":
            _add_relation(hierarchy_relations, edge.object_id, edge.subject_id)

    for subject_id in _cyclic_subjects(alias_relations):
        issues.add(GraphValidationIssue("alias_cycle", subject_id))
    for subject_id in _cyclic_subjects(hierarchy_relations):
        issues.add(GraphValidationIssue("hierarchy_cycle", subject_id))

    _validate_legacy_projection(graph, node_by_id, issues)

    if issues:
        raise GraphValidationError(issues)
