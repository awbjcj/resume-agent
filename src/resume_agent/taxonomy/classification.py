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
    allocate_theme_ids,
    merge_cluster_map,
)
from resume_agent.tracking.canonicalize import (
    IncrementalSkillThemes,
    IncrementalThemeGroup,
    SkillClusters,
)
from resume_agent.tracking.match_gap import normalize_skill

ClassificationPhase = Literal["canonicalize", "theme"]


@dataclass(frozen=True)
class ClassificationFailure:
    phase: ClassificationPhase
    tokens: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ClassificationMetrics:
    canonical_batches: int
    theme_batches: int
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
class _ThemeIntent:
    existing_theme_id: str | None = None
    new_label: str | None = None


@dataclass(frozen=True)
class _ThemeBatchResult:
    assignments: dict[str, _ThemeIntent]
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


def _project_themes(
    content: object,
    *,
    batch: set[str],
    existing_theme_ids: set[str],
) -> _ThemeBatchResult:
    if not isinstance(content, IncrementalSkillThemes):
        return _ThemeBatchResult({}, frozenset(batch))
    assignments: dict[str, _ThemeIntent] = {}
    rejected: set[str] = set()

    for group in content.themes:
        if not isinstance(group, IncrementalThemeGroup):
            continue
        existing_id = (group.existing_theme_id or "").strip() or None
        new_label = (group.new_label or "").strip() or None
        valid_mode = (existing_id is None) != (new_label is None)
        if existing_id is not None and existing_id not in existing_theme_ids:
            valid_mode = False
        if new_label is not None and not any(char.isalnum() for char in new_label):
            valid_mode = False
        intent = _ThemeIntent(existing_theme_id=existing_id, new_label=new_label)
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
    return _ThemeBatchResult(assignments, frozenset(failed))


def _existing_theme_context(cmap: ClusterMap) -> list[dict[str, Any]]:
    members: dict[str, list[str]] = {}
    for skill, theme_id in cmap.theme_of.items():
        members.setdefault(theme_id, []).append(skill)
    theme_ids = set(cmap.theme_label) | set(members)
    return [
        {
            "id": theme_id,
            "label": cmap.theme_label.get(theme_id, theme_id),
            "skills": sorted(members.get(theme_id, [])),
        }
        for theme_id in sorted(theme_ids)
    ]


async def classify_incrementally(
    *,
    demanded_tokens: set[str],
    existing: ClusterMap,
    canonicalizer: Runner,
    themer: Runner,
    batch_size: int,
    concurrency: int,
    reporter: ProgressReporter | None = None,
) -> ClassificationOutcome:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

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
    theme_backlog = demanded_canonicals - existing.theme_of.keys()
    theme_batches = _shard(theme_backlog, batch_size)
    theme_assignments: dict[str, _ThemeIntent] = {}
    existing_theme_ids = set(existing.theme_label) | set(existing.theme_of.values())
    theme_context = _existing_theme_context(existing)

    async def theme(batch: list[str]):
        nonlocal prompt_bytes
        prompt = json.dumps(
            {"new": batch, "existing_themes": theme_context},
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
        return _project_themes(
            response.content,
            batch=set(batch),
            existing_theme_ids=existing_theme_ids,
        )

    if theme_batches:
        if reporter is not None:
            reporter.begin(len(theme_batches), "Grouping skills into themes")
        theme_results = await gather_isolated(
            theme_batches,
            theme,
            on_complete=(
                (lambda completed: reporter.step(completed, label="Grouping skills into themes"))
                if reporter is not None
                else None
            ),
            checkpoint=reporter.checkpoint if reporter is not None else None,
        )
        for batch, result in zip(theme_batches, theme_results, strict=True):
            if not result.ok or result.value is None:
                failures.append(
                    ClassificationFailure(
                        "theme", tuple(batch), str(result.error or "model call failed")
                    )
                )
                continue
            theme_assignments.update(result.value.assignments)
            if result.value.failed_tokens:
                failures.append(
                    ClassificationFailure(
                        "theme",
                        tuple(sorted(result.value.failed_tokens)),
                        "invalid or incomplete model output",
                    )
                )
    elif not alias_batches and reporter is not None:
        reporter.begin(1, "Checking skill clusters")
        reporter.step(1)

    new_labels = [
        intent.new_label
        for intent in theme_assignments.values()
        if intent.new_label is not None
    ]
    allocated = allocate_theme_ids(
        existing_labels=existing.theme_label,
        proposed_labels=new_labels,
    )
    theme_of: dict[str, str] = {}
    theme_label: dict[str, str] = {}
    for token, intent in theme_assignments.items():
        if intent.existing_theme_id is not None:
            theme_of[token] = intent.existing_theme_id
            continue
        assert intent.new_label is not None
        label_key = normalize_skill(intent.new_label)
        theme_id = allocated[label_key]
        theme_of[token] = theme_id
        theme_label.setdefault(theme_id, intent.new_label)

    if reporter is not None:
        reporter.checkpoint()
    metrics = ClassificationMetrics(
        canonical_batches=len(alias_batches),
        theme_batches=len(theme_batches),
        prompt_bytes=prompt_bytes,
        max_in_flight=meter.maximum,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    return ClassificationOutcome(
        additions=ClusterMap(
            aliases=aliases,
            theme_of=theme_of,
            theme_label=theme_label,
        ),
        failures=tuple(failures),
        metrics=metrics,
    )
