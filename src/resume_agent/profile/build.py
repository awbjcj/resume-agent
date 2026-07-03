from pathlib import Path

from pydantic import Field

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.corpus import load_manifest
from resume_agent.profile.extractor import build_extractor_agent, extract_profile_facts
from resume_agent.profile.fragments import extract_fragments, extract_synthesis_fragments
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_ingest import build_github_profile, repo_to_project
from resume_agent.profile.inference import apply_inferred, infer_skills
from resume_agent.profile.merge import (
    apply_synthesis_fragments,
    dedup_experience_bullets,
    merge_facts,
    merge_fragments,
)
from resume_agent.profile.resume_reader import read_resume_text
from resume_agent.profile.synthesis import profile_skeleton


def build_profile(
    resume_path: str | Path,
    github_username: str | None,
    extractor_agent: Runner | None = None,
    github_client=None,
) -> tuple[ProfileFacts, str]:
    """Build a merged ProfileFacts from a resume file and (optionally) GitHub.

    ``extractor_agent`` and ``github_client`` are injectable for testing; in
    normal use they default to the real Agno agent and GitHub REST client.
    Returns the facts plus raw resume text for deterministic coverage checks.
    """
    text = read_resume_text(resume_path)
    agent = extractor_agent if extractor_agent is not None else build_extractor_agent()
    resume_facts = extract_profile_facts(text, agent)

    if not github_username:
        return merge_facts(resume_facts), text

    gh = github_client if github_client is not None else GitHubClient()
    profile_data = gh.fetch_profile(github_username)
    repos = gh.fetch_repos(github_username)
    gh_profile = build_github_profile(profile_data, repos)
    projects = [repo_to_project(repo) for repo in repos]
    return merge_facts(resume_facts, github_projects=projects, github_profile=gh_profile), text


class BuildReport(ExtensibleModel):
    doc_status: dict[str, str] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    dropped_bullets: list[str] = Field(default_factory=list)
    inferred_added: list[str] = Field(default_factory=list)
    anchor_decisions: list[str] = Field(default_factory=list)
    verification_drops: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_corpus_profile(
    profile_dir: str | Path,
    github_username: str | None,
    extractor_agent: Runner | None = None,
    github_client=None,
    dedup_agent: Runner | None = None,
    inference_agent: Runner | None = None,
    synthesis_agent: Runner | None = None,
    entailment_agent: Runner | None = None,
) -> tuple[ProfileFacts, BuildReport]:
    """Build merged, inference-enriched facts from the registered source corpus."""
    manifest = load_manifest(profile_dir)
    if not manifest.docs:
        raise ValueError(
            "no sources registered — run 'resume-agent profile add <file>' first"
        )
    agent = extractor_agent if extractor_agent is not None else build_extractor_agent()
    extraction = extract_fragments(profile_dir, manifest, agent)
    report = BuildReport(doc_status=extraction.status)

    ordered = sorted(manifest.docs, key=lambda doc: not doc.primary)
    primary = ordered[0]
    if primary.id not in extraction.fragments:
        raise ValueError(
            f"primary source {primary.id} has no usable fragment: "
            f"{extraction.status.get(primary.id, 'unknown failure')}"
        )
    fragments = [
        (doc, extraction.fragments[doc.id])
        for doc in ordered
        if doc.id in extraction.fragments
    ]
    merged, merge_report = merge_fragments(fragments, dedup_agent=dedup_agent)
    report.conflicts = merge_report.conflicts
    report.dropped_bullets = merge_report.dropped_bullets

    synthesis_docs = [doc for doc in manifest.docs if doc.mode == "synthesis"]
    if synthesis_docs:
        if synthesis_agent is None or entailment_agent is None:
            report.warnings.append(
                f"synthesis skipped for {len(synthesis_docs)} document(s): "
                "no synthesis/entailment agent configured"
            )
        else:
            skeleton = profile_skeleton(merged)
            synthesis = extract_synthesis_fragments(
                profile_dir, manifest, skeleton, synthesis_agent, entailment_agent
            )
            report.doc_status.update(synthesis.status)
            report.verification_drops = [
                f"{doc_id}: {drop}"
                for doc_id, drops in sorted(synthesis.drops.items())
                for drop in drops
            ]
            pairs = [
                (doc, synthesis.fragments[doc.id])
                for doc in manifest.docs
                if doc.id in synthesis.fragments
            ]
            report.anchor_decisions, touched = apply_synthesis_fragments(
                merged, pairs, merge_report
            )
            report.conflicts = merge_report.conflicts
            if dedup_agent is not None and touched:
                dedup_experience_bullets(merged, dedup_agent, merge_report, only_ids=touched)
                report.dropped_bullets = merge_report.dropped_bullets

    if github_username:
        github = github_client if github_client is not None else GitHubClient()
        profile_data = github.fetch_profile(github_username)
        repos = github.fetch_repos(github_username)
        merged = merge_facts(
            merged,
            github_projects=[repo_to_project(repo) for repo in repos],
            github_profile=build_github_profile(profile_data, repos),
        )

    if inference_agent is not None:
        try:
            merged, report.inferred_added = apply_inferred(
                merged, infer_skills(merged, inference_agent)
            )
        except Exception as exc:
            report.warnings.append(f"skill inference failed: {exc}")
    return merged, report
