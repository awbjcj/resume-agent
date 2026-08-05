"""Deterministic gate: a number in generated prose must come from a cited fact.

The largest class of fact-check failures is an invented quantity -- "saving
hours of manual reporting effort", "3+ years", "reduced planning effort by 40%".
A number is mechanically checkable, so a premium reviewer should not be spending
a round to notice it.

Tokenization is conservative in the permissive direction. A token counts as a
claim only when it stands alone, so `p95`, `L1-L3`, `GPT-4`, `S3`, and `C++` are
never treated as quantities; and a fact's evidence set is every digit run
anywhere in its own fields, so a number the fact states in passing still
legalizes the claim. False blocks cost a round, which is worse than a miss the
LLM fact-checker can still catch.
"""

import re
from typing import Any

from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.provenance import index_facts

NUMERIC_EVIDENCE_REVIEWER = "numeric-evidence"

# A whole whitespace token that is a bare quantity, optionally carrying one
# common unit. Anything welded to letters fails this and is ignored.
_QUANTITY = re.compile(r"^\d[\d,]*(?:\.\d+)?(?:%|\+|x|k|m|b|ms|s)?$", re.IGNORECASE)
# The digit core of a token, and every digit run inside a fact's text.
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_EDGE_PUNCTUATION = "\"'`()[]{}<>,.;:!?—–-"

# Identity and structure, not evidence. `bullets` is excluded so citing a parent
# Experience does not inherit the numbers stated by its child bullets -- the
# writer is required to cite the narrowest supporting fact.
_SKIP_FIELDS = frozenset({"id", "schema_version", "source", "source_ref", "bullets"})


def claim_numbers(text: str) -> list[str]:
    """Standalone numeric claims in prose, normalized to their digit core."""
    numbers: list[str] = []
    for raw in text.split():
        token = raw.strip(_EDGE_PUNCTUATION)
        if not token or not _QUANTITY.match(token):
            continue
        core = _DIGITS.match(token)
        if core:
            numbers.append(core.group().replace(",", ""))
    return numbers


def fact_numbers(fact: object) -> set[str]:
    """Every digit run stated anywhere in a fact's own evidence fields."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in _SKIP_FIELDS:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif value is not None and not isinstance(value, bool):
            parts.append(str(value))

    walk(fact.model_dump(mode="json"))  # type: ignore[attr-defined]
    return {
        match.group().replace(",", "") for match in _DIGITS.finditer(" ".join(parts))
    }


def numeric_evidence_critique(
    content: ResumeContent, facts: ProfileFacts
) -> ReviewCritique:
    """Blocking for every number no cited fact states."""
    index = index_facts(facts)
    issues: list[ReviewIssue] = []

    def check(text: str | None, fact_ids: list[str], location: str) -> None:
        if not text:
            return
        resolved = [index[fact_id] for fact_id in fact_ids if fact_id in index]
        # Nothing resolved means the citation itself is broken; that is the
        # provenance gate's finding, not a numeric one.
        if not resolved:
            return
        allowed: set[str] = set()
        for fact in resolved:
            allowed |= fact_numbers(fact)
        cited = ", ".join(fact_ids)
        for number in claim_numbers(text):
            if number in allowed:
                continue
            issues.append(
                ReviewIssue(
                    severity=Severity.blocking,
                    location=location,
                    message=(
                        f"the number {number!r} does not appear in the cited "
                        f"fact(s) {cited}"
                    ),
                    suggestion=(
                        "delete the quantity, or restate the claim using a value the "
                        "cited fact states"
                    ),
                )
            )

    check(content.summary, content.summary_provenance, "summary")
    for exp in content.experience:
        for position, bullet in enumerate(exp.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"experience/{exp.company}/bullet {position + 1}",
            )
    for project in content.projects:
        check(project.description, [project.provenance], f"projects/{project.name}")
        for position, bullet in enumerate(project.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"projects/{project.name}/bullet {position + 1}",
            )
    for vol in content.volunteer:
        for position, bullet in enumerate(vol.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"volunteer/{vol.organization}/bullet {position + 1}",
            )

    return ReviewCritique(
        reviewer=NUMERIC_EVIDENCE_REVIEWER,
        score=0 if issues else 100,
        passed=not issues,
        issues=issues,
    )
