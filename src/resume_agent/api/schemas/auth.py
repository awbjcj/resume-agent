from resume_agent.api.schemas.base import CamelModel


class LoginRequest(CamelModel):
    username: str
    password: str


class MeResponse(CamelModel):
    username: str | None = None
    auth_required: bool = False
