import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth, auth_codes
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import validate_password
from resume_agent.api.schemas.auth import MeResponse
from resume_agent.api.schemas.auth_email import (
    CodeSentResponse,
    RegisterRequest,
    ResendCodeRequest,
    VerifyEmailRequest,
)
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.mail.mailer import MailDeliveryError
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.quotas import assign_new_member
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, PendingRegistration, User
from resume_agent.tenancy.workspace import provision_workspace, workspace_paths


router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def system_engine(request: Request):
    engine = getattr(request.app.state, "system_engine", None)
    if engine is None:
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Multi-user auth is required")
    return engine


def rate_event(
    request: Request, email: str, scopes: frozenset[str] = attempts.DEFAULT_SCOPES
) -> None:
    if not attempts.consume(
        system_engine(request), email=email, ip=client_ip(request), scopes=scopes
    ):
        raise ApiException(429, "RATE_LIMITED", "Too many attempts; try again later")


def send_or_fail(request: Request, to: str, message: messages.Message) -> None:
    try:
        request.app.state.mailer.send(to=to, subject=message.subject, body=message.body)
    except MailDeliveryError as error:
        raise ApiException(503, "MAIL_UNAVAILABLE", "Could not send email") from error


def _invite_error(invite: InviteCode | None, now: datetime) -> ApiException | None:
    if invite is None or invite.revoked_at is not None:
        return ApiException(400, "INVITE_INVALID", "Unknown invitation code")
    expiry = invite.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= now:
        return ApiException(400, "INVITE_EXPIRED", "Invitation code expired")
    if invite.used_at is not None:
        return ApiException(400, "INVITE_USED", "Invitation code already used")
    return None


def _available_username(session: Session, preferred: str, user_id: str) -> str:
    base = preferred.strip()[:64] or f"user-{user_id}"
    if session.execute(select(User.id).where(User.username == base)).scalar() is None:
        return base
    suffix = f"-{user_id[:6]}"
    return f"{base[: 64 - len(suffix)]}{suffix}"


