"""LLM email drafting grounded in profile facts. Human gate, never sends.

The prompt's only permitted source for claims about the user is
facts.json — same evidence discipline as tailoring, but the hard gate is
the human editing the draft in Gmail, not an LLM reviewer round.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.tenancy.paths import FACTS_PATH
from resume_agent.gmail.client import fetch_message_body, fetch_recent_messages
from resume_agent.gmail.match import match_email_to_application
from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.prompts.guidance import with_guidance
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    save_email_draft,
)
from resume_agent.tracking.tables import EmailDraft

DRAFT_TYPES = ("follow_up", "thank_you", "withdrawal", "cold_outreach")

_TYPE_GUIDANCE = {
    "follow_up": "A short, warm check-in on the application's status. 80-140 words.",
    "thank_you": "A brief thank-you after an interview, referencing the role. 60-120 words.",
    "withdrawal": "A gracious withdrawal of the application. 50-100 words.",
    "cold_outreach": (
        "A concise introduction to someone at the company. 100-160 words. "
        "Structure it: open with one specific, genuine hook drawn from the job "
        "description or company (a product decision, a stated problem, a "
        "number) — not a generic compliment; introduce who the candidate is in "
        "a sentence or two grounded strictly in the facts; bridge the "
        "company's apparent need to the candidate's most relevant evidence; "
        "close low-pressure and confident. Let the single strongest fact carry "
        "the email instead of listing credentials."
    ),
}

_JD_CHAR_LIMIT = 2000
_FACTS_CHAR_LIMIT = 6000
_THREAD_CHAR_LIMIT = 1500

_WRITER_INSTRUCTIONS = (
    "You draft professional job-search emails that read like a thoughtful "
    "person wrote them, not a template. Open with something specific to this "
    "company, role, or email thread — never a generic 'I am writing to "
    "express my interest.' Sound like a colleague reaching out, not a pitch "
    "deck: confident but not desperate, and never apologize for or "
    "over-explain a gap. Never use cover-letter clichés such as 'I look "
    "forward to hearing from you', 'Please find attached', or 'I would love "
    "the opportunity'. Claims about the candidate must come ONLY from the "
    "provided profile facts — never invent experience, numbers, or "
    "credentials. Match the requested tone and length. Return the subject and "
    "body."
)


class EmailDraftContent(ExtensibleModel):
    subject: str
    body: str


def build_writer_agent() -> Runner:
    from agno.agent import Agent

    from resume_agent.llm_runner import (
        AgentRunner,
        build_model,
        retry_kwargs,
        use_json_mode_for,
    )
    from resume_agent.tailor.agents import model_for_tier

    model = build_model(model_for_tier("mid"))
    return AgentRunner(
        Agent(
            model=model,
            description="Draft one professional job-search email.",
            instructions=with_guidance("email-writer", _WRITER_INSTRUCTIONS),
            output_schema=EmailDraftContent,
            use_json_mode=use_json_mode_for(model, EmailDraftContent),
            **retry_kwargs(),
        )
    )


_ADDR_RE = re.compile(r"<([^>]+)>")


def _sender_address(sender: str) -> str:
    match = _ADDR_RE.search(sender)
    if match:
        return match.group(1).strip()
    return sender.strip() if "@" in sender else ""


def _thread_context(service: Any, job) -> tuple[str, str, str] | None:
    """(sender_addr, thread_id, excerpt) from the newest matched inbox message."""
    emails = fetch_recent_messages(
        service, max_results=get_settings().gmail_max_messages
    )
    for email in emails:
        if match_email_to_application(email, [job]) is None:
            continue
        body = ""
        if email.message_id:
            try:
                body = fetch_message_body(service, email.message_id)
            except Exception:  # noqa: BLE001 — snippet is enough context
                body = ""
        excerpt = f"{email.subject}\n{body or email.snippet}"[:_THREAD_CHAR_LIMIT]
        return _sender_address(email.sender), email.thread_id or "", excerpt
    return None


def _load_facts(facts_path: str) -> str:
    path = Path(facts_path)
    if not path.is_file():
        return "{}"
    return json.dumps(json.loads(path.read_text(encoding="utf-8")))[:_FACTS_CHAR_LIMIT]


def _prompt(job, application, draft_type, instructions, facts, thread) -> str:
    lines = [
        f"Email type: {draft_type} — {_TYPE_GUIDANCE[draft_type]}",
        f"Company: {job.company}",
        f"Role: {job.title}",
        f"Application status: {application.status if application else 'not applied yet'}",
        f"Job description excerpt:\n{(job.jd_text or '')[:_JD_CHAR_LIMIT]}",
        f"Candidate profile facts (the ONLY permitted source for claims):\n{facts}",
    ]
    if thread is not None:
        lines.append(
            "This email replies to an existing thread. Latest message from "
            f"{thread[0]}:\n{thread[2]}"
        )
    if instructions:
        lines.append(f"Additional instructions from the candidate: {instructions}")
    return "\n\n".join(lines)


def generate_email_draft(
    session: Session,
    job_id: int,
    draft_type: str,
    instructions: str | None = None,
    *,
    facts_path: str = FACTS_PATH,
    agent: Runner | None = None,
    service: Any | None = None,
) -> EmailDraft:
    if draft_type not in DRAFT_TYPES:
        raise ValueError(f"Unknown draft type: {draft_type}")
    job = get_job(session, job_id)
    if job is None:
        raise ValueError(f"Job #{job_id} not found")
    application = application_for_job(session, job_id)
    thread = _thread_context(service, job) if service is not None else None
    agent = agent or build_writer_agent()
    response = agent.run(
        _prompt(
            job, application, draft_type, instructions, _load_facts(facts_path), thread
        )
    )
    content = response.content
    if not isinstance(content, EmailDraftContent):
        content = EmailDraftContent.model_validate_json(str(content))
    return save_email_draft(
        session,
        EmailDraft(
            job_id=job_id,
            draft_type=draft_type,
            subject=content.subject,
            body=content.body,
            to_addr=thread[0] if thread else "",
            gmail_thread_id=(thread[1] or None) if thread else None,
        ),
    )
