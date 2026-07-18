"""Incremental skill classification behind one orchestration interface."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from resume_agent.concurrency import gather_isolated
from resume_agent.llm_runner import Runner, acall
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    merge_cluster_map,
    slugify_domain,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.canonicalize import (
    IncrementalDomainGroup,
    IncrementalSkillDomains,
    SkillClusters,
)
from resume_agent.tracking.match_gap import normalize_skill

ClassificationPhase = Literal["canonicalize", "domain"]


@dataclass(frozen=True)
class ClassificationFailure:
    phase: ClassificationPhase
    tokens: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ClassificationMetrics:
    canonical_batches: int
    domain_batches: int
    prompt_bytes: int
    max_in_flight: int
    elapsed_ms: int


@dataclass(frozen=True)
class ClassificationOutcome:
    additions: ClusterMap
    failures: tuple[ClassificationFailure, ...]
    metrics: ClassificationMetrics


class ReconcileError(RuntimeError):
    """Global canonical reconciliation failed; additions must not be saved."""


@dataclass(frozen=True)
class _AliasBatchResult:
    aliases: dict[str, str]
    failed_tokens: frozenset[str]


@dataclass(frozen=True)
class _DomainIntent:
    existing_domain_id: str | None = None
    new_label: str | None = None
    new_category: str | None = None


@dataclass(frozen=True)
class _DomainBatchResult:
    assignments: dict[str, _DomainIntent]
    failed_tokens: frozenset[str]


class _FlightMeter:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0

    def acquire(self) -> None:
        self.current += 1
        self.maximum = max(self.maximum, self.current)

    def release(self) -> None:
        self.current -= 1


def _shard(items: set[str], size: int) -> list[list[str]]:
    ordered = sorted(items)
    return [ordered[index : index + size] for index in range(0, len(ordered), size)]


def _project_aliases(
    content: object,
    *,
    batch: set[str],
    existing: set[str],
) -> _AliasBatchResult:
    if not isinstance(content, SkillClusters):
        return _AliasBatchResult({}, frozenset(batch))
    assignments: dict[str, str] = {}
    rejected: set[str] = set()
    allowed = batch | existing

    for raw_cluster in content.clusters:
        members: list[str] = []
        for raw in raw_cluster:
            token = normalize_skill(raw)
            if token in allowed and token not in members:
                members.append(token)
        new_members = [token for token in members if token in batch]
        existing_members = [token for token in members if token in existing]
        if not new_members:
            continue
        if len(existing_members) > 1 or (existing_members and members[0] != existing_members[0]):
            rejected.update(new_members)
            continue
        head = existing_members[0] if existing_members else members[0]
        for token in new_members:
            if token in assignments or token in rejected:
                assignments.pop(token, None)
                rejected.add(token)
            else:
                assignments[token] = head

    for token in rejected:
        assignments.pop(token, None)
    failed = batch - assignments.keys()
    return _AliasBatchResult(assignments, frozenset(failed))


def _project_domains(
    content: object,
    *,
    batch: set[str],
    existing_domain_ids: set[str],
    full_categories: set[str],
) -> _DomainBatchResult:
    if not isinstance(content, IncrementalSkillDomains):
        return _DomainBatchResult({}, frozenset(batch))
    assignments: dict[str, _DomainIntent] = {}
    rejected: set[str] = set()

    for group in content.domains:
        if not isinstance(group, IncrementalDomainGroup):
            continue
        existing_id = (group.existing_domain_id or "").strip() or None
        new_label = (group.new_label or "").strip() or None
        new_category = (group.new_category or "").strip() or None
        valid_mode = (existing_id is None) != (new_label is None)
        if existing_id is not None and (
            new_category is not None or existing_id not in existing_domain_ids
        ):
            valid_mode = False
        if new_label is not None:
            if not any(char.isalnum() for char in new_label):
                valid_mode = False
            if new_category not in SKILL_GROUPS or new_category in full_categories:
                valid_mode = False
        intent = _DomainIntent(
            existing_domain_id=existing_id,
            new_label=new_label,
            new_category=new_category,
        )
        members = [normalize_skill(raw) for raw in group.skills]
        authoritative = [token for token in members if token in batch]
        if not valid_mode:
            rejected.update(authoritative)
            continue
        for token in authoritative:
            if members.count(token) > 1 or token in assignments or token in rejected:
                assignments.pop(token, None)
                rejected.add(token)
            else:
                assignments[token] = intent

    for token in rejected:
        assignments.pop(token, None)
    failed = batch - assignments.keys()
    return _DomainBatchResult(assignments, frozenset(failed))


def _category_context(cmap: ClusterMap, cap: int) -> list[dict[str, Any]]:
    members: dict[str, list[str]] = {}
    for skill, domain_id in cmap.domain_of.items():
        members.setdefault(domain_id, []).append(skill)
    domains_by_category: dict[str, list[dict[str, Any]]] = {}
    domain_ids = set(cmap.domain_label) | set(members)
    for domain_id in sorted(domain_ids):
        slug = cmap.category_of.get(domain_id, "other")
        domains_by_category.setdefault(slug, []).append(
            {
                "id": domain_id,
                "label": cmap.domain_label.get(domain_id, domain_id),
                "skills": sorted(members.get(domain_id, [])),
            }
        )
    return [
        {
            "slug": slug,
            "label": label,
            "full": len(domains_by_category.get(slug, [])) >= cap,
            "domains": domains_by_category.get(slug, []),
        }
        for slug, label in SKILL_GROUPS.items()
    ]


def _admit_new_domains(
    existing: ClusterMap,
    assignments: dict[str, _DomainIntent],
    category_cap: int,
) -> tuple[dict[str, _DomainIntent], set[str]]:
    counts = {slug: 0 for slug in SKILL_GROUPS}
    for domain_id in set(existing.domain_of.values()) | set(existing.domain_label):
        counts[existing.category_of.get(domain_id, "other")] += 1
    existing_identities = {
        (normalize_skill(label), existing.category_of.get(domain_id, "other"))
        for domain_id, label in existing.domain_label.items()
    }
    admitted_identities: set[tuple[str, str]] = set()
    admitted: dict[str, _DomainIntent] = {}
    rejected: set[str] = set()
    for token, intent in assignments.items():
        if intent.existing_domain_id is not None:
            admitted[token] = intent
            continue
        assert intent.new_label is not None and intent.new_category is not None
        identity = (normalize_skill(intent.new_label), intent.new_category)
        if identity not in existing_identities and identity not in admitted_identities:
            if counts[intent.new_category] >= category_cap:
                rejected.add(token)
                continue
            counts[intent.new_category] += 1
            admitted_identities.add(identity)
        admitted[token] = intent
    return admitted, rejected


def _allocate_domain_proposals(
    existing: ClusterMap, assignments: dict[str, _DomainIntent]
) -> dict[tuple[str, str], str]:
    existing_by_identity = {
        (normalize_skill(label), existing.category_of.get(domain_id, "other")): domain_id
        for domain_id, label in existing.domain_label.items()
    }
    proposals = {
        (normalize_skill(intent.new_label), intent.new_category): intent.new_label.strip()
        for intent in assignments.values()
        if intent.new_label is not None and intent.new_category is not None
    }
    occupied = set(existing.domain_label) | set(existing.domain_of.values())
    allocated: dict[tuple[str, str], str] = {}
    for identity in sorted(proposals):
        if identity in existing_by_identity:
            allocated[identity] = existing_by_identity[identity]
            continue
        base = slugify_domain(proposals[identity])
        domain_id, suffix = base, 2
        while domain_id in occupied:
            domain_id = f"{base}-{suffix}"
            suffix += 1
        occupied.add(domain_id)
        allocated[identity] = domain_id
    return allocated


async def classify_incrementally(
    *,
    demanded_tokens: set[str],
    existing: ClusterMap,
    canonicalizer: Runner,
    themer: Runner,
    batch_size: int,
    concurrency: int,
    category_cap: int,
    reporter: ProgressReporter | None = None,
) -> ClassificationOutcome:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if category_cap < 1:
        raise ValueError("category_cap must be at least 1")

    started = time.monotonic()
    semaphore = asyncio.Semaphore(concurrency)
    meter = _FlightMeter()
    prompt_bytes = 0
    failures: list[ClassificationFailure] = []
    alias_delta = demanded_tokens - existing.aliases.keys()
    alias_batches = _shard(alias_delta, batch_size)
    stable_canonicals = set(existing.aliases.values())

    async def canonicalize(batch: list[str], existing_canonicals: list[str]):
        nonlocal prompt_bytes
        prompt = json.dumps(
            {"new": batch, "existing_canonicals": existing_canonicals},
            separators=(",", ":"),
        )
        prompt_bytes += len(prompt.encode("utf-8"))
        response = await acall(
            canonicalizer,
            prompt,
            sem=semaphore,
            on_acquire=meter.acquire,
            on_release=meter.release,
        )
        return _project_aliases(
            response.content,
            batch=set(batch),
            existing=set(existing_canonicals),
        )

    aliases: dict[str, str] = {}
    if alias_batches:
        if reporter is not None:
            reporter.begin(len(alias_batches), "Canonicalizing skills")
        canonical_results = await gather_isolated(
            alias_batches,
            lambda batch: canonicalize(batch, sorted(stable_canonicals)),
            on_complete=(
                (lambda completed: reporter.step(completed, label="Canonicalizing skills"))
                if reporter is not None
                else None
            ),
            checkpoint=reporter.checkpoint if reporter is not None else None,
        )
        for batch, result in zip(alias_batches, canonical_results, strict=True):
            if not result.ok or result.value is None:
                failures.append(
                    ClassificationFailure(
                        "canonicalize", tuple(batch), str(result.error or "model call failed")
                    )
                )
                continue
            aliases.update(result.value.aliases)
            if result.value.failed_tokens:
                failures.append(
                    ClassificationFailure(
                        "canonicalize",
                        tuple(sorted(result.value.failed_tokens)),
                        "invalid or incomplete model output",
                    )
                )

    new_heads = set(aliases.values()) - stable_canonicals
    if new_heads:
        if reporter is not None:
            reporter.begin(1, "Reconciling skill synonyms")
        try:
            reconciled = await canonicalize(sorted(new_heads), sorted(stable_canonicals))
        except Exception as exc:
            raise ReconcileError(f"reconcile failed: {exc}") from exc
        if reconciled.failed_tokens:
            raise ReconcileError(
                f"reconcile returned invalid output for {sorted(reconciled.failed_tokens)!r}"
            )
        aliases = {
            token: reconciled.aliases.get(head, head) for token, head in aliases.items()
        }
        if reporter is not None:
            reporter.step(1, label="Reconciled skill synonyms")

    alias_additions = ClusterMap(aliases=aliases)
    merged_aliases = merge_cluster_map(existing, alias_additions).aliases
    demanded_canonicals = {
        merged_aliases[token] for token in demanded_tokens if token in merged_aliases
    }
    domain_backlog = demanded_canonicals - existing.domain_of.keys()
    domain_batches = _shard(domain_backlog, batch_size)
    domain_assignments: dict[str, _DomainIntent] = {}
    existing_domain_ids = set(existing.domain_label) | set(existing.domain_of.values())
    category_context = _category_context(existing, category_cap)
    full_categories = {
        entry["slug"] for entry in category_context if entry["full"]
    }

    async def classify_domains(batch: list[str]):
        nonlocal prompt_bytes
        prompt = json.dumps(
            {"new": batch, "categories": category_context},
            separators=(",", ":"),
        )
        prompt_bytes += len(prompt.encode("utf-8"))
        response = await acall(
            themer,
            prompt,
            sem=semaphore,
            on_acquire=meter.acquire,
            on_release=meter.release,
        )
        return _project_domains(
            response.content,
            batch=set(batch),
            existing_domain_ids=existing_domain_ids,
            full_categories=full_categories,
        )

    if domain_batches:
        if reporter is not None:
            reporter.begin(len(domain_batches), "Grouping skills into domains")
        domain_results = await gather_isolated(
            domain_batches,
            classify_domains,
            on_complete=(
                (lambda completed: reporter.step(completed, label="Grouping skills into domains"))
                if reporter is not None
                else None
            ),
            checkpoint=reporter.checkpoint if reporter is not None else None,
        )
        for batch, result in zip(domain_batches, domain_results, strict=True):
            if not result.ok or result.value is None:
                failures.append(
                    ClassificationFailure(
                        "domain", tuple(batch), str(result.error or "model call failed")
                    )
                )
                continue
            domain_assignments.update(result.value.assignments)
            if result.value.failed_tokens:
                failures.append(
                    ClassificationFailure(
                        "domain",
                        tuple(sorted(result.value.failed_tokens)),
                        "invalid or incomplete model output",
                    )
                )
    elif not alias_batches and reporter is not None:
        reporter.begin(1, "Checking skill clusters")
        reporter.step(1)

    domain_assignments, cap_rejected = _admit_new_domains(
        existing, domain_assignments, category_cap
    )
    if cap_rejected:
        failures.append(
            ClassificationFailure(
                "domain",
                tuple(sorted(cap_rejected)),
                "category domain cap reached during deterministic admission",
            )
        )
    allocated = _allocate_domain_proposals(existing, domain_assignments)
    domain_of: dict[str, str] = {}
    domain_label: dict[str, str] = {}
    category_of: dict[str, str] = {}
    for token, intent in domain_assignments.items():
        if intent.existing_domain_id is not None:
            domain_of[token] = intent.existing_domain_id
            continue
        assert intent.new_label is not None and intent.new_category is not None
        identity = (normalize_skill(intent.new_label), intent.new_category)
        domain_id = allocated[identity]
        domain_of[token] = domain_id
        if domain_id not in existing.domain_label:
            domain_label.setdefault(domain_id, intent.new_label)
            category_of.setdefault(domain_id, intent.new_category)

    if reporter is not None:
        reporter.checkpoint()
    metrics = ClassificationMetrics(
        canonical_batches=len(alias_batches),
        domain_batches=len(domain_batches),
        prompt_bytes=prompt_bytes,
        max_in_flight=meter.maximum,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    return ClassificationOutcome(
        additions=ClusterMap(
            aliases=aliases,
            domain_of=domain_of,
            domain_label=domain_label,
            category_of=category_of,
        ),
        failures=tuple(failures),
        metrics=metrics,
    )
