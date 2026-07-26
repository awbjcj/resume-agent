from dataclasses import dataclass, field
from typing import cast

from resume_agent.config import Settings


def _tier_default(name: str) -> str:
    """Seed a tier from ``Settings`` so the wizard cannot drift behind it.

    These were literals, and ``mid_model`` had already fallen a generation
    behind (``claude-sonnet-4-6`` vs ``claude-sonnet-5``) -- a new user would
    have been set up on a stale model with nothing to flag it.
    """
    return cast(str, Settings.model_fields[name].default)


@dataclass
class WizardState:
    """Every answer the wizard collects. Screens bind to this; cores read it."""

    # secrets (→ .env)
    anthropic_api_key: str = ""
    github_token: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    db_url: str = "sqlite:///data/resume_agent.db"
    cheap_model: str = field(default_factory=lambda: _tier_default("cheap_model"))
    mid_model: str = field(default_factory=lambda: _tier_default("mid_model"))
    premium_model: str = field(default_factory=lambda: _tier_default("premium_model"))

    # profile sources (→ profile_sources.yaml)
    resume_path: str = ""
    github_username: str = ""

    # search (→ search.yaml)
    keywords: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_policy: str = "any"
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False

    # connectors (→ connectors.yaml)
    greenhouse_enabled: bool = False
    greenhouse_boards: list[dict] = field(default_factory=list)
    adzuna_enabled: bool = False
    adzuna_country: str = "us"
    remoteok_enabled: bool = False
    linkedin_enabled: bool = False

    def managed_env(self) -> dict[str, str]:
        """Map state secrets to .env keys, dropping empty values.

        Note: ``openai_api_key`` and ``linkedin_user_data_dir`` are deliberately
        NOT managed here — they are preserved by ``merge_env`` if already set.
        """
        candidates = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "GITHUB_TOKEN": self.github_token,
            "ADZUNA_APP_ID": self.adzuna_app_id,
            "ADZUNA_APP_KEY": self.adzuna_app_key,
            "LINKEDIN_EMAIL": self.linkedin_email,
            "LINKEDIN_PASSWORD": self.linkedin_password,
            "DB_URL": self.db_url,
            "CHEAP_MODEL": self.cheap_model,
            "MID_MODEL": self.mid_model,
            "PREMIUM_MODEL": self.premium_model,
        }
        return {k: v for k, v in candidates.items() if v}
