from agno.agent import Agent
from pydantic import BaseModel, ConfigDict, Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner, build_model, use_json_mode_for
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts


class FitLocation(BaseModel):
    """LLM-facing parsed location (every field required, nullable for unknown)."""

    model_config = ConfigDict(extra="forbid")

    city: str | None
    region: str | None
    country: str | None


class FitScore(ExtensibleModel):
    score: int = Field(ge=0, le=100)
    rationale: str
    # New fields default to None so existing callers/faked agents keep working.
    sic_major: str | None = None
    location: FitLocation | None = None


_INSTRUCTIONS = [
    "Score how well the candidate fits the job, from 0 to 100.",
    "Base the score only on the candidate facts and job description provided.",
    "Give a one or two sentence rationale.",
    "Classify the industry the job's domain serves into the single best 2-digit SIC "
    "major-group code (e.g. fintech -> '60', healthcare -> '80', software/business "
    "services -> '73'); set sic_major to that 2-digit string, or null if unclear.",
    "Parse the work location into city, region (US state), and country; leave any "
    "part null if the text does not support it.",
]


def build_fit_agent(model_id: str | None = None) -> Runner:
    s = get_settings()
    model = build_model(model_id or s.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="You rate how well a candidate fits a job.",
            instructions=_INSTRUCTIONS,
            output_schema=FitScore,
            use_json_mode=use_json_mode_for(model),
        )
    )


def compose_fit_input(
    jd_text: str, profile_facts: ProfileFacts, location: str | None = None
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        f"JOB LOCATION: {location or 'unknown'}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def score_fit(input_text: str, agent: Runner) -> FitScore:
    result = agent.run(input_text)
    fit = result.content
    if not isinstance(fit, FitScore):
        raise TypeError(f"Expected FitScore from agent, got {type(fit).__name__}")
    return fit
