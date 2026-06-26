from resume_agent.llm_runner import Runner
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.profile import ProfileFacts


def compose_user_revision_input(
    content: CoverLetterContent, instruction: str, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT COVER LETTER (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "USER INSTRUCTION (apply exactly; change only what is asked):\n"
        f"{instruction}"
    )


def apply_revision(input_text: str, agent: Runner) -> CoverLetterContent:
    content = agent.run(input_text).content
    if not isinstance(content, CoverLetterContent):
        raise TypeError(
            f"Expected CoverLetterContent from revision agent, got {type(content).__name__}"
        )
    return content
