"""Saved guidance reaches built agents after their immutable rules."""

import ast
from pathlib import Path
from typing import cast

import yaml

from resume_tailor_harness.llm_runner import AgentRunner, Runner
from resume_tailor_harness.prompts.guidance import GUIDANCE_HEADER


def _instructions(runner: Runner) -> list[str]:
    return list(cast(AgentRunner, runner)._agent.instructions)


def _write_guidance(tmp_path, entries) -> None:
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "agent_guidance.yaml").write_text(
        yaml.safe_dump(entries), encoding="utf-8"
    )


def test_reviewer_and_fit_agents_receive_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_guidance(
        tmp_path,
        {
            "reviewer-recruiter": "Weight the summary heavily.",
            "fit-score": "Penalize on-site-only roles.",
        },
    )

    from resume_tailor_harness.discovery.fit import build_fit_agent
    from resume_tailor_harness.tailor.agents import build_reviewer_agent

    reviewer = _instructions(build_reviewer_agent("recruiter"))
    fit = _instructions(build_fit_agent())
    assert reviewer[-2:] == [GUIDANCE_HEADER, "Weight the summary heavily."]
    assert fit[-2:] == [GUIDANCE_HEADER, "Penalize on-site-only roles."]


def test_fact_check_never_receives_file_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"reviewer-fact-check": "Be lenient."})

    from resume_tailor_harness.tailor.agents import build_reviewer_agent

    assert GUIDANCE_HEADER not in _instructions(build_reviewer_agent("fact-check"))


def test_merged_advisory_embeds_reviewer_and_panel_guidance(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_guidance(
        tmp_path,
        {
            "reviewer-recruiter": "Weight the summary heavily.",
            "reviewer-merged-advisory": "Keep reviews independent.",
        },
    )

    from resume_tailor_harness.tailor.agents import (
        _merged_advisory_instructions,
        build_merged_advisory_agent,
    )

    lines = _merged_advisory_instructions(["recruiter", "concision"])
    recruiter = next(
        line for line in lines if line.startswith("Rubric for 'recruiter'")
    )
    concision = next(
        line for line in lines if line.startswith("Rubric for 'concision'")
    )
    assert "Weight the summary heavily." in recruiter
    assert "Weight the summary heavily." not in concision
    built = _instructions(build_merged_advisory_agent(["recruiter", "concision"]))
    assert built[-2:] == [GUIDANCE_HEADER, "Keep reviews independent."]


def test_interviewer_receives_guidance_after_dynamic_persona(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"interviewer": "Ask about reliability trade-offs."})

    from resume_tailor_harness.interview.agent import InterviewStyle, build_interviewer_agent

    instructions = _instructions(build_interviewer_agent(InterviewStyle()))
    assert instructions[-2:] == [GUIDANCE_HEADER, "Ask about reliability trade-offs."]


def test_every_production_agent_site_uses_the_guidance_boundary() -> None:
    source_root = Path(__file__).parents[1] / "src" / "resume_tailor_harness"
    missing: list[str] = []
    for path in source_root.rglob("*.py"):
        if path.name == "llm_runner.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Agent":
                continue
            instructions = next(
                (
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg == "instructions"
                ),
                None,
            )
            if not (
                isinstance(instructions, ast.Call)
                and isinstance(instructions.func, ast.Name)
                and instructions.func.id == "with_guidance"
            ):
                missing.append(f"{path.relative_to(source_root)}:{node.lineno}")
    assert missing == []
