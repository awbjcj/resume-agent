"""Deterministic resume content for template validation and previews."""

from resume_agent.models.profile import Contact, Education
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)


def sample_resume_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(
            name="Alex Sample",
            headline="Software Engineer",
            email="alex@example.com",
            location="Remote",
        ),
        summary="Engineer with six years building reliable data-heavy services.",
        experience=[
            TailoredExperience(
                company="Acme Corp",
                title="Senior Engineer",
                start="2021",
                end="Present",
                provenance="sample-experience",
                bullets=[
                    TailoredBullet(
                        text="Cut p95 latency 40% by redesigning the query planner.",
                        provenance="sample-latency",
                    ),
                    TailoredBullet(
                        text="Led a four-person team shipping a billing service.",
                        provenance="sample-leadership",
                    ),
                ],
            )
        ],
        skills={
            "Hard skills": [
                TailoredSkill(name="Python", provenance="sample-python"),
                TailoredSkill(name="PostgreSQL", provenance="sample-postgres"),
            ]
        },
        education=[
            Education(
                institution="State University",
                degree="BSc",
                field="Computer Science",
            )
        ],
    )
