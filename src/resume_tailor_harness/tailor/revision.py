from resume_tailor_harness.llm_runner import Runner, expect_schema
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent


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
    return expect_schema(agent.run(input_text), ResumeContent, source="revision")
