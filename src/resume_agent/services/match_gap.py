"""Match-gap Skill classification application module."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner, run_with_cleanup
from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.classification import (
    ClassificationOutcome,
    classify_incrementally,
)
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
from resume_agent.taxonomy.custody import TaxonomyCustody
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
    restore_retired_skills,
    set_grouping_statuses,
    snapshot_before_maintenance,
    undo_last_maintenance,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill
from resume_agent.tracking.match_gap import collect_target_skill_tokens

# Domains that exist only to guarantee every demanded skill has a home.  The
# prefix is a naming convention, not a protected kind: maintenance is expected
# to split these into real domains over time.
FLOOR_DOMAIN_PREFIX = "general-"


def floor_domain(category: str) -> tuple[str, str]:
    """Return the id and label of the general domain backing a category."""

    label = SKILL_GROUPS.get(category, SKILL_GROUPS["other"])
    return f"{FLOOR_DOMAIN_PREFIX}{category}", f"{label} — General"


def _unassigned(cmap: ClusterMap, tokens: set[str]) -> set[str]:
    """Canonical forms of ``tokens`` that still hold no domain in ``cmap``."""

    return {
        canonical
        for token in tokens
        if (canonical := cmap.aliases.get(token, token)) not in cmap.domain_of
    }


def _apply_placement_floor(
    merged: ClusterMap,
    *,
    target_raw: set[str],
    not_skills: set[str],
    call_failed: set[str],
    hints: dict[str, str],
    candidate_context: CandidateContext | None,
    existing: ClusterMap,
    enabled: bool,
) -> tuple[ClusterMap, list[str]]:
    """Give every still-unplaced skill a home in its category's general domain.

    Two passes have now declined to commit, so the choice is between a skill
    nobody can see and a skill filed one level too coarsely.  The second is
    strictly more useful and is visibly provisional, and maintenance can split
    a general domain into real ones later.  The category is the model's own
    stated intent wherever it gave one, so this honours the classification it
    was unwilling to certify rather than inventing a new one.

    A token whose model *call* failed is excluded: there is no judgment to
    honour there, only an outage, and filing a skill because a request timed
    out would turn a transient error into a permanent misplacement.  Those keep
    their failed status and are retried on the next run.
    """

    remaining = sorted(_unassigned(merged, target_raw) - not_skills - call_failed)
    if not enabled or not remaining:
        return merged, []
    retrieved: dict[str, str] = {}
    if candidate_context is not None:
        for token, domains in candidate_context.domain_candidates.items():
            if domains:
                retrieved[token] = existing.category_of.get(domains[0], "other")
    additions = ClusterMap()
    for canonical in remaining:
        category = hints.get(canonical) or retrieved.get(canonical) or "other"
        if category not in SKILL_GROUPS:
            category = "other"
        domain_id, label = floor_domain(category)
        additions.domain_of[canonical] = domain_id
        additions.domain_label.setdefault(domain_id, label)
        additions.category_of.setdefault(domain_id, category)
    return merge_cluster_map(merged, additions), remaining


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
    escalation_themer: Runner | None = None,
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

    correction_file = (
        corrections_path
        if corrections_path is not None
        else Path(path).with_name("taxonomy_corrections.json")
    )
    custody = TaxonomyCustody(path, correction_file)
    with custody.mutation():
        corrections = load_taxonomy_corrections(correction_file)
        taxonomy_state = load_taxonomy_state(path)
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
        # A retired token names no skill.  Dropping it here is what stops the
        # backlog from re-buying the same LLM verdict on every single run.
        demanded -= set(taxonomy_state.retired_skills)
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

        # A token that already failed a pass skips straight to escalation: a
        # replay of the identical batch, prompt, and gates is exactly why
        # clicking Regroup twice used to change nothing.
        attempted = set(taxonomy_state.grouping_status)
        first_pass = {
            token
            for token in target_raw
            if existing.aliases.get(token, token) not in attempted
        }

        candidate_context: CandidateContext | None = None
        if first_pass:
            candidate_context = asyncio.run(
                build_candidate_context(
                    cluster_path=path,
                    tokens=first_pass,
                    existing=existing,
                    provider=embedding_provider,
                )
            )
        # Retrieval may only veto reuse it did not surface when it is actually
        # semantic.  Under a lexical or partial fallback it narrows the prompt
        # but no longer forbids an otherwise valid domain.
        enforce_candidates = (
            candidate_context is not None and candidate_context.mode == "embedding"
        )
        escalation_cap = settings.taxonomy_escalation_max_skills

        async def classify_both() -> tuple[
            ClassificationOutcome,
            ClassificationOutcome | None,
            ClusterMap,
            set[str],
        ]:
            first = await classify_incrementally(
                demanded_tokens=first_pass,
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
                enforce_candidates=enforce_candidates,
            )
            after_first = merge_cluster_map(existing, first.additions)
            pending = sorted(
                _unassigned(after_first, target_raw) - set(first.not_skills)
            )
            # Escalation is the expensive path, so it is bounded per run.  What
            # the bound defers is not "unplaceable" -- it simply has not been
            # tried yet, so it must not be swept up by the placement floor.  It
            # keeps its status and escalates first on the next run.
            leftovers, deferred = pending[:escalation_cap], set(pending[escalation_cap:])
            if not leftovers:
                return first, None, after_first, deferred
            # These are canonical already; pinning identity aliases keeps the
            # escalation pass out of synonym reconciliation entirely.
            for canonical in leftovers:
                after_first.aliases.setdefault(canonical, canonical)
            second = await classify_incrementally(
                demanded_tokens=set(leftovers),
                existing=after_first,
                canonicalizer=canonicalizer,
                themer=escalation_themer or themer,
                # Smaller batches and the whole taxonomy: the residue is the
                # ambiguous tail, so it gets more attention per token, not less.
                batch_size=max(1, size // 4),
                concurrency=width,
                category_cap=settings.domains_per_category_target,
                reconcile_batch_size=reconcile_size,
                reporter=reporter,
                candidate_context=None,
                allow_category_growth=True,
                min_new_domain_members=1,
                category_hints=category_hints,
            )
            return (
                first,
                second,
                merge_cluster_map(after_first, second.additions),
                deferred,
            )

        outcome, escalated, merged, deferred = asyncio.run(
            run_with_cleanup(
                classify_both(),
                canonicalizer,
                themer,
                *((escalation_themer,) if escalation_themer is not None else ()),
            )
        )
        not_skills = set(outcome.not_skills) | set(
            escalated.not_skills if escalated else ()
        )
        escalated_count = (
            len(escalated.additions.domain_of) if escalated is not None else 0
        )
        # Both passes report; the escalation pass is where the hard cases end
        # up, so hiding its failures would hide exactly the interesting ones.
        all_failures = tuple(outcome.failures) + tuple(
            escalated.failures if escalated else ()
        )
        call_failed = {
            normalized
            for failure in all_failures
            if failure.kind == "call"
            for token in failure.tokens
            if (normalized := normalize_skill(token))
        }
        merged, floor_placed = _apply_placement_floor(
            merged,
            target_raw=target_raw,
            not_skills=not_skills,
            call_failed=call_failed | deferred,
            hints={
                **outcome.fallback_categories,
                **(escalated.fallback_categories if escalated else {}),
            },
            candidate_context=candidate_context,
            existing=existing,
            enabled=settings.taxonomy_placement_floor,
        )
        # This is a growing canonical taxonomy rather than a view cache.  Even
        # an unscoped refresh may only add or clarify its current unassigned
        # backlog; it must never prune established domains or aliases that are
        # merely outside today's visible jobs.
        final = apply_taxonomy_corrections(merged, corrections)
        if reporter is not None:
            reporter.checkpoint()
        save_cluster_map(final, path)
        # Distinct tokens, not token-attempts: a token the first pass and the
        # escalation pass both failed is one unresolved skill, not two.
        canonical_failures = len(
            {
                token
                for failure in all_failures
                if failure.phase == "canonicalize"
                for token in failure.tokens
            }
        )
        domain_failures = len(
            {
                token
                for failure in all_failures
                if failure.phase == "domain"
                for token in failure.tokens
            }
        )
        failure_reasons: dict[str, int] = {}
        for failure in all_failures:
            failure_reasons[failure.message] = failure_reasons.get(
                failure.message, 0
            ) + len(failure.tokens)
        requested_canonicals = {final.aliases.get(token, token) for token in target_raw}
        retired_canonicals = {
            final.aliases.get(token, token) for token in not_skills
        } & requested_canonicals
        assigned = {token for token in requested_canonicals if token in final.domain_of}
        statuses: dict[str, GroupingStatus] = {}
        for failure in all_failures:
            failure_state = "failed" if failure.kind == "call" else "uncertain"
            for token in failure.tokens:
                canonical = final.aliases.get(
                    normalize_skill(token), normalize_skill(token)
                )
                if canonical not in final.domain_of:
                    statuses[canonical] = GroupingStatus(
                        state=failure_state, reason=failure.message
                    )
        for token in requested_canonicals - assigned - retired_canonicals:
            statuses.setdefault(
                token,
                GroupingStatus(
                    state="uncertain",
                    reason="no high-confidence existing or coherent new domain",
                ),
            )
        set_grouping_statuses(
            path,
            assigned=assigned,
            statuses=statuses,
            retired={token: "not a skill" for token in retired_canonicals},
        )
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
        "canonicalBatches": outcome.metrics.canonical_batches
        + (escalated.metrics.canonical_batches if escalated else 0),
        "domainBatches": outcome.metrics.domain_batches
        + (escalated.metrics.domain_batches if escalated else 0),
        "promptBytes": outcome.metrics.prompt_bytes
        + (escalated.metrics.prompt_bytes if escalated else 0),
        "elapsedMs": outcome.metrics.elapsed_ms
        + (escalated.metrics.elapsed_ms if escalated else 0),
        "embeddingMode": outcome.metrics.embedding_mode,
        # Retrieval degrading to a lexical fallback used to be invisible, which
        # is how it ran that way for the entire life of the feature.
        "embeddingDegraded": candidate_context is not None
        and candidate_context.degraded,
        "embeddingReason": candidate_context.reason if candidate_context else "",
        "escalatedSkills": escalated_count,
        "placedByFallback": len(floor_placed),
        "retiredSkills": sorted(retired_canonicals),
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


def restore_skills(
    *, path: str | Path, skill_keys: set[str] | frozenset[str]
) -> dict[str, object]:
    """Un-retire tokens so the next regroup reconsiders them as real skills."""

    correction_file = Path(path).with_name("taxonomy_corrections.json")
    with TaxonomyCustody(path, correction_file).mutation():
        _state, restored = restore_retired_skills(path, set(skill_keys))
    return {"restoredSkills": restored, "restored": len(restored)}


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
    correction_file = (
        corrections_path
        if corrections_path is not None
        else Path(path).with_name("taxonomy_corrections.json")
    )
    with TaxonomyCustody(path, correction_file).mutation():
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

    correction_file = (
        corrections_path
        if corrections_path is not None
        else Path(path).with_name("taxonomy_corrections.json")
    )
    with TaxonomyCustody(path, correction_file).mutation():
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
