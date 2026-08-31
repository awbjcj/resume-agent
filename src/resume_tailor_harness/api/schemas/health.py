from resume_tailor_harness.api.schemas.base import CamelModel


class HealthOut(CamelModel):
    status: str = "ok"
    mail_configured: bool
    google_oauth_configured: bool
