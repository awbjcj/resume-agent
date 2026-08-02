"""Cover-letter use-case: resolve targets, build agents, draft + render each."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from resume_agent.cover_letter.render import render_cover_letter
from resume_agent.cover_letter.service import generate_cover_letter
from resume_agent.career_skills.models import CoverLetterSkillName
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
from resume_agent.render.export import export_job_artifacts
from resume_agent.services.agents import build_cover_letter_bundle
from resume_agent.services.tailoring import resolve_targets
from resume_agent.tenancy.limits import enforce_active_budget
from resume_agent.tenancy.paths import FACTS_PATH as DEFAULT_FACTS


@dataclass
class CoverLetterResult:
    job_id: int
    cover_letter_id: int
    fact_check_passed: bool
    pdf_path: str


def write_cover_letters(
    session: Session,
    *,
    job_ids: list[int] | None = None,
    approved: bool = False,
    facts_path: str = DEFAULT_FACTS,
    reporter: ProgressReporter | None = None,
    skill: CoverLetterSkillName | str | None = None,
) -> list[CoverLetterResult]:
    targets = resolve_targets(session, job_ids=job_ids, approved=approved)
    if not targets:
        return []
    enforce_active_budget()
    facts = load_facts(facts_path)
    bundle = build_cover_letter_bundle(skill=skill) if skill is not None else build_cover_letter_bundle()
    results: list[CoverLetterResult] = []
    if reporter:
        reporter.begin(len(targets), "Starting")
    for index, job in enumerate(targets, 1):
        if reporter:
            reporter.step(index - 1, label=f"Cover letter for job #{job.id}")
        cover = generate_cover_letter(session, job, facts, bundle.draft, bundle.reviser)
        if cover.id is None:
            raise RuntimeError("Cover letter was not persisted")
        assert job.id is not None
        path = render_cover_letter(session, cover.id)
        export_job_artifacts(session, job.id)
        results.append(
            CoverLetterResult(
                job_id=job.id,
                cover_letter_id=cover.id,
                fact_check_passed=cover.fact_check_passed,
                pdf_path=str(path),
            )
        )
        if reporter:
            reporter.step(index)
    if reporter:
        reporter.done()
    return results
