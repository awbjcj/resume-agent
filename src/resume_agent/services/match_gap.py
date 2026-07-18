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
    load_cluster_map,
    merge_cluster_map,
    prune_cluster_map,
    save_cluster_map,
    slugify_domain as slugify_domain,
)
from resume_agent.taxonomy.corrections import (
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
)
from resume_agent.tracking.match_gap import collect_target_skill_tokens

_REFRESH_LOCK = threading.Lock()


def refresh_clusters(
    session: Session,
    *,
    canonicalizer: Runner,
    themer: Runner,
    path: str | Path,
    reporter: ProgressReporter | None = None,
    batch_size: int | None = None,
    concurrency: int | None = None,
    extra_tokens: frozenset[str] | set[str] = frozenset(),
    corrections_path: str | Path | None = None,
) -> dict[str, object]:
    """Classify the current backlog, apply successes, prune, and save once."""
    settings = get_settings()
    size = settings.cluster_batch_size if batch_size is None else batch_size
    width = settings.llm_concurrency if concurrency is None else concurrency
    if size < 1:
        raise ValueError("batch_size must be at least 1")
    if width < 1:
        raise ValueError("concurrency must be at least 1")

    with _REFRESH_LOCK:
        demanded = collect_target_skill_tokens(session) | set(extra_tokens)
        existing = load_cluster_map(path)
        outcome = asyncio.run(
            run_with_cleanup(
                classify_incrementally(
                    demanded_tokens=demanded,
                    existing=existing,
                    canonicalizer=canonicalizer,
                    themer=themer,
                    batch_size=size,
                    concurrency=width,
                    category_cap=settings.domains_per_category_cap,
                    reporter=reporter,
                ),
                canonicalizer,
                themer,
            )
        )
        final = apply_taxonomy_corrections(
            prune_cluster_map(
                merge_cluster_map(existing, outcome.additions), demanded
            ),
            load_taxonomy_corrections(
                corrections_path
                if corrections_path is not None
                else Path(path).with_name("taxonomy_corrections.json")
            ),
        )
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
    return {
        "skills": len(set(final.aliases.values())),
        "domains": len(final.domain_label),
        "failedCanonicalTokens": canonical_failures,
        "failedDomainTokens": domain_failures,
        "canonicalBatches": outcome.metrics.canonical_batches,
        "domainBatches": outcome.metrics.domain_batches,
        "promptBytes": outcome.metrics.prompt_bytes,
        "elapsedMs": outcome.metrics.elapsed_ms,
    }
