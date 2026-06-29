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
    slugify_theme as slugify_theme,
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
        demanded = collect_target_skill_tokens(session)
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
                    reporter=reporter,
                ),
                canonicalizer,
                themer,
            )
        )
        final = prune_cluster_map(
            merge_cluster_map(existing, outcome.additions), demanded
        )
        if reporter is not None:
            reporter.checkpoint()
        save_cluster_map(final, path)

    canonical_failures = sum(
        len(failure.tokens)
        for failure in outcome.failures
        if failure.phase == "canonicalize"
    )
    theme_failures = sum(
        len(failure.tokens)
        for failure in outcome.failures
        if failure.phase == "theme"
    )
    return {
        "skills": len(set(final.aliases.values())),
        "themes": len(final.theme_label),
        "failedCanonicalTokens": canonical_failures,
        "failedThemeTokens": theme_failures,
        "canonicalBatches": outcome.metrics.canonical_batches,
        "themeBatches": outcome.metrics.theme_batches,
        "promptBytes": outcome.metrics.prompt_bytes,
        "elapsedMs": outcome.metrics.elapsed_ms,
    }
