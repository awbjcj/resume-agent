from agno.agent import Agent

from resume_agent.config import get_settings
from resume_agent.llm_runner import (
    AgentRunner,
    Runner,
    build_model,
    retry_kwargs,
    use_json_mode_for,
)
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.style_guide import compose_instructions


def model_for_tier(tier: str) -> str:
    s = get_settings()
    return {"cheap": s.cheap_model, "mid": s.mid_model, "premium": s.premium_model}.get(tier, s.mid_model)


_TAILOR_INSTRUCTIONS = [
    "Rewrite the candidate's resume to target the given job.",
    "Use ONLY facts present in the candidate profile. Never invent anything.",
    "Every bullet, experience, project, and selected skill MUST set 'provenance' to the id of the source fact it came from.",
    "Surface real matches to the job's keywords; do not keyword-stuff or exaggerate.",
]

_REVISER_INSTRUCTIONS = [
    "Revise the resume content to address the reviewer issues and suggestions.",
    "Keep every claim fact-locked: use only the candidate profile facts and preserve correct 'provenance' ids.",
    "Do not introduce any claim that lacks a provenance id pointing at a real profile fact.",
]

_REVISION_INSTRUCTIONS = [
    "Apply the user's instruction to the resume content.",
    "Change ONLY what the instruction asks; keep everything else intact.",
    "Use ONLY facts present in the candidate profile. Never invent anything.",
    "Preserve fact-lock: every bullet, experience, project, and selected skill MUST keep a provenance id pointing at a real profile fact.",
    "If the instruction cannot be satisfied truthfully, make the closest truthful change and keep provenance valid.",
]

REVIEWER_INSTRUCTIONS: dict[str, list[str]] = {
    "fact-check": [
        "You are a fact-checker. Verify every claim in the resume traces to a fact in the candidate profile.",
        "A bullet/skill is supported only if its 'provenance' id exists in the profile and the text stays faithful to that fact.",
        "Set passed=False with a 'blocking' issue for ANY unsupported or exaggerated claim; otherwise passed=True.",
    ],
    "ats-keyword": [
        "You assess ATS keyword coverage: are the job's must-have skills/keywords present and in context?",
        "Score 0-100; list missing keywords as issues with suggestions (only if truthfully supported). Set passed accordingly.",
    ],
    "recruiter": [
        "You are a recruiter doing a 6-second scan. Judge clarity, impact, and formatting.",
        "Score 0-100, give concise actionable issues, and set passed.",
    ],
    "hiring-manager": [
        "You are the hiring manager. Judge technical credibility and the relevance of experience/projects to the role.",
        "Score 0-100, give specific issues, and set passed.",
    ],
    "concision": [
        "You assess concision and style: one page, active voice, quantified impact, no fluff.",
        "Score 0-100, give trimming/rewrite suggestions, and set passed.",
    ],
}

_DEFAULT_REVIEWER_INSTRUCTIONS = [
    "Review the resume and return a structured critique with a 0-100 score, a pass/fail, and issues.",
]


def build_tailor_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You are an expert resume writer who never fabricates.",
            instructions=compose_instructions(_TAILOR_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def build_reviser_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise resume content while keeping it strictly fact-locked.",
            instructions=compose_instructions(_REVISER_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def build_revision_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise resume content per a user's instruction, strictly fact-locked.",
            instructions=compose_instructions(_REVISION_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def build_reviewer_agent(
    name: str, model_id: str | None = None, style_guide: str | None = None
) -> Runner:
    model = build_model(model_id or model_for_tier("mid"))
    return AgentRunner(
        Agent(
            model=model,
            description=f"You are the '{name}' resume reviewer.",
            instructions=compose_instructions(
                REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS), style_guide
            ),
            output_schema=ReviewCritique,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
