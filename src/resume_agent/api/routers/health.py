from fastapi import APIRouter, Request

from resume_agent.api.schemas.health import HealthOut
from resume_agent.mail.mailer import mail_configured

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    settings = request.app.state.settings
    return HealthOut(
        status="ok",
        mail_configured=mail_configured(settings),
        google_oauth_configured=bool(
            settings.google_oauth_client_id and settings.google_oauth_client_secret
        ),
    )

