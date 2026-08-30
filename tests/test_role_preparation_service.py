from datetime import datetime, timezone
from types import SimpleNamespace

from sqlmodel import Session

from resume_agent.company_intelligence.models import (
    CompanyIntelligenceDraft,
    CompanyIntelligenceInsight,
    CompanyIntelligenceSource,
)
from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.role_preparation.models import (
    RolePreparationAsk,
    RolePreparationCompetency,
    RolePreparationDraft,
    RolePreparationQuestion,
)
from resume_agent.services.company_intelligence import generate_company_intelligence
from resume_agent.services.role_preparation import (
    build_role_preparation_inputs,
    generate_role_preparation_brief,
    load_role_preparation_brief,
    role_preparation_inputs_changed,
)
from resume_agent.tracking.tables import (
    Application,
    ApplicationEvent,
    Job,
    ResumeVersion,
)


class _Runner:
    def __init__(self, content):
        self.content = content
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.content)


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def _company_draft():
    return CompanyIntelligenceDraft(
        overview="Acme builds infrastructure software.",
        sources=[
            CompanyIntelligenceSource(
                title="Strategy",
                url="https://acme.example/strategy",
                publisher="Acme",
                source_type="official",
            )
        ],
        insights=[
            CompanyIntelligenceInsight(
                axis="strategy",
                summary="Acme is investing in platform tooling.",
                citations=["https://acme.example/strategy"],
            )
        ],
    )


def _prep_draft():
    return RolePreparationDraft(
        positioning_summary="Lead with platform ownership.",
        competencies=[
            RolePreparationCompetency(
                name="Platform ownership",
                rationale="The JD asks for service ownership.",
            )
        ],
        likely_questions=[
            RolePreparationQuestion(
                question="How have you improved a production platform?",
                question_type="behavioral",
                competency="Platform ownership",
                rationale="The role owns core services.",
                company_citations=["https://acme.example/strategy"],
                story_prompt="Use the billing reliability example from the resume.",
            ),
            RolePreparationQuestion(
                question="This item has an invented company source.",
                company_citations=["https://invented.example/claim"],
            ),
        ],
        questions_to_ask=[
            RolePreparationAsk(
                text="How does this team contribute to the platform investment?",
                rationale="Tests role scope.",
                company_citations=["https://acme.example/strategy"],
            )
        ],
        recruiter_verification_questions=[
            RolePreparationAsk(
                text="Which interview stage comes next?",
                rationale="The process is not stated in the JD.",
            )
        ],
        prior_round_focus=["Give a more concrete scaling example."],
    )


def _seed(session: Session):
    job = Job(
        source="manual",
        company="Acme",
        title="Platform Engineer",
        jd_text="Own Python services and improve platform reliability.",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    assert job.id is not None
    older = ResumeVersion(
        job_id=job.id,
        content_json={"summary": "Older resume"},
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    selected = ResumeVersion(
        job_id=job.id,
        content_json={"summary": "Selected resume", "facts": ["Billing reliability"]},
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    session.add(older)
    session.add(selected)
    session.commit()
    session.refresh(selected)
    assert selected.id is not None
    application = Application(
        job_id=job.id,
        resume_version_id=selected.id,
        status="interview",
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    assert application.id is not None
    event = ApplicationEvent(
        application_id=application.id,
        kind="technical_round",
        interviewers="Sam, Staff Engineer",
        result="advanced",
        notes="Platform architecture discussion",
        reflection="My scaling answer needed a more concrete example.",
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    generate_company_intelligence(
        session,
        company="Acme",
        settings=Settings(),
        research_agent=_Runner("https://acme.example/strategy"),
        formatter=_Runner(_company_draft()),
    )
    return job, selected, event


def test_role_preparation_freezes_selected_resume_and_prior_round_signals():
    engine = _engine()
    formatter = _Runner(_prep_draft())
    with Session(engine) as session:
        job, selected, event = _seed(session)
        assert job.id is not None
        generate_role_preparation_brief(
            session,
            job_id=job.id,
            formatter=formatter,
            now=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        )
        brief = load_role_preparation_brief(session, job.id)
        selected_id = selected.id
        event_id = event.id

    assert brief is not None
    assert brief.resume_version_id == selected_id
    assert brief.signal_event_ids == [event_id]
    assert brief.application_status == "interview"
    assert brief.company_intelligence_version_id is not None
    assert [item.question for item in brief.likely_questions] == [
        "How have you improved a production platform?"
    ]
    assert "Selected resume" in formatter.prompts[0]
    assert "Sam, Staff Engineer" in formatter.prompts[0]
    assert "more concrete example" in formatter.prompts[0]
    assert brief.likely_questions[0].story_prompt == (
        "Use the billing reliability example from the resume."
    )


def test_role_preparation_removes_a_story_prompt_without_resume_evidence():
    engine = _engine()
    draft = _prep_draft()
    draft.likely_questions[0].story_prompt = (
        "Use the Kubernetes migration that reduced deployment time by 80 percent."
    )
    with Session(engine) as session:
        job, _selected, _event = _seed(session)
        assert job.id is not None
        generate_role_preparation_brief(
            session,
            job_id=job.id,
            formatter=_Runner(draft),
        )
        brief = load_role_preparation_brief(session, job.id)

    assert brief is not None
    assert brief.likely_questions[0].story_prompt == ""


def test_role_preparation_uses_latest_resume_without_application_selection():
    engine = _engine()
    with Session(engine) as session:
        job = Job(
            source="manual",
            company="Acme",
            title="Engineer",
            jd_text="Build services",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        first = ResumeVersion(
            job_id=job.id,
            content_json={"summary": "First"},
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        latest = ResumeVersion(
            job_id=job.id,
            content_json={"summary": "Latest"},
            created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        session.add(first)
        session.add(latest)
        session.commit()
        session.refresh(latest)
        generate_company_intelligence(
            session,
            company="Acme",
            settings=Settings(),
            research_agent=_Runner("https://acme.example/strategy"),
            formatter=_Runner(_company_draft()),
        )
        inputs = build_role_preparation_inputs(session, job.id)

    assert inputs is not None
    assert inputs.resume_version_id == latest.id
    assert inputs.resume_content["summary"] == "Latest"


def test_role_preparation_detects_changed_event_inputs_without_rewriting_brief():
    engine = _engine()
    with Session(engine) as session:
        job, _selected, event = _seed(session)
        assert job.id is not None
        generate_role_preparation_brief(
            session,
            job_id=job.id,
            formatter=_Runner(_prep_draft()),
        )
        brief = load_role_preparation_brief(session, job.id)
        assert brief is not None
        assert role_preparation_inputs_changed(session, brief) is False
        event.reflection = "A newly captured reflection"
        session.add(event)
        session.commit()
        assert role_preparation_inputs_changed(session, brief) is True
        unchanged = load_role_preparation_brief(session, job.id)

    assert unchanged is not None
    assert unchanged.input_fingerprint == brief.input_fingerprint
