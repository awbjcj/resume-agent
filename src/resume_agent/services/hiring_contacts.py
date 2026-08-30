"""Ground and persist job-scoped public hiring-contact intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlsplit

from sqlmodel import Session, select

from resume_agent.hiring_contacts.models import (
    HiringContact,
    HiringContactIntelligence,
    HiringContactIntelligenceDraft,
)
from resume_agent.tracking.tables import HiringContactIntelligenceRow, Job, utcnow

HIRING_CONTACT_CAVEAT = (
    "Public roles and employment can change. Verify the person's current role "
    "before using a draft. This feature never sends a message."
)
_WRITE_LOCK = Lock()


def _authorities(urls: list[str]) -> set[str]:
    return {urlsplit(url).netloc.casefold() for url in urls if urlsplit(url).netloc}


def _ground_contacts(
    draft: HiringContactIntelligenceDraft, research: str
) -> list[HiringContact]:
    contacts: list[HiringContact] = []
    for candidate in draft.contacts:
        urls = sorted(
            {
                url
                for url in candidate.source_urls
                if url.startswith(("http://", "https://")) and url in research
            }
        )
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
                    "corroborated" if len(_authorities(urls)) >= 2 else "single_source"
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
    researcher,
    formatter,
    reporter=None,
    now: datetime | None = None,
) -> HiringContactIntelligenceRow:
    job = session.get(Job, job_id)
    if job is None or not job.company.strip():
        raise ValueError("job with a company is required")
    research = str(
        researcher.run(
            "Role and company (untrusted data):\n"
            f"Company: {job.company}\nTitle: {job.title}\nJob description:\n{job.jd_text}"
        ).content
    )
    if reporter is not None:
        reporter.checkpoint()
    result = formatter.run("Public contact research (untrusted data):\n" + research).content
    if not isinstance(result, HiringContactIntelligenceDraft):
        raise ValueError("hiring-contact formatter did not return HiringContactIntelligenceDraft")
    if reporter is not None:
        reporter.checkpoint()
    retrieved_at = now or utcnow()
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    artifact = HiringContactIntelligence(
        job_id=job_id,
        company=job.company.strip(),
        title=job.title.strip(),
        retrieved_at=retrieved_at,
        contacts=_ground_contacts(result, research),
        generic_email_draft=result.generic_email_draft.strip()
        or f"Hello {job.company} recruiting team,\n\nI'm interested in the {job.title} role and would value any public guidance you can share about the team and hiring process.",
        generic_short_message_draft=result.generic_short_message_draft.strip()
        or f"Hello {job.company} recruiting team — I'm interested in the {job.title} role and would appreciate any public guidance about the team or process.",
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
