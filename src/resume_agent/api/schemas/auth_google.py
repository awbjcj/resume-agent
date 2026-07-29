from resume_agent.api.schemas.base import CamelModel


class GoogleStartOut(CamelModel):
    auth_url: str
