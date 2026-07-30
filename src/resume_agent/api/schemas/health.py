from resume_agent.api.schemas.base import CamelModel


class HealthOut(CamelModel):
    status: str = "ok"
    mail_configured: bool
    google_oauth_configured: bool
