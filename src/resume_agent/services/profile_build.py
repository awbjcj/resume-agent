"""Profile build use-case: source corpus (+ GitHub) -> facts.json + matrix.json."""

from __future__ import annotations

from pathlib import Path

from resume_agent.profile.store import save_facts


def run_corpus_build(
    reporter,
    *,
    profile_dir: Path,
    github_username: str | None,
    facts_out: str | Path,
) -> dict:
    from resume_agent.profile.build import build_corpus_profile
    from resume_agent.profile.inference import build_inference_agent
    from resume_agent.profile.matrix import build_matrix, load_overrides, save_matrix
    from resume_agent.profile.merge import build_bullet_dedup_agent
    from resume_agent.profile.synthesis import (
        build_entailment_agent,
        build_synthesis_agent,
    )
    from resume_agent.taxonomy.clusters import load_cluster_map

    reporter.begin(3, "Extracting and merging source documents")
    facts, report = build_corpus_profile(
        profile_dir,
        github_username=github_username,
        dedup_agent=build_bullet_dedup_agent(),
        inference_agent=build_inference_agent(),
        synthesis_agent=build_synthesis_agent(),
        entailment_agent=build_entailment_agent(),
    )
    reporter.step(1, label="Saving facts.json")
    save_facts(facts, str(facts_out))
    reporter.step(2, label="Building skill matrix")
    matrix = build_matrix(
        facts,
        load_cluster_map(Path(profile_dir) / "cluster_map.json"),
        load_overrides(Path(profile_dir) / "overrides.yaml"),
    )
    save_matrix(matrix, Path(facts_out).with_name("matrix.json"))
    reporter.step(3, label="Saved matrix.json")
    return {
        "experiences": len(facts.experience),
        "projects": len(facts.projects),
        "docStatus": dict(report.doc_status),
        "conflicts": list(report.conflicts),
        "anchorDecisions": list(report.anchor_decisions),
        "verificationDrops": list(report.verification_drops),
        "inferred": list(report.inferred_added),
        "warnings": list(report.warnings),
    }
