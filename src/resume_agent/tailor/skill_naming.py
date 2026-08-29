"""Deterministic gate: a displayed skill name must resolve to the fact it cites.

The writer merges two real facts into one entry ("AI/LLM Agents & LangChain"
citing only the LLM Agents id) to save space in the skills section. Both halves
exist as separate facts with separate ids, and `skills` is already
`dict[str, list[TailoredSkill]]`, so the category key -- not the entry name --
is where grouping belongs.

Only the *cited fact's* own name and aliases legalize a displayed name. The
cluster map's alias table is deliberately not consulted: it maps a token to a
canonical cluster token, which is exactly the "adjacent skill" relation the
fact-lock forbids a writer from claiming as the job's own term.
"""

import re
from typing import Any

from resume_agent.models.profile import ProfileFacts, Skill
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.provenance import index_facts, renderable_skill_pointer
from resume_agent.tracking.match_gap import normalize_skill

SKILL_NAMING_REVIEWER = "skill-naming"

# Separators a writer uses to merge technologies into one entry. `+` is
# deliberately absent: it would split "C++" into a fragment.
_SEPARATORS = re.compile(r"\s*(?:&|/|,|;|\band\b)\s*", re.IGNORECASE)
_BRACKETS = re.compile(r"[()\[\]]")


def split_name(name: str) -> list[str]:
    """Segments of a displayed skill name, in order, with empties dropped."""
    # A bracket becomes a separator, not whitespace: "Unit Testing (pytest, ...)"
    # must split at the parenthesis, and substituting a space would leave
    # "Unit Testing  pytest" as one segment.
    flattened = _BRACKETS.sub(",", name)
    return [
        segment.strip() for segment in _SEPARATORS.split(flattened) if segment.strip()
    ]


def _legal_tokens(fact: Skill) -> set[str]:
    tokens = {normalize_skill(fact.name)}
    tokens.update(normalize_skill(alias) for alias in fact.aliases)
    tokens.discard("")
    return tokens


def _legalizing_fact_ids(segment: str, index: dict[str, Any]) -> list[str]:
    """Return ids whose own names or aliases match an unresolved segment.

    Only pointers the fact-lock would actually accept are offered: suggesting an
    id `check_provenance` rejects would trade this gate's failure for that one.
    """
    normalized = normalize_skill(segment)
    return sorted(
        fact_id
        for fact_id, candidate in index.items()
        if isinstance(candidate, Skill)
        and renderable_skill_pointer(candidate, index)
        and normalized in _legal_tokens(candidate)
    )


def skill_naming_critique(
    content: ResumeContent, facts: ProfileFacts
) -> ReviewCritique:
    """Blocking when an entry names a technology its cited fact does not cover."""
    index = index_facts(facts)
    issues: list[ReviewIssue] = []
    for category, entries in content.skills.items():
        for entry in entries:
            fact = index.get(entry.provenance)
            # A missing or wrong-kind provenance id belongs to the provenance
            # gate; raising it here too would double-report one defect.
            if not isinstance(fact, Skill):
                continue
            legal = _legal_tokens(fact)
            # Check the whole name first: a fact legitimately named
            # "Research & Development" must not be split into two segments
            # that individually resolve to nothing.
            if normalize_skill(entry.name) in legal:
                continue
            segments = split_name(entry.name)
            unresolved = [
                segment for segment in segments if normalize_skill(segment) not in legal
            ]
            if not unresolved:
                continue
            location = f"skills/{category}/{entry.name}"
            if len(segments) >= 2:
                legalizing: list[str] = []
                for segment in unresolved:
                    fact_ids = _legalizing_fact_ids(segment, index)
                    if fact_ids:
                        legalizing.append(f"{segment!r} -> {', '.join(fact_ids)}")
                suggestion = (
                    "cite one fact per skills entry; list each named technology "
                    "as its own entry under the same skills category key"
                )
                if legalizing:
                    suggestion += (
                        "; legalizing fact ids for extra segments: "
                        + "; ".join(legalizing)
                    )
                issues.append(
                    ReviewIssue(
                        severity=Severity.blocking,
                        location=location,
                        message=(
                            f"skill entry {entry.name!r} names "
                            f"{', '.join(repr(s) for s in unresolved)}, which its cited "
                            f"fact {fact.name!r} ({fact.id}) does not cover"
                        ),
                        suggestion=suggestion,
                    )
                )
            else:
                issues.append(
                    ReviewIssue(
                        severity=Severity.major,
                        location=location,
                        message=(
                            f"skill entry {entry.name!r} does not match its cited fact "
                            f"{fact.name!r} ({fact.id}) or any alias listed on it"
                        ),
                        suggestion=(
                            "use the fact's own name, or an alias listed on that fact"
                        ),
                    )
                )
    blocking = any(issue.severity is Severity.blocking for issue in issues)
    return ReviewCritique(
        reviewer=SKILL_NAMING_REVIEWER,
        score=0 if blocking else 100,
        passed=not blocking,
        issues=issues,
    )
