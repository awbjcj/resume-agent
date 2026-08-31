"""Compact fact-lock snapshots and deterministic Profile Coach impact diffs."""

from __future__ import annotations

import re
from pathlib import Path

from resume_tailor_harness.cover_letter.provenance import collect_fact_ids
from resume_tailor_harness.profile.matrix import load_matrix
from resume_tailor_harness.profile.store import load_facts

_METRIC = re.compile(r"\d")


def profile_snapshot(profile_dir: Path | str) -> dict:
    root = Path(profile_dir)
    fact_ids: list[str] = []
    bullets: dict[str, dict[str, int]] = {}
    facts_path = root / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        fact_ids = sorted(collect_fact_ids(facts))
        bullets = {
            experience.id: {
                "total": len(experience.bullets),
                "withMetrics": sum(
                    1 for bullet in experience.bullets if _METRIC.search(bullet.text)
                ),
            }
            for experience in facts.experience
        }
    matrix = load_matrix(root / "matrix.json")
    skills = (
        {row.key: len(row.evidence_fact_ids) for row in matrix.rows}
        if matrix is not None
        else {}
    )
    return {"factIds": fact_ids, "bullets": bullets, "skills": skills}


def snapshot_diff(before: dict, after: dict) -> dict:
    before_ids = set(before["factIds"])
    new_fact_ids = sorted(
        fact_id for fact_id in after["factIds"] if fact_id not in before_ids
    )
    gained_metrics = sorted(
        (
            {
                "experienceId": experience_id,
                "before": before["bullets"]
                .get(experience_id, {})
                .get("withMetrics", 0),
                "after": counts["withMetrics"],
            }
            for experience_id, counts in after["bullets"].items()
            if counts["withMetrics"]
            > before["bullets"].get(experience_id, {}).get("withMetrics", 0)
        ),
        key=lambda row: row["experienceId"],
    )
    gained_evidence = sorted(
        (
            {"skill": key, "before": before["skills"].get(key, 0), "after": count}
            for key, count in after["skills"].items()
            if key in before["skills"] and count > before["skills"][key]
        ),
        key=lambda row: row["skill"],
    )
    new_skills = sorted(key for key in after["skills"] if key not in before["skills"])
    return {
        "newFactIds": new_fact_ids,
        "bulletsGainedMetrics": gained_metrics,
        "skillsGainedEvidence": gained_evidence,
        "newSkills": new_skills,
    }
