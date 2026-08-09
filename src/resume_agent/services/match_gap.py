"""Match-gap Skill classification application module."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner, run_with_cleanup
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.classification import classify_incrementally
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    merge_cluster_map,
    save_cluster_map,
    slugify_domain as slugify_domain,
)
from resume_agent.taxonomy.corrections import (
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
)
from resume_agent.taxonomy.embeddings import (
    CandidateContext,
    EmbeddingProvider,
    build_candidate_context,
)
from resume_agent.taxonomy.maintenance import maintain_taxonomy as evaluate_maintenance
from resume_agent.taxonomy.state import (
    ALGORITHM_VERSION,
    GroupingStatus,
    load_taxonomy_state,
    set_grouping_statuses,
    snapshot_before_maintenance,
    undo_last_maintenance,
)
from resume_agent.tracking.match_gap import normalize_skill
from resume_agent.tracking.match_gap import collect_target_skill_tokens

_REFRESH_LOCK = threading.Lock()


def _domain_members(cmap: ClusterMap, domain_id: str) -> frozenset[str]:
    return frozenset(
        token
        for token, assigned_domain_id in cmap.domain_of.items()
        if assigned_domain_id == domain_id
    )


def _invalidate_changed_domain_suggestions(
    session: Session | None, before: ClusterMap, after: ClusterMap
) -> int:
    """Mark cached domain advice stale when a taxonomy operation changes it.

    Skill suggestions remain valid as long as their individual canonical and
    demand context are unchanged.  Domain suggestions summarize membership, so
    they must be refreshed after a regroup, maintenance generation, or undo.
    """

    if session is None:
        return 0
    changed_ids = {
        domain_id
        for domain_id in set(before.domain_label)
        | set(before.domain_of.values())
        | set(after.domain_label)
        | set(after.domain_of.values())
        if _domain_members(before, domain_id) != _domain_members(after, domain_id)
    }
    if not changed_ids:
        return 0
    from sqlmodel import select

    from resume_agent.tracking.tables import SkillSuggestion

    rows = session.exec(
        select(SkillSuggestion).where(SkillSuggestion.kind == "domain")
    ).all()
    changed = 0
    for row in rows:
        if row.key in changed_ids and row.fingerprint != "stale:taxonomy-change":
            row.fingerprint = "stale:taxonomy-change"
            changed += 1
    if changed:
        session.commit()
    return changed


def refresh_clusters(
    session: Session | None,
    *,
    canonicalizer: Runner,
    themer: Runner,
    path: str | Path,
    reporter: ProgressReporter | None = None,
    batch_size: int | None = None,
    concurrency: int | None = None,
    reconcile_batch_size: int | None = None,
    extra_tokens: frozenset[str] | set[str] = frozenset(),
    corrections_path: str | Path | None = None,
    skill_keys: set[str] | frozenset[str] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    demanded_tokens: set[str] | frozenset[str] | None = None,
    category_hints: dict[str, str] | None = None,
) -> dict[str, object]:
    """Classify a complete or explicitly scoped Unassigned backlog and save once."""
    settings = get_settings()
    size = settings.cluster_batch_size if batch_size is None else batch_size
    width = settings.llm_concurrency if concurrency is None else concurrency
    reconcile_size = (
        settings.cluster_reconcile_batch_size
        if reconcile_batch_size is None
        else reconcile_batch_size
    )
    if size < 1:
        raise ValueError("batch_size must be at least 1")
    if width < 1:
        raise ValueError("concurrency must be at least 1")
    if reconcile_size < 1:
        raise ValueError("reconcile_batch_size must be at least 1")

    with _REFRESH_LOCK:
        correction_file = (
            corrections_path
            if corrections_path is not None
            else Path(path).with_name("taxonomy_corrections.json")
        )
        corrections = load_taxonomy_corrections(correction_file)
        demanded = (
            (
                set(demanded_tokens)
                if demanded_tokens is not None
                else (
                    collect_target_skill_tokens(session)
                    if session is not None
                    else set()
                )
            )
            | set(extra_tokens)
            | set(corrections.added_skills)
        )
        demanded -= set(corrections.removed_skills)
        existing = apply_taxonomy_corrections(load_cluster_map(path), corrections)
        normalized_requested = {
            token for raw in (skill_keys or set()) if (token := normalize_skill(raw))
        }
        skipped_unknown: set[str] = set()
        skipped_assigned: set[str] = set()
        target_raw: set[str] = set()
        if skill_keys is None:
            target_raw = {
                token
                for token in demanded
                if existing.domain_of.get(existing.aliases.get(token, token)) is None
            }
        else:
            for token in normalized_requested:
                canonical = existing.aliases.get(token, token)
                if token not in demanded and canonical not in {
                    existing.aliases.get(item, item) for item in demanded
                }:
                    skipped_unknown.add(token)
                elif existing.domain_of.get(canonical) is not None:
                    skipped_assigned.add(token)
                else:
                    target_raw.add(token)

        candidate_context: CandidateContext | None = None
        if target_raw:
            candidate_context = asyncio.run(
                build_candidate_context(
                    cluster_path=path,
                    tokens=target_raw,
                    existing=existing,
                    provider=embedding_provider,
                )
            )
        outcome = asyncio.run(
            run_with_cleanup(
                classify_incrementally(
                    demanded_tokens=target_raw,
                    existing=existing,
                    canonicalizer=canonicalizer,
                    themer=themer,
                    batch_size=size,
                    concurrency=width,
                    category_cap=settings.domains_per_category_target,
                    reconcile_batch_size=reconcile_size,
                    reporter=reporter,
                    candidate_context=candidate_context,
                    allow_category_growth=True,
                    min_new_domain_members=2,
                    category_hints=category_hints,
                ),
                canonicalizer,
                themer,
            )
        )
        merged = merge_cluster_map(existing, outcome.additions)
        # This is a growing canonical taxonomy rather than a view cache.  Even
        # an unscoped refresh may only add or clarify its current unassigned
        # backlog; it must never prune established domains or aliases that are
        # merely outside today's visible jobs.
        final = apply_taxonomy_corrections(merged, corrections)
        if reporter is not None:
            reporter.checkpoint()
        save_cluster_map(final, path)
        canonical_failures = sum(
            len(failure.tokens)
            for failure in outcome.failures
            if failure.phase == "canonicalize"
        )
        domain_failures = sum(
            len(failure.tokens)
            for failure in outcome.failures
            if failure.phase == "domain"
        )
        failure_reasons: dict[str, int] = {}
        for failure in outcome.failures:
            failure_reasons[failure.message] = failure_reasons.get(
                failure.message, 0
            ) + len(failure.tokens)
        requested_canonicals = {final.aliases.get(token, token) for token in target_raw}
        assigned = {token for token in requested_canonicals if token in final.domain_of}
        statuses: dict[str, GroupingStatus] = {}
        for failure in outcome.failures:
            state = "failed" if "model call failed" in failure.message else "uncertain"
            for token in failure.tokens:
                canonical = final.aliases.get(
                    normalize_skill(token), normalize_skill(token)
                )
                if canonical not in final.domain_of:
                    statuses[canonical] = GroupingStatus(
                        state=state, reason=failure.message
                    )
        for token in requested_canonicals - assigned:
            statuses.setdefault(
                token,
                GroupingStatus(
                    state="uncertain",
                    reason="no high-confidence existing or coherent new domain",
                ),
            )
        set_grouping_statuses(path, assigned=assigned, statuses=statuses)
        stale_suggestions = _invalidate_changed_domain_suggestions(
            session, existing, final
        )
        domains_created = len(set(final.domain_label) - set(existing.domain_label))
        aliases_merged = sum(
            final.aliases.get(token, token) != token for token in target_raw
        )
    return {
        "skills": len(set(final.aliases.values())),
        "domains": len(final.domain_label),
        "failedCanonicalTokens": canonical_failures,
        "failedDomainTokens": domain_failures,
        "canonicalBatches": outcome.metrics.canonical_batches,
        "domainBatches": outcome.metrics.domain_batches,
        "promptBytes": outcome.metrics.prompt_bytes,
        "elapsedMs": outcome.metrics.elapsed_ms,
        "embeddingMode": outcome.metrics.embedding_mode,
        "algorithmVersion": ALGORITHM_VERSION,
        "requestedSkills": sorted(requested_canonicals),
        "processedSkillKeys": sorted(target_raw),
        "assignedSkills": len(assigned),
        "uncertainSkills": len(
            [status for status in statuses.values() if status.state == "uncertain"]
        ),
        "failedSkills": len(
            [status for status in statuses.values() if status.state == "failed"]
        ),
        "failureReasons": failure_reasons,
        "domainsCreated": domains_created,
        "aliasesMerged": aliases_merged,
        "remainingUnassigned": len(requested_canonicals - assigned),
        "skippedAlreadyAssigned": sorted(skipped_assigned),
        "skippedUnknown": sorted(skipped_unknown),
        "skippedStaleSkills": len(skipped_assigned) + len(skipped_unknown),
        "staleSuggestions": stale_suggestions,
    }


def maintain_taxonomy(
    session: Session | None,
    *,
    judge: Runner,
    path: str | Path,
    corrections_path: str | Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    """Run one correction-safe, versioned taxonomy maintenance generation."""

    settings = get_settings()
    with _REFRESH_LOCK:
        correction_file = (
            corrections_path
            if corrections_path is not None
            else Path(path).with_name("taxonomy_corrections.json")
        )
        corrections = load_taxonomy_corrections(correction_file)
        existing = apply_taxonomy_corrections(load_cluster_map(path), corrections)
        outcome = asyncio.run(
            run_with_cleanup(
                evaluate_maintenance(
                    cluster_path=str(path),
                    cmap=existing,
                    corrections=corrections,
                    judge=judge,
                    max_churn=settings.taxonomy_maintenance_max_churn,
                    embedding_provider=embedding_provider,
                ),
                judge,
            )
        )
        final = apply_taxonomy_corrections(outcome.cluster_map, corrections)
        changed = outcome.changed and final != existing
        if changed:
            state, _generation = snapshot_before_maintenance(path, existing)
            save_cluster_map(final, path)
        else:
            state = load_taxonomy_state(path)
        stale_suggestions = _invalidate_changed_domain_suggestions(
            session, existing, final
        )
    return {
        "changed": changed,
        "generationId": state.generation_id,
        "algorithmVersion": ALGORITHM_VERSION,
        "maintenanceDue": state.maintenance_due,
        "actions": [action.model_dump(mode="json") for action in outcome.actions],
        "rejectedActions": list(outcome.rejected_actions),
        "embeddingMode": outcome.embedding_mode,
        "churnedSkills": outcome.churned_skills,
        "undoAvailable": state.can_undo,
        "staleSuggestions": stale_suggestions,
    }


def undo_taxonomy_maintenance(
    session: Session | None,
    *,
    path: str | Path,
    corrections_path: str | Path | None = None,
) -> dict[str, object]:
    """Restore the immediately preceding generated taxonomy version."""

    with _REFRESH_LOCK:
        correction_file = (
            corrections_path
            if corrections_path is not None
            else Path(path).with_name("taxonomy_corrections.json")
        )
        corrections = load_taxonomy_corrections(correction_file)
        existing = apply_taxonomy_corrections(load_cluster_map(path), corrections)
        restored, state = undo_last_maintenance(path)
        final = apply_taxonomy_corrections(restored, corrections)
        save_cluster_map(final, path)
        stale_suggestions = _invalidate_changed_domain_suggestions(
            session, existing, final
        )
    return {
        "restored": True,
        "generationId": state.generation_id,
        "algorithmVersion": ALGORITHM_VERSION,
        "maintenanceDue": state.maintenance_due,
        "undoAvailable": state.can_undo,
        "staleSuggestions": stale_suggestions,
    }
