from datetime import datetime, timezone
from types import SimpleNamespace

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.hiring_contacts.models import (
    HiringContactDraft,
    HiringContactIntelligenceDraft,
)
from resume_agent.llm_runner import UnparsedAgentOutput
from resume_agent.services.hiring_contacts import (
    generate_hiring_contact_intelligence,
    load_hiring_contact_intelligence,
)
from resume_agent.tracking.tables import Job


class _Runner:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return SimpleNamespace(content=self.content)


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_contact_generation_keeps_only_exact_publicly_grounded_people():
    engine = _engine()
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    draft = HiringContactIntelligenceDraft(
        contacts=[
            HiringContactDraft(
                name="Avery Chen",
                public_role="VP of Platform",
                contact_type="team_leader",
                source_urls=[
                    "https://acme.com/team/avery",
                    "https://conference.org/speakers/avery",
                ],
                why_relevant="Publicly leads the platform organization.",
                email_draft="Hello Avery — I am exploring the platform role.",
                short_message_draft="Hello Avery — may I ask about the platform team?",
            ),
            HiringContactDraft(
                name="Invented Person",
                public_role="Recruiter",
                source_urls=["https://invented.example/person"],
            ),
        ],
        generic_email_draft="Hello recruiting team",
        generic_short_message_draft="Hello team",
    )
    with Session(engine) as session:
        job = Job(source="manual", company="Acme", title="Platform Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        generate_hiring_contact_intelligence(
            session,
            job_id=job.id,
            researcher=_Runner(
                "https://acme.com/team/avery "
                "https://conference.org/speakers/avery"
            ),
            formatter=_Runner(draft),
            now=now,
        )
        artifact = load_hiring_contact_intelligence(session, job.id)

    assert artifact is not None
    assert [contact.name for contact in artifact.contacts] == ["Avery Chen"]
    assert artifact.contacts[0].verification_state == "corroborated"
    assert artifact.retrieved_at == now
    assert "never sends" in artifact.caveat


def test_contact_generation_preserves_generic_drafts_when_no_person_is_verified():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="manual", company="Acme", title="Platform Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        generate_hiring_contact_intelligence(
            session,
            job_id=job.id,
            researcher=_Runner("No verified people found."),
            formatter=_Runner(HiringContactIntelligenceDraft()),
        )
        artifact = load_hiring_contact_intelligence(session, job.id)

    assert artifact is not None
    assert artifact.contacts == []
    assert "recruiting team" in artifact.generic_email_draft
    assert "recruiting team" in artifact.generic_short_message_draft


def test_contact_generation_rejects_a_source_url_prefix():
    engine = _engine()
    draft = HiringContactIntelligenceDraft(
        contacts=[
            HiringContactDraft(
                name="Avery Chen",
                public_role="VP of Platform",
                source_urls=["https://acme.example/team/avery"],
            )
        ]
    )
    with Session(engine) as session:
        job = Job(source="manual", company="Acme", title="Platform Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        generate_hiring_contact_intelligence(
            session,
            job_id=job.id,
            researcher=_Runner("https://acme.example/team/avery-profile"),
            formatter=_Runner(draft),
        )
        artifact = load_hiring_contact_intelligence(session, job.id)

    assert artifact is not None
    assert artifact.contacts == []


def test_contact_generation_reports_unparsed_formatter_output_at_the_model_boundary():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="manual", company="Acme", title="Platform Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        try:
            generate_hiring_contact_intelligence(
                session,
                job_id=job.id,
                researcher=_Runner("No contacts found."),
                formatter=_Runner("not structured output"),
            )
        except UnparsedAgentOutput as exc:
            assert "Expected HiringContactIntelligenceDraft" in str(exc)
            assert "hiring-contact format agent" in str(exc)
        else:
            raise AssertionError("expected unparsed formatter output to be rejected")
