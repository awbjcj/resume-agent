"""Profile build use-case: documents + GitHub -> facts.json, with progress."""

from __future__ import annotations

from pathlib import Path

from resume_agent.profile.build import build_profile
from resume_agent.profile.store import save_facts
from resume_agent.profile.validate import validate_profile


def run_profile_build(
    reporter,
    *,
    resume_path: Path,
    github_username: str | None,
    facts_out: str | Path = "data/profile/facts.json",
) -> dict:
    reporter.begin(2, "Extracting facts from resume")
    facts, raw_text = build_profile(
        resume_path=resume_path, github_username=github_username
    )
    reporter.step(1, label="Validating profile")
    report = validate_profile(facts, raw_text)
    save_facts(facts, str(facts_out))
    reporter.step(2, label="Saved facts.json")
    return {
        "experiences": len(facts.experience),
        "projects": len(facts.projects),
        "warnings": list(report.warnings),
    }
