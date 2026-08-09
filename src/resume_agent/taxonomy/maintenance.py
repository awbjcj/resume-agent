"""Versionable, correction-aware maintenance of model-owned skill domains."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Iterable

from resume_agent.llm_runner import Runner, acall
from resume_agent.taxonomy.clusters import ClusterMap, slugify_domain
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.embeddings import (
    EmbeddingProvider,
    domain_neighbor_candidates,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.canonicalize import (
    TaxonomyMaintenanceAction,
    TaxonomyMaintenancePlan,
)
from resume_agent.tracking.match_gap import normalize_skill


MAINTENANCE_CHUNK_SIZE = 20


@dataclass(frozen=True)
class MaintenanceOutcome:
    cluster_map: ClusterMap
    actions: tuple[TaxonomyMaintenanceAction, ...]
    rejected_actions: tuple[str, ...]
    embedding_mode: str
    churned_skills: int

    @property
    def changed(self) -> bool:
        return bool(self.actions)


def _members(cmap: ClusterMap, domain_id: str) -> set[str]:
    return {token for token, value in cmap.domain_of.items() if value == domain_id}


def pinned_domains_and_skills(
    cmap: ClusterMap, corrections: TaxonomyCorrections
) -> tuple[set[str], set[str]]:
    """Infer model-owned versus user-pinned state from the durable intent ledger."""

    domains = (
        set(corrections.domain_renames)
        | set(corrections.domain_category)
        | set(corrections.domain_merges)
        | set(corrections.domain_merges.values())
        | set(corrections.skill_domain.values())
    )
    pinned_tokens = (
        set(corrections.skill_domain)
        | set(corrections.aliases)
        | set(corrections.aliases.values())
        | set(corrections.added_skills)
        | set(corrections.removed_skills)
    )
    skills = {
        cmap.aliases.get(normalize_skill(token), normalize_skill(token))
        for token in pinned_tokens
        if normalize_skill(token)
    }
    return domains, skills


def _domain_payload(cmap: ClusterMap, domain_id: str) -> dict[str, object]:
    return {
        "id": domain_id,
        "label": cmap.domain_label.get(domain_id, domain_id),
        "category": cmap.category_of.get(domain_id, "other"),
        "skills": sorted(_members(cmap, domain_id)),
    }


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


async def _judge_actions(
    *,
    cmap: ClusterMap,
    judge: Runner,
    pinned_domains: set[str],
    neighbours: dict[str, tuple[str, ...]],
) -> tuple[list[TaxonomyMaintenanceAction], list[str]]:
    model_owned = sorted(
        domain_id
        for domain_id in set(cmap.domain_of.values()) | set(cmap.domain_label)
        if domain_id not in pinned_domains
    )
    actions: list[TaxonomyMaintenanceAction] = []
    failures: list[str] = []
    semaphore = asyncio.Semaphore(1)
    for shard in _chunks(model_owned, MAINTENANCE_CHUNK_SIZE):
        included = set(shard)
        for domain_id in shard:
            included.update(neighbours.get(domain_id, ()))
        payload = {
            "domains": [
                _domain_payload(cmap, domain_id) for domain_id in sorted(included)
            ],
            "focus_domain_ids": shard,
            "neighbours": {
                domain_id: list(neighbours.get(domain_id, ())) for domain_id in shard
            },
            "pinned_domain_ids": sorted(pinned_domains),
            "categories": SKILL_GROUPS,
        }
        try:
            response = await acall(
                judge, json.dumps(payload, separators=(",", ":")), sem=semaphore
            )
        except Exception as exc:  # noqa: BLE001 - maintenance can safely skip a shard
            failures.append(f"maintenance judge failed: {exc}")
            continue
        content = response.content
        if not isinstance(content, TaxonomyMaintenancePlan):
            failures.append("maintenance judge returned invalid output")
            continue
        actions.extend(content.actions)
    return actions, failures


def _allocate_id(label: str, occupied: set[str]) -> str | None:
    base = slugify_domain(label)
    if not base:
        return None
    candidate, suffix = base, 2
    while candidate in occupied:
        candidate = f"{base}-{suffix}"
        suffix += 1
    occupied.add(candidate)
    return candidate


def _copy_map(cmap: ClusterMap) -> ClusterMap:
    return ClusterMap(
        aliases=dict(cmap.aliases),
        domain_of=dict(cmap.domain_of),
        domain_label=dict(cmap.domain_label),
        category_of=dict(cmap.category_of),
    )


def _apply_actions(
    *,
    cmap: ClusterMap,
    actions: Iterable[TaxonomyMaintenanceAction],
    pinned_domains: set[str],
    pinned_skills: set[str],
) -> tuple[ClusterMap, list[TaxonomyMaintenanceAction], list[str]]:
    candidate = _copy_map(cmap)
    accepted: list[TaxonomyMaintenanceAction] = []
    rejected: list[str] = []
    occupied = set(candidate.domain_label) | set(candidate.domain_of.values())

    for action in actions:
        if action.confidence != "high":
            rejected.append(f"{action.kind}: confidence is not high")
            continue
        domain_id = action.domain_id.strip()
        if domain_id not in occupied or domain_id in pinned_domains:
            rejected.append(f"{action.kind}: domain is unknown or pinned")
            continue
        if action.kind == "merge":
            target = action.target_domain_id.strip()
            if (
                not target
                or target == domain_id
                or target not in occupied
                or target in pinned_domains
            ):
                rejected.append("merge: target is unknown, identical, or pinned")
                continue
            if _members(candidate, domain_id) & pinned_skills:
                rejected.append("merge: source contains a user-pinned skill")
                continue
            candidate.domain_of = {
                token: target if value == domain_id else value
                for token, value in candidate.domain_of.items()
            }
            candidate.domain_label.pop(domain_id, None)
            candidate.category_of.pop(domain_id, None)
            occupied.discard(domain_id)
            accepted.append(action)
            continue
        if action.kind == "rename":
            label = action.label.strip()
            if not label or not slugify_domain(label):
                rejected.append("rename: label is blank or invalid")
                continue
            if candidate.domain_label.get(domain_id) == label:
                continue
            candidate.domain_label[domain_id] = label
            accepted.append(action)
            continue
        if action.kind == "reparent":
            category = action.category.strip()
            if category not in SKILL_GROUPS:
                rejected.append("reparent: category is invalid")
                continue
            if candidate.category_of.get(domain_id, "other") == category:
                continue
            candidate.category_of[domain_id] = category
            accepted.append(action)
            continue
        if action.kind == "split":
            members = _members(candidate, domain_id)
            if members & pinned_skills:
                rejected.append("split: domain contains a user-pinned skill")
                continue
            clusters = [
                {normalize_skill(token) for token in cluster if normalize_skill(token)}
                for cluster in action.clusters
            ]
            if (
                len(clusters) < 2
                or any(len(cluster) < 2 for cluster in clusters)
                or set().union(*clusters) != members
                or sum(len(cluster) for cluster in clusters) != len(members)
            ):
                rejected.append(
                    "split: clusters must be a disjoint full partition with two skills each"
                )
                continue
            labels = [label.strip() for label in action.labels]
            if len(labels) != len(clusters) or any(
                not slugify_domain(label) for label in labels
            ):
                rejected.append("split: every cluster needs a valid label")
                continue
            categories = [category.strip() for category in action.categories]
            if not categories:
                categories = [candidate.category_of.get(domain_id, "other")] * len(
                    clusters
                )
            if len(categories) != len(clusters) or any(
                category not in SKILL_GROUPS for category in categories
            ):
                rejected.append("split: every cluster needs a valid category")
                continue
            ordered = sorted(
                zip(clusters, labels, categories, strict=True),
                key=lambda item: item[1].casefold(),
            )
            first_cluster, first_label, first_category = ordered[0]
            for token in first_cluster:
                candidate.domain_of[token] = domain_id
            candidate.domain_label[domain_id] = first_label
            candidate.category_of[domain_id] = first_category
            for cluster, label, category in ordered[1:]:
                new_id = _allocate_id(label, occupied)
                assert new_id is not None
                for token in cluster:
                    candidate.domain_of[token] = new_id
                candidate.domain_label[new_id] = label
                candidate.category_of[new_id] = category
            accepted.append(action)
            continue
        rejected.append(f"{action.kind}: unsupported action")
    return candidate, accepted, rejected


async def maintain_taxonomy(
    *,
    cluster_path: str,
    cmap: ClusterMap,
    corrections: TaxonomyCorrections,
    judge: Runner,
    max_churn: float,
    embedding_provider: EmbeddingProvider | None = None,
) -> MaintenanceOutcome:
    """Produce one quality-gated model-owned taxonomy generation."""

    if not 0 < max_churn <= 1:
        raise ValueError("max_churn must be between zero and one")
    pinned_domains, pinned_skills = pinned_domains_and_skills(cmap, corrections)
    mode, neighbours = await domain_neighbor_candidates(
        cluster_path=cluster_path, cmap=cmap, provider=embedding_provider
    )
    proposed, failures = await _judge_actions(
        cmap=cmap,
        judge=judge,
        pinned_domains=pinned_domains,
        neighbours=neighbours,
    )
    # Candidate retrieval is advisory rather than an assignment mechanism, but
    # a merge still has to be between a domain and one of the bounded semantic
    # neighbours shown to the judge.  That prevents an otherwise-valid model
    # response from reaching across the complete taxonomy on an invented hunch.
    candidate_actions: list[TaxonomyMaintenanceAction] = []
    for action in proposed:
        if action.kind == "merge" and action.target_domain_id not in neighbours.get(
            action.domain_id, ()
        ):
            failures.append("merge target was not an embedding candidate")
            continue
        candidate_actions.append(action)
    candidate, accepted, rejected = _apply_actions(
        cmap=cmap,
        actions=candidate_actions,
        pinned_domains=pinned_domains,
        pinned_skills=pinned_skills,
    )
    unlocked = set(cmap.domain_of) - pinned_skills
    churned = sum(
        cmap.domain_of.get(token) != candidate.domain_of.get(token)
        for token in unlocked
    )
    maximum = max(1, int(len(unlocked) * max_churn)) if unlocked else 0
    if churned > maximum:
        return MaintenanceOutcome(
            cluster_map=cmap,
            actions=(),
            rejected_actions=tuple(
                [*failures, *rejected, "maintenance churn exceeds configured limit"]
            ),
            embedding_mode=mode,
            churned_skills=churned,
        )
    before_unassigned = set(cmap.aliases.values()) - set(cmap.domain_of)
    after_unassigned = set(candidate.aliases.values()) - set(candidate.domain_of)
    if len(after_unassigned) > len(before_unassigned):
        return MaintenanceOutcome(
            cluster_map=cmap,
            actions=(),
            rejected_actions=tuple(
                [*failures, *rejected, "maintenance increased unassigned skills"]
            ),
            embedding_mode=mode,
            churned_skills=churned,
        )
    return MaintenanceOutcome(
        cluster_map=candidate,
        actions=tuple(accepted),
        rejected_actions=tuple([*failures, *rejected]),
        embedding_mode=mode,
        churned_skills=churned,
    )
