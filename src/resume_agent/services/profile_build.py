"""Profile build use-case: source corpus (+ GitHub) -> facts.json + matrix.json."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.store import save_facts
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import resolve_tenant_path

if TYPE_CHECKING:
    from resume_agent.profile.matrix import SkillMatrix


def _restore_publication_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".rollback",
        ) as handle:
            temporary = Path(handle.name)
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _publish_profile_artifacts(
    facts: ProfileFacts,
    matrix: SkillMatrix,
    *,
    facts_path: Path,
    matrix_path: Path,
    matrix_writer: Callable[[SkillMatrix, str | Path], None],
) -> None:
    """Publish facts and their derived matrix as one rollback-safe operation."""

    paths = (facts_path, matrix_path)
    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        save_facts(facts, facts_path)
        matrix_writer(matrix, matrix_path)
    except BaseException:
        for path in paths:
            _restore_publication_file(path, previous[path])
        raise


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
    from resume_agent.profile.aspect_classifier import build_aspect_classifier_agent
    from resume_agent.profile.inference import build_inference_agent
    from resume_agent.profile.manual_skills import (
        apply_manual_skills,
        load_manual_skills,
        manual_skills_lock,
    )
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.profile.matrix import (
        build_matrix,
        decorate_matrix_groups,
        save_matrix,
    )
    from resume_agent.profile.merge import build_bullet_dedup_agent
    from resume_agent.profile.project_extractor import build_project_extractor_agent
    from resume_agent.profile.synthesis import (
        build_entailment_agent,
        build_synthesis_agent,
    )
    from resume_agent.taxonomy import groups as skill_groups
    from resume_agent.taxonomy.corrections import corrections_file_path
    from resume_agent.taxonomy.custody import TaxonomyCustody
    from resume_agent.taxonomy.state import mark_legacy_group_map_imported
    from resume_agent.services.match_gap import refresh_clusters

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
        aspect_agent=build_aspect_classifier_agent(),
        github_allow=github_allow,
        github_deny=github_deny,
        github_limit=github_limit,
    )
    with manual_skills_lock(profile_dir):
        manual_ledger = load_manual_skills(Path(profile_dir) / "manual_skills.json")
        facts, replay_warnings = apply_manual_skills(facts, manual_ledger)
        report.warnings.extend(replay_warnings)
        if reporter is not None:
            reporter.step(1, label="Prepared profile facts")
        if reporter is not None:
            reporter.step(2, label="Classifying the shared skill taxonomy")
        cluster_path = Path(profile_dir) / "cluster_map.json"
        correction_path = resolve_tenant_path(corrections_file_path())
        # Everything before classification uses one coherent taxonomy read.
        pre = build_effective_taxonomy(profile_dir)
        preliminary = build_matrix(facts, pre)
        taxonomy_path = skill_groups.group_map_path(profile_dir)
        # ``skill_groups.json`` is a one-time migration hint only.  Once its
        # original content hash has been recorded, the growing cluster map is
        # the sole taxonomy source and later edits to the legacy artifact must
        # not steer a rebuild.
        legacy_hints = (
            skill_groups.load_group_map(taxonomy_path)
            if pre.state.legacy_group_map_sha256 is None
            else {}
        )
        missing = {
            row.key
            for row in preliminary.rows
            if pre.cluster_map.domain_of.get(
                pre.cluster_map.aliases.get(row.key, row.key)
            )
            is None
        }
        if missing:
            refresh_clusters(
                None,
                path=cluster_path,
                demanded_tokens=missing,
                category_hints=legacy_hints,
                corrections_path=correction_path,
            )
        with TaxonomyCustody(cluster_path, correction_path).mutation():
            mark_legacy_group_map_imported(cluster_path, taxonomy_path)
        # Classification and the legacy-import marker may both have mutated
        # persisted taxonomy artifacts, so the final matrix must rebind.
        post = build_effective_taxonomy(profile_dir)
        matrix = build_matrix(facts, post)
        decorate_matrix_groups(matrix, profile_dir, post)
        _publish_profile_artifacts(
            facts,
            matrix,
            facts_path=Path(facts_out),
            matrix_path=Path(facts_out).with_name("matrix.json"),
            matrix_writer=save_matrix,
        )
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
