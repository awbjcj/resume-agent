"""View application prompts and edit their subordinate guidance layer."""

from fastapi import APIRouter

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.prompts import AgentPromptItem, GuidanceUpdate
from resume_tailor_harness.prompts.guidance import load_guidance, save_guidance
from resume_tailor_harness.prompts.registry import PROMPT_SPECS, PromptSpec, spec_for


router = APIRouter()


def _item(spec: PromptSpec, guidance: dict[str, str]) -> AgentPromptItem:
    return AgentPromptItem(
        key=spec.key,
        title=spec.title,
        stage=spec.stage,
        description=spec.description,
        instructions=list(spec.instructions),
        guidance=guidance.get(spec.key) if spec.editable else None,
        editable=spec.editable,
    )


@router.get("/agents/prompts", response_model=list[AgentPromptItem])
def list_prompts() -> list[AgentPromptItem]:
    guidance = load_guidance()
    return [_item(spec, guidance) for spec in PROMPT_SPECS]


@router.put("/agents/prompts/{key}", response_model=AgentPromptItem)
def put_guidance(key: str, body: GuidanceUpdate) -> AgentPromptItem:
    spec = spec_for(key)
    if spec is None:
        raise ApiException(404, "unknown_agent", f"No agent named {key!r}.")
    if not spec.editable:
        raise ApiException(
            409,
            "agent_not_editable",
            f"{spec.title} is an integrity gate and cannot be customized.",
        )
    saved = save_guidance(key, body.guidance)
    return _item(spec, saved)
