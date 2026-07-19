"""Email writer endpoints: generate (202 run), list, save to Gmail drafts."""

from __future__ import annotations

import base64
from email.message import EmailMessage as MimeMessage
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.email_drafts import EmailDraftOut, EmailDraftRequest
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session as open_session
from resume_agent.gmail import auth as gmail_auth
from resume_agent.gmail.errors import (
    GmailApiError,
    GmailError,
    GmailNotConnected,
    GmailScopeMissing,
)
from resume_agent.services.email_writer import DRAFT_TYPES, generate_email_draft
from resume_agent.tracking.repository import (
    email_drafts_for_job,
    get_email_draft,
    get_job,
    save_email_draft,
)

router = APIRouter()


def _service_or_none() -> Any | None:
    """Gmail service for thread context, or None when not connected."""
    try:
        return gmail_auth.build_service()
    except GmailNotConnected:
        return None


def _compose_service(request: Request) -> Any:
    """Draft-capable Gmail service, or a typed 409."""
    from resume_agent.api.deps import get_data_dir

    data_dir = get_data_dir(request)
    creds = gmail_auth.load_credentials(data_dir)
    if creds is None:
        raise GmailNotConnected("Connect Gmail in Settings to save drafts")
    if not gmail_auth.has_compose(creds):
        raise GmailScopeMissing("Reconnect Gmail to grant draft permission")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def _gmail_409(error: GmailError) -> ApiException:
    return ApiException(409, error.code, str(error))


@router.post("/jobs/{job_id}/email-draft", response_model=RunOut, status_code=202)
def launch_email_draft(
    job_id: int,
    body: EmailDraftRequest,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    if body.draft_type not in DRAFT_TYPES:
        raise ApiException(400, "INVALID_DRAFT_TYPE", f"Unknown type {body.draft_type}")
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    from resume_agent.api.routers.runs import _engine
    from resume_agent.api.runs.launch import launch

    engine = _engine(request)
    draft_type, instructions = body.draft_type, body.instructions

    def work(reporter):
        reporter.begin(1, "Drafting email")
        service = _service_or_none()
        with open_session(engine) as worker_session:
            draft = generate_email_draft(
                worker_session,
                job_id,
                draft_type,
                instructions,
                service=service,
            )
        reporter.step(1)
        return {"draftId": draft.id}

    return launch(
        mgr,
        "emailDraft",
        work,
        singleton_key=f"emailDraft:{job_id}",
        meta={"jobId": job_id},
    )


@router.get("/jobs/{job_id}/email-drafts", response_model=list[EmailDraftOut])
def list_email_drafts(job_id: int, session: Session = Depends(get_session)):
    return [
        EmailDraftOut.model_validate(d) for d in email_drafts_for_job(session, job_id)
    ]


@router.post("/email-drafts/{draft_id}/save", response_model=EmailDraftOut)
def save_to_gmail(
    draft_id: int, request: Request, session: Session = Depends(get_session)
):
    draft = get_email_draft(session, draft_id)
    if draft is None:
        raise ApiException(404, "NOT_FOUND", f"Draft #{draft_id} not found")
    try:
        service = _compose_service(request)
    except GmailError as error:
        raise _gmail_409(error) from error
    mime = MimeMessage()
    if draft.to_addr:
        mime["To"] = draft.to_addr
    mime["Subject"] = draft.subject
    mime.set_content(draft.body)
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    message: dict[str, Any] = {"raw": raw}
    if draft.gmail_thread_id:
        message["threadId"] = draft.gmail_thread_id
    payload = {"message": message}
    drafts_api = service.users().drafts()
    try:
        if draft.gmail_draft_id:
            response = drafts_api.update(
                userId="me", id=draft.gmail_draft_id, body=payload
            ).execute()
        else:
            response = drafts_api.create(userId="me", body=payload).execute()
    except Exception as exc:  # noqa: BLE001 — surface a typed Gmail API failure
        raise ApiException(
            502, GmailApiError.code, "Failed to save the draft to Gmail"
        ) from exc
    draft.gmail_draft_id = response.get("id")
    draft.state = "saved"
    return EmailDraftOut.model_validate(save_email_draft(session, draft))
