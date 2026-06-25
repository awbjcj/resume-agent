import asyncio

from agno.agent import Agent
from pydantic import BaseModel, ConfigDict

from resume_agent.config import get_settings
from resume_agent.llm_runner import (
    AgentRunner,
    Runner,
    acall,
    build_model,
    retry_kwargs,
    resolve_api_key,
    use_json_mode_for,
)

_SNIPPET_CHARS = 500

_INSTRUCTIONS = [
    "Decide whether a job posting plausibly matches the target role the user is hunting.",
    "Judge by the title and the snippet only; be lenient on adjacent roles, strict on unrelated ones.",
    "Reject clearly off-target roles (e.g. truck driver, nurse, creative/marketing) with a short reason.",
    "Answer keep=true to let it through, keep=false to reject; give a one-line reason.",
]


class RelevanceVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: bool
    reason: str


def build_relevance_agent(model_id: str | None = None) -> Runner | None:
    settings = get_settings()
    resolved = model_id or settings.cheap_model
    if not resolve_api_key(resolved):
        return None
    model = build_model(resolved)
    return AgentRunner(
        Agent(
            model=model,
            description="You decide whether a job posting matches a target role.",
            instructions=_INSTRUCTIONS,
            output_schema=RelevanceVerdict,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def compose_relevance_input(target_role: str, title: str | None, jd_text: str) -> str:
    snippet = (jd_text or "")[:_SNIPPET_CHARS]
    return (
        f"TARGET ROLE:\n{target_role}\n\n"
        f"JOB TITLE:\n{title or '(none)'}\n\n"
        f"JOB SNIPPET:\n{snippet}"
    )


def judge_relevance(
    target_role: str, title: str | None, jd_text: str, agent: Runner
) -> RelevanceVerdict:
    result = agent.run(compose_relevance_input(target_role, title, jd_text))
    verdict = result.content
    if not isinstance(verdict, RelevanceVerdict):
        raise TypeError(
            f"Expected RelevanceVerdict from agent, got {type(verdict).__name__}"
        )
    return verdict


async def ajudge_relevance(
    target_role: str,
    title: str | None,
    jd_text: str,
    agent: Runner,
    *,
    sem: asyncio.Semaphore,
) -> RelevanceVerdict:
    result = await acall(
        agent, compose_relevance_input(target_role, title, jd_text), sem=sem
    )
    verdict = result.content
    if not isinstance(verdict, RelevanceVerdict):
        raise TypeError(
            f"Expected RelevanceVerdict from agent, got {type(verdict).__name__}"
        )
    return verdict
