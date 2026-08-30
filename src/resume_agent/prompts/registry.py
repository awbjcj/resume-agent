"""Declarative projection of every application-owned Agno prompt."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from resume_agent.cover_letter import agents as cover_letter_agents
from resume_agent.company_intelligence import agents as company_intelligence_agents
from resume_agent.discovery import (
    extract,
    fit,
    industry,
    relevance,
    scout,
)
from resume_agent.discovery.scraper import learn
from resume_agent.discovery.url_ingest import llm as url_ingest_llm
from resume_agent.gmail import classify
from resume_agent.interview import agent as interview_agent
from resume_agent.profile import (
    aspect_classifier,
    coach,
    extractor,
    inference,
    merge,
    project_extractor,
    synthesis,
)
from resume_agent.prompts.guidance import NON_EDITABLE_KEYS
from resume_agent.services import email_writer
from resume_agent.suggestions import agents as suggestions_agents
from resume_agent.tailor import agents as tailor_agents
from resume_agent.tailor import match_plan
from resume_agent.taxonomy import groups
from resume_agent.tracking import canonicalize


@dataclass(frozen=True)
class PromptSpec:
    key: str
    title: str
    stage: str
    description: str
    instructions: tuple[str, ...]
    editable: bool = True


def _spec(
    key: str,
    title: str,
    stage: str,
    description: str,
    instructions: Iterable[str],
) -> PromptSpec:
    return PromptSpec(
        key=key,
        title=title,
        stage=stage,
        description=description,
        instructions=tuple(instructions),
        editable=key not in NON_EDITABLE_KEYS,
    )


PROMPT_SPECS = (
    _spec(
        "tailor-writer",
        "Resume writer",
        "tailoring",
        "Writes a targeted resume under the profile fact-lock.",
        tailor_agents._writer_instructions(tailor_agents._TAILOR_INSTRUCTIONS),
    ),
    _spec(
        "tailor-reviser",
        "Resume reviser",
        "tailoring",
        "Repairs a reviewed resume without adding facts.",
        tailor_agents._writer_instructions(tailor_agents._REVISER_INSTRUCTIONS),
    ),
    _spec(
        "tailor-revision",
        "Manual revision editor",
        "tailoring",
        "Applies one user-requested resume edit.",
        tailor_agents._REVISION_INSTRUCTIONS,
    ),
    _spec(
        "match-plan",
        "Match planner",
        "tailoring",
        "Plans evidence emphasis for a job by fact id.",
        match_plan._plan_instructions(),
    ),
    _spec(
        "suggestions-research",
        "Match-gap advisor (research)",
        "tailoring",
        "Researches current ways to close evidence gaps.",
        suggestions_agents._SEARCH_INSTRUCTIONS,
    ),
    _spec(
        "suggestions-format",
        "Match-gap advisor (formatter)",
        "tailoring",
        "Formats grounded research into suggestions.",
        suggestions_agents._FORMAT_INSTRUCTIONS,
    ),
    _spec(
        "company-intelligence-research",
        "Company intelligence (research)",
        "discovery",
        "Researches current, cited company facts.",
        company_intelligence_agents._SEARCH_INSTRUCTIONS,
    ),
    _spec(
        "company-intelligence-format",
        "Company intelligence (formatter)",
        "discovery",
        "Formats grounded company research into a durable dossier.",
        company_intelligence_agents._FORMAT_INSTRUCTIONS,
    ),
    _spec(
        "reviewer-fact-check",
        "Fact-check gate",
        "review",
        "Hard gate for unsupported resume claims.",
        tailor_agents._reviewer_instructions("fact-check"),
    ),
    _spec(
        "reviewer-ats-keyword",
        "ATS keyword reviewer",
        "review",
        "Checks credible job-language coverage.",
        tailor_agents._reviewer_instructions("ats-keyword"),
    ),
    _spec(
        "reviewer-recruiter",
        "Recruiter reviewer",
        "review",
        "Reviews first-scan clarity and relevance.",
        tailor_agents._reviewer_instructions("recruiter"),
    ),
    _spec(
        "reviewer-hiring-manager",
        "Hiring-manager reviewer",
        "review",
        "Reviews technical credibility and role fit.",
        tailor_agents._reviewer_instructions("hiring-manager"),
    ),
    _spec(
        "reviewer-concision",
        "Concision reviewer",
        "review",
        "Reviews prioritization, repetition, and density.",
        tailor_agents._reviewer_instructions("concision"),
    ),
    _spec(
        "reviewer-merged-advisory",
        "Merged advisory panel",
        "review",
        "Runs configured advisory rubrics in one model call.",
        tailor_agents._MERGED_ADVISORY_BASE_INSTRUCTIONS,
    ),
    _spec(
        "cover-letter-draft",
        "Cover letter writer",
        "cover-letter",
        "Drafts a fact-grounded cover letter.",
        cover_letter_agents._DRAFT_INSTRUCTIONS,
    ),
    _spec(
        "cover-letter-revise",
        "Cover letter reviser",
        "cover-letter",
        "Repairs a reviewed cover letter.",
        cover_letter_agents._REVISE_INSTRUCTIONS,
    ),
    _spec(
        "cover-letter-revision",
        "Cover letter revision editor",
        "cover-letter",
        "Applies one requested cover-letter edit.",
        cover_letter_agents._REVISION_INSTRUCTIONS,
    ),
    _spec(
        "extract-criteria",
        "Job criteria extractor",
        "discovery",
        "Extracts structured criteria from a job description.",
        extract._INSTRUCTIONS,
    ),
    _spec(
        "fit-score",
        "Fit scorer",
        "discovery",
        "Scores evidence-based candidate fit.",
        fit._INSTRUCTIONS,
    ),
    _spec(
        "relevance-judge",
        "Relevance judge",
        "discovery",
        "Applies the high-recall discovery prefilter.",
        relevance._INSTRUCTIONS,
    ),
    _spec(
        "industry-classifier",
        "Industry classifier",
        "discovery",
        "Normalizes the employer industry.",
        industry._INSTRUCTIONS,
    ),
    _spec(
        "url-ingest",
        "URL job parser",
        "discovery",
        "Recovers one posting from cleaned page text.",
        url_ingest_llm._INSTRUCTIONS,
    ),
    _spec(
        "scraper-learn",
        "Scraper recipe learner",
        "discovery",
        "Learns a browser recipe for a careers board.",
        learn._INSTRUCTIONS,
    ),
    _spec(
        "discovery-scout",
        "Discovery Scout",
        "discovery",
        "Researches company sources and search conditions in a conversational session.",
        scout.scout_instructions(),
    ),
    _spec(
        "discovery-scout-format",
        "Discovery Scout formatter",
        "discovery",
        "Formats grounded Scout notes into a validated conversational turn.",
        scout._FORMAT_INSTRUCTIONS,
    ),
    _spec(
        "profile-extractor",
        "Profile fact extractor",
        "profile",
        "Extracts immutable facts from a document.",
        extractor._INSTRUCTIONS,
    ),
    _spec(
        "aspect-classifier",
        "Bullet aspect classifier",
        "profile",
        "Classifies existing evidence bullets without changing their facts.",
        [
            *aspect_classifier._INSTRUCTIONS,
            "Aspect definitions: "
            + "; ".join(
                f"{name}={description}"
                for name, description in aspect_classifier.ASPECT_DESCRIPTIONS.items()
            ),
        ],
    ),
    _spec(
        "profile-synthesis",
        "Synthesis writer",
        "profile",
        "Synthesizes excerpt-backed supporting facts.",
        synthesis._SYNTHESIS_INSTRUCTIONS,
    ),
    _spec(
        "profile-entailment",
        "Synthesis verifier",
        "profile",
        "Checks synthesized facts against excerpts.",
        synthesis._ENTAILMENT_INSTRUCTIONS,
    ),
    _spec(
        "project-extractor",
        "Project extractor",
        "profile",
        "Extracts one project and its evidenced skills.",
        project_extractor._INSTRUCTIONS,
    ),
    _spec(
        "skill-inference",
        "Skill inferrer",
        "profile",
        "Derives evidence-linked inferred skills.",
        inference._INSTRUCTIONS,
    ),
    _spec(
        "profile-dedup",
        "Fact deduplicator",
        "profile",
        "Groups duplicate profile facts.",
        merge._DEDUP_INSTRUCTIONS,
    ),
    _spec(
        "coach",
        "Profile coach",
        "profile",
        "Runs evidence-locked profile coaching.",
        coach._COACH_INSTRUCTIONS,
    ),
    _spec(
        "coach-formatter",
        "Coach formatter",
        "profile",
        "Formats coach notes into a structured turn.",
        coach._FORMAT_INSTRUCTIONS,
    ),
    _spec(
        "skill-groups",
        "Skill-group classifier",
        "profile",
        "Assigns skills to the fixed group vocabulary.",
        groups._GROUP_INSTRUCTIONS,
    ),
    _spec(
        "taxonomy-clusters",
        "Taxonomy clusterer",
        "profile",
        "Clusters technical-skill tokens.",
        canonicalize._INSTRUCTIONS,
    ),
    _spec(
        "taxonomy-themes",
        "Taxonomy themes (legacy)",
        "profile",
        "Partitions canonical skills into legacy themes.",
        canonicalize._THEME_INSTRUCTIONS,
    ),
    _spec(
        "taxonomy-clusters-incremental",
        "Taxonomy incremental clusterer",
        "profile",
        "Maps new tokens into stable clusters.",
        canonicalize._INCREMENTAL_INSTRUCTIONS,
    ),
    _spec(
        "taxonomy-domains-incremental",
        "Taxonomy incremental domains",
        "profile",
        "Assigns new clusters to stable domains.",
        canonicalize._INCREMENTAL_DOMAIN_INSTRUCTIONS,
    ),
    _spec(
        "interviewer",
        "Mock interviewer",
        "interview",
        "Core rules for in-character interview turns.",
        interview_agent._PERSONA_CORE,
    ),
    _spec(
        "interview-debrief",
        "Interview debrief",
        "interview",
        "Scores the completed mock interview.",
        interview_agent._DEBRIEF_INSTRUCTIONS,
    ),
    _spec(
        "interview-format",
        "Interview formatter",
        "interview",
        "Formats interviewer notes into a turn.",
        interview_agent._FORMAT_INSTRUCTIONS,
    ),
    _spec(
        "email-writer",
        "Email writer",
        "email",
        "Drafts fact-grounded job-search emails.",
        email_writer._WRITER_INSTRUCTIONS,
    ),
    _spec(
        "email-classifier",
        "Recruiting email classifier",
        "email",
        "Classifies recruiting email outcomes.",
        classify._CLASSIFIER_INSTRUCTIONS,
    ),
)

SPECS_BY_KEY = {spec.key: spec for spec in PROMPT_SPECS}


def spec_for(key: str) -> PromptSpec | None:
    return SPECS_BY_KEY.get(key)
