"""Incremental skill classification behind one orchestration interface."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from resume_agent.concurrency import gather_isolated
from resume_agent.llm_runner import Runner, acall
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    merge_cluster_map,
    slugify_domain,
)
from resume_agent.taxonomy.embeddings import CandidateContext
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
    embedding_mode: str = "none"


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
    confidence: Literal["high", "medium", "low"] = "high"
    reason: str = ""


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
        if len(existing_members) > 1 or (
            existing_members and members[0] != existing_members[0]
        ):
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
    allowed_domain_ids: set[str] | None = None,
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
        confidence = group.confidence
        reason = group.reason.strip()
        valid_mode = (existing_id is None) != (new_label is None)
        if existing_id is not None and (
            new_category is not None
            or existing_id not in existing_domain_ids
            or (
                allowed_domain_ids is not None and existing_id not in allowed_domain_ids
            )
        ):
            valid_mode = False
        if new_label is not None:
            if not any(char.isalnum() for char in new_label):
                valid_mode = False
            if new_category not in SKILL_GROUPS or new_category in full_categories:
                valid_mode = False
        if confidence != "high":
            valid_mode = False
        intent = _DomainIntent(
            existing_domain_id=existing_id,
            new_label=new_label,
            new_category=new_category,
            confidence=confidence,
            reason=reason,
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


def _category_context(
    cmap: ClusterMap, cap: int, domain_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    members: dict[str, list[str]] = {}
    for skill, domain_id in cmap.domain_of.items():
        members.setdefault(domain_id, []).append(skill)
    domains_by_category: dict[str, list[dict[str, Any]]] = {}
    present_domain_ids = set(cmap.domain_label) | set(members)
    visible_domain_ids = present_domain_ids if domain_ids is None else domain_ids
    for domain_id in sorted(visible_domain_ids):
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
    *,
    allow_category_growth: bool,
    min_new_domain_members: int,
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
    proposed_members: dict[tuple[str, str], list[str]] = {}
    for token, intent in assignments.items():
        if intent.new_label is not None and intent.new_category is not None:
            identity = (normalize_skill(intent.new_label), intent.new_category)
            proposed_members.setdefault(identity, []).append(token)
    for token, intent in assignments.items():
        if intent.existing_domain_id is not None:
            admitted[token] = intent
            continue
        assert intent.new_label is not None and intent.new_category is not None
        identity = (normalize_skill(intent.new_label), intent.new_category)
        if (
            identity not in existing_identities
            and len(proposed_members.get(identity, [])) < min_new_domain_members
        ):
            rejected.add(token)
            continue
        if identity not in existing_identities and identity not in admitted_identities:
            if (
                not allow_category_growth
                and counts[intent.new_category] >= category_cap
            ):
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
        (
            normalize_skill(label),
            existing.category_of.get(domain_id, "other"),
        ): domain_id
        for domain_id, label in existing.domain_label.items()
    }
    proposals = {
        (
            normalize_skill(intent.new_label),
            intent.new_category,
        ): intent.new_label.strip()
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
    reconcile_batch_size: int,
    reporter: ProgressReporter | None = None,
    candidate_context: CandidateContext | None = None,
    allow_category_growth: bool = False,
    min_new_domain_members: int = 1,
    category_hints: Mapping[str, str] | None = None,
) -> ClassificationOutcome:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if category_cap < 1:
        raise ValueError("category_cap must be at least 1")
    if reconcile_batch_size < 1:
        raise ValueError("reconcile_batch_size must be at least 1")
    if min_new_domain_members < 1:
        raise ValueError("min_new_domain_members must be at least 1")

    started = time.monotonic()
    semaphore = asyncio.Semaphore(concurrency)
    meter = _FlightMeter()
    prompt_bytes = 0
    failures: list[ClassificationFailure] = []
    alias_delta = demanded_tokens - existing.aliases.keys()
    alias_batches = _shard(alias_delta, batch_size)
    # A migrated map can legitimately have a direct domain key without a
    # redundant ``canonical -> canonical`` alias.  Keep it stable during
    # synonym reconciliation rather than asking the LLM to rediscover it.
    stable_canonicals = set(existing.aliases.values()) | set(existing.domain_of)

    async def canonicalize(
        batch: list[str], existing_canonicals: list[str], *, use_candidates: bool
    ):
        nonlocal prompt_bytes
        candidate_canonicals = (
            sorted(
                {
                    candidate
                    for token in batch
                    for candidate in candidate_context.canonical_candidates.get(
                        token, ()
                    )
                }
            )
            if use_candidates and candidate_context is not None
            else existing_canonicals
        )
        prompt = json.dumps(
            {"new": batch, "existing_canonicals": candidate_canonicals},
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
            existing=set(candidate_canonicals),
        )

    aliases: dict[str, str] = {}
    if alias_batches:
        if reporter is not None:
            reporter.begin(len(alias_batches), "Canonicalizing skills")
        canonical_results = await gather_isolated(
            alias_batches,
            lambda batch: canonicalize(
                batch, sorted(stable_canonicals), use_candidates=True
            ),
            on_complete=(
                (
                    lambda completed: reporter.step(
                        completed, label="Canonicalizing skills"
                    )
                )
                if reporter is not None
                else None
            ),
            checkpoint=reporter.checkpoint if reporter is not None else None,
        )
        for batch, result in zip(alias_batches, canonical_results, strict=True):
            if not result.ok or result.value is None:
                failures.append(
                    ClassificationFailure(
                        "canonicalize",
                        tuple(batch),
                        str(result.error or "model call failed"),
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
        # Reconcile merges synonyms that separate alias batches minted
        # independently (batch A made 'k8s' canonical, batch B made 'kube'
        # canonical). Two properties matter:
        #
        #   * Partial coverage is NOT fatal. Every head here is already a valid
        #     canonical from its own batch; reconcile is only a cross-batch
        #     merge refinement. A head the merge pass leaves untouched simply
        #     stays its own canonical (identity alias) — the same state any
        #     canonical stable across runs is already in. A backlog of hundreds
        #     of noisy tokens (many not real skills) will always leave some
        #     heads unmerged, so aborting the whole run on that is wrong; we
        #     keep them and record the gap for observability. Only a failed
        #     model CALL aborts (transactional: the last-good file is kept).
        #   * Chunked, not one call. Sending hundreds of heads in a single
        #     structured-output call is what degrades coverage in the first
        #     place. When candidate retrieval is available, each chunk gets
        #     only its bounded semantic neighbours; the legacy all-head
        #     context remains a no-embedding fallback for standalone callers.
        reconcile_shards = _shard(new_heads, reconcile_batch_size)
        if reporter is not None:
            reporter.begin(len(reconcile_shards), "Reconciling skill synonyms")
        reconciled_aliases: dict[str, str] = {}
        running_stable = set(stable_canonicals)
        for shard_index, shard in enumerate(reconcile_shards, start=1):
            try:
                reconciled = await canonicalize(
                    sorted(shard),
                    sorted(running_stable),
                    use_candidates=candidate_context is not None,
                )
            except Exception as exc:
                raise ReconcileError(f"reconcile failed: {exc}") from exc
            reconciled_aliases.update(reconciled.aliases)
            # Every head in this shard is now a canonical the next chunk may
            # reuse — whether the model merged it or it stayed itself.
            running_stable |= set(shard)
            if reconciled.failed_tokens:
                failures.append(
                    ClassificationFailure(
                        "canonicalize",
                        tuple(sorted(reconciled.failed_tokens)),
                        "reconcile left new canonicals unmerged; kept as-is",
                    )
                )
            if reporter is not None:
                reporter.step(shard_index, label="Reconciled skill synonyms")
        # Uncovered heads fall through .get(head, head) unchanged.
        aliases = {
            token: reconciled_aliases.get(head, head) for token, head in aliases.items()
        }

    alias_additions = ClusterMap(aliases=aliases)
    merged_aliases = merge_cluster_map(existing, alias_additions).aliases
    # Legacy profile-group hints can be recorded against an alias (for example
    # ``k8s``) while this pass has just selected its canonical (``kubernetes``).
    # Translate them once at the canonical boundary; they are still advisory
    # prompt context, never an assignment source.
    resolved_category_hints: dict[str, str] = {}
    if category_hints is not None:
        for raw_token, raw_category in sorted(category_hints.items()):
            token = normalize_skill(raw_token)
            category = raw_category.strip()
            if token and category in SKILL_GROUPS:
                resolved_category_hints.setdefault(
                    merged_aliases.get(token, token), category
                )
    demanded_canonicals = {
        merged_aliases[token] for token in demanded_tokens if token in merged_aliases
    }
    domain_backlog = demanded_canonicals - existing.domain_of.keys()
    domain_batches = _shard(domain_backlog, batch_size)
    domain_assignments: dict[str, _DomainIntent] = {}
    existing_domain_ids = set(existing.domain_label) | set(existing.domain_of.values())
    base_category_context = _category_context(existing, category_cap)
    soft_target_by_slug = {
        entry["slug"]: bool(entry["full"]) for entry in base_category_context
    }
    # The old context called this state "full" because it was a hard cap.
    # A target-taxonomy refresh instead exposes it only as an advisory soft
    # target; the deterministic global coherence gate decides whether growth
    # past it is safe.
    category_context = (
        [
            {
                **entry,
                "full": False,
                "at_soft_target": soft_target_by_slug[entry["slug"]],
            }
            for entry in base_category_context
        ]
        if allow_category_growth
        else base_category_context
    )
    full_categories = (
        {entry["slug"] for entry in base_category_context if entry["full"]}
        if not allow_category_growth
        else set()
    )

    async def classify_domains(batch: list[str]):
        nonlocal prompt_bytes
        allowed_domain_ids: set[str] | None = None
        prompt_context = category_context
        if candidate_context is not None:
            allowed_domain_ids = {
                domain_id
                for token in batch
                for domain_id in candidate_context.domain_candidates.get(token, ())
            }
            prompt_context = _category_context(
                existing, category_cap, allowed_domain_ids
            )
            if allow_category_growth:
                prompt_context = [
                    {
                        **entry,
                        "full": False,
                        "at_soft_target": soft_target_by_slug[entry["slug"]],
                    }
                    for entry in prompt_context
                ]
        prompt = json.dumps(
            {
                "new": batch,
                "categories": prompt_context,
                # A legacy profile group may guide initial placement during
                # migration, but the model still has to emit a valid current
                # category/domain decision and it never becomes a read-path
                # source of truth.
                "category_hints": {
                    token: resolved_category_hints[token]
                    for token in batch
                    if token in resolved_category_hints
                },
                "neighbouring_unresolved": {
                    token: list(candidate_context.peer_candidates.get(token, ()))
                    for token in batch
                    if candidate_context is not None
                },
            },
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
            allowed_domain_ids=allowed_domain_ids,
        )

    if domain_batches:
        if reporter is not None:
            reporter.begin(len(domain_batches), "Grouping skills into domains")
        domain_results = await gather_isolated(
            domain_batches,
            classify_domains,
            on_complete=(
                (
                    lambda completed: reporter.step(
                        completed, label="Grouping skills into domains"
                    )
                )
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
        existing,
        domain_assignments,
        category_cap,
        allow_category_growth=allow_category_growth,
        min_new_domain_members=min_new_domain_members,
    )
    if cap_rejected:
        failures.append(
            ClassificationFailure(
                "domain",
                tuple(sorted(cap_rejected)),
                "new-domain proposal did not meet the deterministic coherence gate",
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
        embedding_mode=candidate_context.mode
        if candidate_context is not None
        else "none",
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