@router.post("/register", status_code=202, response_model=CodeSentResponse)
def register(
    body: RegisterRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    if settings.registration_mode == "closed":
        raise ApiException(403, "REGISTRATION_CLOSED", "Registration is closed")
    rate_event(request, body.email)
    engine = system_engine(request)
    if not attempts.consume_global_signup(
        engine,
        limit=settings.global_daily_signup_limit,
    ):
        raise ApiException(429, "RATE_LIMITED", "Registration capacity reached")
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        invite_hash = hash_secret(body.invite_code) if body.invite_code else ""
        if settings.registration_mode == "invite":
            invite = (
                session.execute(
                    select(InviteCode).where(InviteCode.code_hash == invite_hash)
                )
                .scalars()
                .first()
            )
            error = _invite_error(invite, now)
            if error:
                raise error
        validate_password(
            body.password,
            email=body.email,
            display_name=body.display_name,
            checker=request.app.state.breach_checker,
        )
        existing = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        if existing is not None:
            # Match the expensive password-hash work of the unknown-address path.
            auth.hash_password(body.password)
            notice = messages.signup_on_existing(settings.app_base_url)
            request.app.state.mailer.notify(
                to=body.email, subject=notice.subject, body=notice.body
            )
            return CodeSentResponse()
        code = auth_codes.generate_code()
        session.execute(
            delete(PendingRegistration).where(PendingRegistration.email == body.email)
        )
        session.add(
            PendingRegistration(
                id=uuid.uuid4().hex[:12],
                email=body.email,
                password_hash=auth.hash_password(body.password),
                display_name=body.display_name,
                invite_code_hash=invite_hash
                if settings.registration_mode == "invite"
                else "",
                code_hash=auth_codes.hash_code(code, settings),
                expires_at=auth_codes.expires_at(now),
            )
        )
        session.flush()
        send_or_fail(request, body.email, messages.verification_code(code))
        session.commit()
    return CodeSentResponse()


@router.post("/verify-email", response_model=MeResponse)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    if settings.registration_mode == "closed":
        raise ApiException(403, "REGISTRATION_CLOSED", "Registration is closed")
    rate_event(request, body.email)
    engine = system_engine(request)
    invalid = False
    identity: tuple[str, str, str, int] | None = None
    workspace: Path | None = None
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        pending = (
            session.execute(
                select(PendingRegistration).where(
                    PendingRegistration.email == body.email
                )
            )
            .scalars()
            .first()
        )
        if pending is None:
            session.rollback()
            invalid = True
        else:
            verdict = auth_codes.check_code(
                cast(auth_codes.CodeRow, pending), body.code, settings
            )
            if verdict is not auth_codes.CodeVerdict.OK:
                if verdict is auth_codes.CodeVerdict.EXHAUSTED:
                    session.delete(pending)
                session.commit()
                invalid = True
        if not invalid and pending is not None:
            now = datetime.now(timezone.utc)
            invite = None
            if pending.invite_code_hash:
                invite = (
                    session.execute(
                        select(InviteCode).where(
                            InviteCode.code_hash == pending.invite_code_hash
                        )
                    )
                    .scalars()
                    .first()
                )
                error = _invite_error(invite, now)
                if error:
                    session.rollback()
                    raise error
            open_signup = not pending.invite_code_hash
            user_id = new_user_id()
            user = User(
                id=user_id,
                username=_available_username(
                    session,
                    pending.display_name or body.email.partition("@")[0],
                    user_id,
                ),
                email=body.email,
                email_verified_at=now,
                password_hash=pending.password_hash,
                role="user",
                shared_key_access=(
                    settings.open_signup_shared_keys if open_signup else True
                ),
                weekly_token_budget=(
                    settings.open_signup_weekly_token_budget if open_signup else None
                ),
                max_active_jobs=(
                    settings.open_signup_max_active_jobs if open_signup else None
                ),
                max_concurrent_runs=(
                    settings.open_signup_max_concurrent_runs if open_signup else None
                ),
            )
            session.add(user)
            assign_new_member(session, user.id, now=now)
            if invite is not None:
                invite.used_by = user.id
                invite.used_at = now
            session.delete(pending)
            try:
                session.flush()
            except IntegrityError as error:
                session.rollback()
                raise ApiException(
                    409, "EMAIL_TAKEN", "That email is already in use"
                ) from error
            workspace = workspace_paths(request.app.state.data_dir, user.id).root
            try:
                provision_workspace(
                    request.app.state.data_dir,
                    user.id,
                    template_dir=request.app.state.template_config_dir,
                )
                session.commit()
            except Exception:
                session.rollback()
                if workspace.is_dir():
                    shutil.rmtree(workspace, ignore_errors=True)
                raise
            session.refresh(user)
            identity = (user.id, user.username, user.password_hash, user.session_epoch)
    if invalid:
        raise ApiException(400, "CODE_INVALID", "That code is not valid")
    assert identity is not None
    user_id, username, password_hash, epoch = identity
    attempts.reset(engine, email=body.email, ip=client_ip(request))
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings, user_id=user_id, password_hash=password_hash, epoch=epoch
        ),
    )
    return MeResponse(
        username=username,
        email=body.email,
        email_verified=True,
        role="user",
        auth_required=True,
    )


@router.post("/resend-code", status_code=202, response_model=CodeSentResponse)
def resend_code(
    body: ResendCodeRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    rate_event(request, body.email, attempts.RESEND_ONLY)
    with Session(system_engine(request)) as session:
        pending = (
            session.execute(
                select(PendingRegistration).where(
                    PendingRegistration.email == body.email
                )
            )
            .scalars()
            .first()
        )
        if pending is None:
            return CodeSentResponse()
        code = auth_codes.generate_code()
        pending.code_hash = auth_codes.hash_code(code, settings)
        pending.expires_at = auth_codes.expires_at()
        pending.attempts = 0
        send_or_fail(request, body.email, messages.verification_code(code))
        session.commit()
    return CodeSentResponse()
