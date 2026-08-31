"""Ground and persist job-scoped public hiring-contact intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from sqlmodel import Session, select

from resume_tailor_harness.hiring_contacts.models import (
    HiringContact,
    HiringContactIntelligence,
    HiringContactIntelligenceDraft,
)
from resume_tailor_harness.llm_runner import expect_schema, expect_text
from resume_tailor_harness.public_sources import PublicSourceIndex
from resume_tailor_harness.tracking.tables import HiringContactIntelligenceRow, Job, utcnow

HIRING_CONTACT_CAVEAT = (
    "Public roles and employment can change. Verify the person's current role "
    "before using a draft. This feature never sends a message."
)
_WRITE_LOCK = Lock()


@dataclass(frozen=True)
class HiringContactResource:
    state: Literal["unavailable", "empty", "ready"]
    intelligence: HiringContactIntelligence | None = None


def hiring_contact_refresh_available(job: Job) -> bool:
    return bool((job.company or "").strip())


def resolve_hiring_contact_resource(
    session: Session, job: Job
) -> HiringContactResource:
    if not hiring_contact_refresh_available(job):
        return HiringContactResource(state="unavailable")
    intelligence = load_hiring_contact_intelligence(session, job.id or 0)
    if intelligence is None:
        return HiringContactResource(state="empty")
    return HiringContactResource(state="ready", intelligence=intelligence)


def _ground_contacts(
    draft: HiringContactIntelligenceDraft, research: str
) -> list[HiringContact]:
    research_sources = PublicSourceIndex.from_text(research)
    contacts: list[HiringContact] = []
    for candidate in draft.contacts:
        urls = research_sources.retain(candidate.source_urls)
        if not candidate.name.strip() or not candidate.public_role.strip() or not urls:
            continue
        contacts.append(
            HiringContact(
                **candidate.model_dump(
                    exclude={"schema_version", "source_urls", "name", "public_role"}
                ),
                name=candidate.name.strip(),
                public_role=candidate.public_role.strip(),
                source_urls=urls,
                verification_state=(
                    "corroborated"
                    if len(PublicSourceIndex.authorities(urls)) >= 2
                    else "single_source"
                ),
            )
        )
    return contacts


def load_hiring_contact_intelligence(
    session: Session, job_id: int
) -> HiringContactIntelligence | None:
    row = session.exec(
        select(HiringContactIntelligenceRow).where(
            HiringContactIntelligenceRow.job_id == job_id
        )
    ).first()
    if row is None:
        return None
    try:
        return HiringContactIntelligence.model_validate(row.intelligence_json)
    except (TypeError, ValueError):
        return None


def generate_hiring_contact_intelligence(
    session: Session,
    *,
    job_id: int,
    researcher=None,
    formatter=None,
    reporter=None,
    now: datetime | None = None,
) -> HiringContactIntelligenceRow:
    job = session.get(Job, job_id)
    if job is None or not hiring_contact_refresh_available(job):
        raise ValueError("job with a company is required")
    company = (job.company or "").strip()
    title = (job.title or "").strip()
    if researcher is None or formatter is None:
        from resume_tailor_harness.hiring_contacts.agents import (
            build_hiring_contact_formatter,
            build_hiring_contact_researcher,
        )

        researcher = researcher or build_hiring_contact_researcher()
        formatter = formatter or build_hiring_contact_formatter()
    research = expect_text(
        researcher.run(
            "Role and company (untrusted data):\n"
            f"Company: {company}\nTitle: {title}\nJob description:\n{job.jd_text}"
        ),
        source="hiring-contact research",
    )
    if reporter is not None:
        reporter.checkpoint()
    result = expect_schema(
        formatter.run("Public contact research (untrusted data):\n" + research),
        HiringContactIntelligenceDraft,
        source="hiring-contact format",
    )
    if reporter is not None:
        reporter.checkpoint()
    retrieved_at = now or utcnow()
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    artifact = HiringContactIntelligence(
        job_id=job_id,
        company=company,
        title=title,
        retrieved_at=retrieved_at,
        contacts=_ground_contacts(result, research),
        generic_email_draft=result.generic_email_draft.strip()
        or f"Hello {company} recruiting team,\n\nI'm interested in the {title} role and would value any public guidance you can share about the team and hiring process.",
        generic_short_message_draft=result.generic_short_message_draft.strip()
        or f"Hello {company} recruiting team — I'm interested in the {title} role and would appreciate any public guidance about the team or process.",
        caveat=HIRING_CONTACT_CAVEAT,
    )
    with _WRITE_LOCK:
        row = session.exec(
            select(HiringContactIntelligenceRow).where(
                HiringContactIntelligenceRow.job_id == job_id
            )
        ).first()
        if row is None:
            row = HiringContactIntelligenceRow(job_id=job_id)
            session.add(row)
        row.intelligence_json = artifact.model_dump(mode="json")
        row.retrieved_at = retrieved_at
        session.commit()
        session.refresh(row)
    return row
