import uuid
from datetime import datetime, timezone
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from resume_tailor_harness.api import attempts, auth, auth_codes
from resume_tailor_harness.api.deps import get_settings_dep
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.password_policy import validate_password
from resume_tailor_harness.api.routers.auth_register import (
    client_ip,
    rate_event,
    send_or_fail,
    system_engine,
)
from resume_tailor_harness.api.schemas.auth import MeResponse
from resume_tailor_harness.api.schemas.auth_email import (
    CodeSentResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from resume_tailor_harness.config import Settings
from resume_tailor_harness.mail import messages
from resume_tailor_harness.tenancy.system_db import PasswordResetCode, User


router = APIRouter(prefix="/auth/password", tags=["auth"])


@router.post("/forgot", status_code=202, response_model=CodeSentResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    rate_event(request, body.email)
    with Session(system_engine(request)) as session:
        user = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        # Do code-hash work in both branches so account existence is not exposed
        # by the local CPU profile. Delivery remains intentionally asynchronous
        # from the response contract.
        code = auth_codes.generate_code()
        code_hash = auth_codes.hash_code(code, settings)
        if user is None or user.disabled_at is not None:
            return CodeSentResponse()
        session.execute(
            delete(PasswordResetCode).where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.pending_email.is_(None),
            )
        )
        session.add(
            PasswordResetCode(
                id=uuid.uuid4().hex[:12],
                user_id=user.id,
                code_hash=code_hash,
                expires_at=auth_codes.expires_at(),
            )
        )
        session.flush()
        send_or_fail(request, body.email, messages.reset_code(code))
        session.commit()
    return CodeSentResponse()


@router.post("/reset", response_model=MeResponse)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    rate_event(request, body.email)
    engine = system_engine(request)
    with Session(engine) as session:
        user = (
            session.execute(select(User).where(User.email == body.email))
            .scalars()
            .first()
        )
        row = None
        if user is not None:
            row = (
                session.execute(
                    select(PasswordResetCode).where(
                        PasswordResetCode.user_id == user.id,
                        PasswordResetCode.pending_email.is_(None),
                        PasswordResetCode.consumed_at.is_(None),
                    )
                )
                .scalars()
                .first()
            )
        if user is None or row is None:
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        verdict = auth_codes.check_code(
            cast(auth_codes.CodeRow, row), body.code, settings
        )
        if verdict is not auth_codes.CodeVerdict.OK:
            if verdict is auth_codes.CodeVerdict.EXHAUSTED:
                session.delete(row)
            session.commit()
            raise ApiException(400, "CODE_INVALID", "That code is not valid")
        validate_password(
            body.new_password,
            email=body.email,
            display_name=user.username,
            checker=request.app.state.breach_checker,
        )
        if user.password_hash and auth.verify_password(
            body.new_password, user.password_hash
        ):
            raise ApiException(
                400, "PASSWORD_WEAK", "Choose a password different from the current one"
            )
        user.password_hash = auth.hash_password(body.new_password)
        user.session_epoch += 1
        attempts.clear_lockout(user)
        row.consumed_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(user)
        identity = (
            user.id,
            user.username,
            user.session_epoch,
            user.email_verified_at,
            user.google_sub,
            user.role,
        )
    attempts.reset(engine, email=body.email, ip=client_ip(request))
    user_id, username, epoch, verified, google_sub, role = identity
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(settings, user_id=user_id, epoch=epoch),
    )
    notice = messages.password_changed(settings.app_base_url)
    request.app.state.mailer.notify(
        to=body.email, subject=notice.subject, body=notice.body
    )
    return MeResponse(
        username=username,
        email=body.email,
        email_verified=verified is not None,
        needs_email=False,
        google_linked=google_sub is not None,
        role=cast(Literal["admin", "user"], role),
        auth_required=True,
    )
