"""Generate and cache evidence-grounded gap-closing suggestions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, select

from resume_agent.github.repos import RepoMeta, parse_github_url
from resume_agent.models.profile import ProfileFacts
from resume_agent.suggestions.agents import SuggestionDraft
from resume_agent.tracking.match_gap import DemandGraph, profile_skill_tokens
from resume_agent.tracking.tables import SkillSuggestion, utcnow

SuggestionKind = Literal["skill", "theme"]
RepoVerifier = Callable[[str, str], RepoMeta | None]


class SuggestionTargetNotFound(ValueError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"unknown {kind} suggestion target: {key}")


@dataclass(frozen=True)
class SuggestionContext:
    kind: SuggestionKind
    key: str
    label: str
    members: tuple[str, ...]
    demanding_job_ids: tuple[int, ...]
    jobs_context: str


def resolve_suggestion_context(
    graph: DemandGraph,
    *,
    kind: SuggestionKind,
    key: str,
) -> SuggestionContext:
    if kind == "skill":
        skill = next((candidate for candidate in graph.skills if candidate.skill == key), None)
        if skill is None:
            raise SuggestionTargetNotFound(kind, key)
        label = skill.skill
        members = (skill.skill,)
    else:
        theme = next((candidate for candidate in graph.themes if candidate.id == key), None)
        if theme is None:
            raise SuggestionTargetNotFound(kind, key)
        label = theme.label
        members = tuple(
            sorted(skill.skill for skill in graph.skills if skill.theme_id == theme.id)
        )

    member_set = set(members)
    job_ids = tuple(
        sorted({edge.job_id for edge in graph.edges if edge.skill in member_set})
    )
    jobs_by_id = {job.id: job for job in graph.jobs}
    jobs_context = "; ".join(
        f"{jobs_by_id[job_id].company or 'Unknown company'} — "
        f"{jobs_by_id[job_id].title or 'Untitled role'}"
        for job_id in job_ids
        if job_id in jobs_by_id
    )
    return SuggestionContext(kind, key, label, members, job_ids, jobs_context)


def suggestion_fingerprint(
    context: SuggestionContext,
    coverage: set[str],
    schema_version: int = 1,
) -> str:
    payload = json.dumps(
        {
            "schema_version": schema_version,
            "kind": context.kind,
            "key": context.key,
            "coverage": sorted(coverage),
            "members": sorted(context.members),
            "demanding_job_ids": sorted(context.demanding_job_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_URL = re.compile(r"https?://[^\s<>\]\[()]+")


def _normalized_http_url(value: str) -> str | None:
    parsed = urlsplit(value.rstrip(".,;:"))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _verified_repos(
    draft: SuggestionDraft,
    verify: RepoVerifier,
    evidence_urls: set[str],
) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reference in draft.repos:
        normalized = _normalized_http_url(reference.url)
        if normalized is None or normalized not in evidence_urls:
            continue
        parsed = parse_github_url(reference.url)
        if parsed is None:
            continue
        metadata = verify(*parsed)
        if metadata is None or metadata.full_name in seen:
            continue
        seen.add(metadata.full_name)
        repositories.append(
            {
                "name": metadata.full_name,
                "url": metadata.url,
                "why": reference.why,
                "stars": metadata.stars,
                "description": metadata.description,
            }
        )
    return repositories


def _payload_from_evidence(
    draft: SuggestionDraft,
    research: str,
    verify: RepoVerifier,
) -> dict[str, Any]:
    evidence_urls = {
        normalized
        for raw_url in _URL.findall(research)
        if (normalized := _normalized_http_url(raw_url)) is not None
    }
    project = None
    if draft.project is not None:
        project = {
            "title": draft.project.title,
            "summary": draft.project.summary,
            "skills_demonstrated": draft.project.skills_demonstrated,
        }

    payload = {
        "repos": _verified_repos(draft, verify, evidence_urls),
        "resources": [
            {"title": resource.title, "url": normalized, "kind": resource.kind}
            for resource in draft.resources
            if (normalized := _normalized_http_url(resource.url)) in evidence_urls
        ],
        "project": project,
        "bridge": draft.bridge.strip(),
        "citations": sorted(evidence_urls),
    }
    if not (
        payload["repos"]
        or payload["resources"]
        or payload["project"]
        or payload["bridge"]
    ):
        raise ValueError("advisor formatter returned an empty suggestion")
    return payload


def _search_prompt(context: SuggestionContext) -> str:
    if context.kind == "theme":
        return (
            f"Theme gap: {context.label}. Member skills: {', '.join(context.members)}.\n"
            f"Jobs demanding these skills: {context.jobs_context}\n"
            "Research a learning path that closes this capability gap."
        )
    return (
        f"Skill gap: {context.label}.\n"
        f"Jobs demanding it: {context.jobs_context}\n"
        "Research real repositories, official learning resources, and a portfolio project."
    )


def _format_prompt(research: str, coverage: set[str]) -> str:
    bridge_context = ", ".join(sorted(coverage)) or "(no profile skills on file)"
    return (
        f"Research:\n{research}\n\n"
        f"Profile skills available for bridge framing:\n{bridge_context}"
    )


def generate_suggestion(
    session: Session,
    *,
    context: SuggestionContext,
    search_agent,
    formatter,
    verify: RepoVerifier,
    facts: ProfileFacts,
    reporter=None,
) -> SkillSuggestion:
    coverage = profile_skill_tokens(facts)
    research = str(search_agent.run(_search_prompt(context)).content)
    if reporter is not None:
        reporter.checkpoint()
    formatted = formatter.run(_format_prompt(research, coverage)).content
    if not isinstance(formatted, SuggestionDraft):
        raise ValueError("advisor formatter did not return SuggestionDraft")
    if reporter is not None:
        reporter.checkpoint()

    payload = _payload_from_evidence(formatted, research, verify)
    fingerprint = suggestion_fingerprint(context, coverage)
    row = session.exec(
        select(SkillSuggestion).where(
            SkillSuggestion.kind == context.kind,
            SkillSuggestion.key == context.key,
        )
    ).first()
    if row is None:
        row = SkillSuggestion(kind=context.kind, key=context.key)
        session.add(row)
    row.payload_json = payload
    row.fingerprint = fingerprint
    row.generated_at = utcnow()
    session.commit()
    session.refresh(row)
    return row
