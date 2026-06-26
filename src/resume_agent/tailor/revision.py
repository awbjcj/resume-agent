from resume_agent.llm_runner import Runner
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent


def compose_user_revision_input(
    content: ResumeContent, instruction: str, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "USER INSTRUCTION (apply exactly; change only what is asked):\n"
        f"{instruction}"
    )


def apply_revision(input_text: str, agent: Runner) -> ResumeContent:
    content = agent.run(input_text).content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from revision agent, got {type(content).__name__}")
    return content
