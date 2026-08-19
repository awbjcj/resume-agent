"""Bounded, policy-approved graph traversal for candidate retrieval only."""

from __future__ import annotations

from dataclasses import dataclass

from resume_agent.matching.models import RelationshipPath, RelationshipStep
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph, EdgeType

_DEFAULT_PREDICATES: frozenset[EdgeType] = frozenset(
    {
        "same_as",
        "equivalent_in_context",
        "broader_than",
        "narrower_than",
        "transferable_to",
        "prerequisite_for",
        "requires_capability",
        "requires_knowledge",
        "supports_task",
    }
)


@dataclass(frozen=True)
class TraversalPolicy:
    allowed_predicates: frozenset[EdgeType] = _DEFAULT_PREDICATES
    max_depth: int = 2
    minimum_confidence: float = 0.8
    visible_scopes: frozenset[str] = frozenset({"global"})

    def __post_init__(self) -> None:
        if self.max_depth < 0 or self.max_depth > 4:
            raise ValueError("max_depth must be between 0 and 4")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")


def find_paths(
    graph: CareerCapabilityGraph,
    *,
    start_id: str,
    target_id: str,
    policy: TraversalPolicy | None = None,
) -> list[RelationshipPath]:
    policy = policy or TraversalPolicy()
    if start_id == target_id:
        return [RelationshipPath()]
    adjacency: dict[str, list[RelationshipStep]] = {}
    for edge in graph.edges:
        if (
            edge.status != "approved"
            or edge.predicate not in policy.allowed_predicates
            or edge.confidence < policy.minimum_confidence
            or edge.scope not in policy.visible_scopes
        ):
            continue
        step = RelationshipStep(
            edge_id=edge.id,
            from_id=edge.subject_id,
            predicate=edge.predicate,
            to_id=edge.object_id,
            confidence=edge.confidence,
        )
        adjacency.setdefault(edge.subject_id, []).append(step)
        if edge.direction == "bidirectional":
            adjacency.setdefault(edge.object_id, []).append(
                RelationshipStep(
                    edge_id=edge.id,
                    from_id=edge.object_id,
                    predicate=edge.predicate,
                    to_id=edge.subject_id,
                    confidence=edge.confidence,
                )
            )
    for steps in adjacency.values():
        steps.sort(key=lambda item: (item.edge_id, item.to_id))

    found: list[RelationshipPath] = []
    queue: list[tuple[str, tuple[RelationshipStep, ...], frozenset[str]]] = [
        (start_id, (), frozenset({start_id}))
    ]
    while queue:
        node_id, steps, visited = queue.pop(0)
        if len(steps) >= policy.max_depth:
            continue
        for step in adjacency.get(node_id, []):
            if step.to_id in visited:
                continue
            next_steps = (*steps, step)
            if step.to_id == target_id:
                found.append(RelationshipPath(steps=list(next_steps)))
                continue
            queue.append((step.to_id, next_steps, visited | {step.to_id}))
    return sorted(
        found,
        key=lambda path: (len(path.steps), [step.edge_id for step in path.steps]),
    )
