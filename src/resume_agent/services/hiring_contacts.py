"""Ground and persist job-scoped public hiring-contact intelligence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, select

from resume_agent.hiring_contacts.models import (
    HiringContact,
    HiringContactIntelligence,
    HiringContactIntelligenceDraft,
)
from resume_agent.discovery.source_resolution.identity import registrable_domain
from resume_agent.tracking.tables import HiringContactIntelligenceRow, Job, utcnow

HIRING_CONTACT_CAVEAT = (
    "Public roles and employment can change. Verify the person's current role "
    "before using a draft. This feature never sends a message."
)
_WRITE_LOCK = Lock()
_URL = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)


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


def _normalized_http_url(value: str) -> str | None:
    parsed = urlsplit(value.rstrip(".,;:"))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _authorities(urls: list[str]) -> set[str]:
    return {domain for url in urls if (domain := registrable_domain(url))}


def _ground_contacts(
    draft: HiringContactIntelligenceDraft, research: str
) -> list[HiringContact]:
    grounded_urls: dict[str, str] = {}
    for raw in _URL.findall(research):
        exact_url = raw.rstrip(".,;:")
        normalized = _normalized_http_url(exact_url)
        if normalized is not None:
            grounded_urls.setdefault(normalized, exact_url)
    contacts: list[HiringContact] = []
    for candidate in draft.contacts:
        urls = sorted(
            {
                grounded_urls[normalized]
                for url in candidate.source_urls
                if (normalized := _normalized_http_url(url)) in grounded_urls
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
    if job is None or not hiring_contact_refresh_available(job):
        raise ValueError("job with a company is required")
    company = (job.company or "").strip()
    title = (job.title or "").strip()
    research = str(
        researcher.run(
            "Role and company (untrusted data):\n"
            f"Company: {company}\nTitle: {title}\nJob description:\n{job.jd_text}"
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
