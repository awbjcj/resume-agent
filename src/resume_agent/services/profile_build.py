"""Profile build use-case: source corpus (+ GitHub) -> facts.json + matrix.json."""

from __future__ import annotations

from pathlib import Path

from resume_agent.profile.store import save_facts
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import resolve_tenant_path


def run_corpus_build(
    reporter=None,
    *,
    profile_dir: Path,
    github_username: str | None,
    facts_out: str | Path,
    github_allow: tuple[str, ...] = (),
    github_deny: tuple[str, ...] = (),
    github_limit: int = 20,
) -> dict:
    if not 1 <= github_limit <= 100:
        raise ValueError("github repo limit must be between 1 and 100")
    enforce_active_budget()
    profile_dir = resolve_tenant_path(profile_dir)
    facts_out = resolve_tenant_path(facts_out)
    from resume_agent.profile.build import build_corpus_profile
    from resume_agent.profile.inference import build_inference_agent
    from resume_agent.profile.manual_skills import (
        apply_manual_skills,
        load_manual_skills,
        manual_skills_lock,
    )
    from resume_agent.profile.matrix import (
        apply_skill_groups,
        build_matrix,
        load_overrides,
        save_matrix,
    )
    from resume_agent.profile.merge import build_bullet_dedup_agent
    from resume_agent.profile.project_extractor import build_project_extractor_agent
    from resume_agent.profile.synthesis import (
        build_entailment_agent,
        build_synthesis_agent,
    )
    from resume_agent.taxonomy.clusters import load_cluster_map
    from resume_agent.taxonomy import groups as skill_groups

    if reporter is not None:
        reporter.begin(3, "Extracting and merging source documents")
    facts, report = build_corpus_profile(
        profile_dir,
        github_username=github_username,
        dedup_agent=build_bullet_dedup_agent(),
        inference_agent=build_inference_agent(),
        synthesis_agent=build_synthesis_agent(),
        entailment_agent=build_entailment_agent(),
        project_agent=build_project_extractor_agent(),
        github_allow=github_allow,
        github_deny=github_deny,
        github_limit=github_limit,
    )
    with manual_skills_lock(profile_dir):
        manual_ledger = load_manual_skills(Path(profile_dir) / "manual_skills.json")
        facts, replay_warnings = apply_manual_skills(facts, manual_ledger)
        report.warnings.extend(replay_warnings)
        if reporter is not None:
            reporter.step(1, label="Saving facts.json")
        save_facts(facts, str(facts_out))
        if reporter is not None:
            reporter.step(2, label="Building skill matrix")
        overrides = load_overrides(Path(profile_dir) / "overrides.yaml")
        matrix = build_matrix(
            facts,
            load_cluster_map(Path(profile_dir) / "cluster_map.json"),
            overrides,
        )
        taxonomy_path = skill_groups.group_map_path(profile_dir)
        group_map = skill_groups.load_group_map(taxonomy_path)
        missing = {row.key for row in matrix.rows} - set(group_map)
        if missing:
            additions = skill_groups.classify_missing_groups(
                missing,
                skill_groups.build_group_classifier_agent(),
            )
            if additions:
                skill_groups.save_group_map(additions, taxonomy_path)
                group_map = skill_groups.load_group_map(taxonomy_path)
        apply_skill_groups(matrix, group_map, overrides)
        save_matrix(matrix, Path(facts_out).with_name("matrix.json"))
    if reporter is not None:
        reporter.step(3, label="Saved matrix.json")
    return {
        "experiences": len(facts.experience),
        "projects": len(facts.projects),
        "matrixRows": len(matrix.rows),
        "groupedRows": sum(row.group is not None for row in matrix.rows),
        "docStatus": dict(report.doc_status),
        "conflicts": list(report.conflicts),
        "anchorDecisions": list(report.anchor_decisions),
        "verificationDrops": list(report.verification_drops),
        "inferred": list(report.inferred_added),
        "warnings": list(report.warnings),
    }
