from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from resume_agent.config import Settings
from resume_agent.setup.env_writer import parse_env

_PLATFORM_FIELDS = frozenset(
    {
        "api_token",
        "auth_password_hash",
        "auth_username",
        "cors_origins",
        "db_url",
        "session_secret",
    }
)
_PROVIDER_FIELDS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "deepseek": "deepseek_api_key",
}
_OVERLAY_FIELDS = frozenset(
    name
    for name, field in Settings.model_fields.items()
    if field.annotation is str and name not in _PLATFORM_FIELDS
)


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @property
    def db_file(self) -> Path:
        return self.root / "resume_agent.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_file.as_posix()}"

    @property
    def profile_dir(self) -> Path:
        return self.root / "profile"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def secrets_env(self) -> Path:
        return self.root / "secrets.env"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def runs_root(self) -> Path:
        return self.root / "runs"

    @property
    def documents_dir(self) -> Path:
        return self.profile_dir / "documents"


@dataclass(frozen=True)
class SettingsOverlay:
    settings: Settings
    own_key_providers: frozenset[str]


def workspace_paths(data_root: Path | str, user_id: str) -> WorkspacePaths:
    return WorkspacePaths(Path(data_root) / "users" / user_id)


def provision_workspace(
    data_root: Path | str,
    user_id: str,
    *,
    template_dir: Path | str = Path("config"),
) -> WorkspacePaths:
    paths = workspace_paths(data_root, user_id)
    for directory in (
        paths.documents_dir,
        paths.config_dir,
        paths.output_dir,
        paths.runs_root,
        paths.root / "scraper_recipes",
        paths.root / "workday_facets",
        paths.root / "taxonomy",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    templates = Path(template_dir)
    if templates.is_dir():
        for example in sorted(templates.glob("*.example")):
            target = paths.config_dir / example.name.removesuffix(".example")
            if not target.exists():
                shutil.copyfile(example, target)
    return paths


def effective_settings(base: Settings, paths: WorkspacePaths) -> SettingsOverlay:
    updates: dict[str, object] = {"db_url": paths.db_url}
    if paths.secrets_env.is_file():
        values = parse_env(paths.secrets_env.read_text(encoding="utf-8"))
        for env_name, value in values.items():
            field_name = env_name.lower()
            if field_name in _OVERLAY_FIELDS and value:
                updates[field_name] = value
    settings = base.model_copy(update=updates)
    own_keys = frozenset(
        provider
        for provider, field_name in _PROVIDER_FIELDS.items()
        if getattr(settings, field_name, "")
        and getattr(settings, field_name, "") != getattr(base, field_name, "")
    )
    return SettingsOverlay(settings=settings, own_key_providers=own_keys)
