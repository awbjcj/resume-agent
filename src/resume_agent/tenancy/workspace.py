from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
    def gmail_token(self) -> Path:
        return self.root / "gmail_token.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def runs_root(self) -> Path:
        return self.root / "runs"

    @property
    def documents_dir(self) -> Path:
        return self.profile_dir / "documents"

    @property
    def scraper_recipes_dir(self) -> Path:
        return self.root / "scraper_recipes"

    @property
    def workday_facets_dir(self) -> Path:
        return self.root / "workday_facets"


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
        paths.scraper_recipes_dir,
        paths.workday_facets_dir,
        paths.root / "taxonomy",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    # Local import: settings_sections -> tenancy.paths -> tenancy.context ->
    # tenancy.workspace would otherwise be a module-load cycle.
    from resume_agent.settings_sections import SETTINGS_SECTIONS

    templates = Path(template_dir)
    if templates.is_dir():
        # Registry-driven, but seeded from the caller's template_dir -- never
        # from the repository root -- so provisioning does not silently no-op
        # when the shipped examples are not colocated with the package.
        for section in SETTINGS_SECTIONS:
            for entry in section.files:
                if "*" in entry or PurePosixPath(entry).parent != PurePosixPath(
                    "config"
                ):
                    continue
                name = PurePosixPath(entry).name
                example = templates / f"{name}.example"
                target = paths.config_dir / name
                if example.is_file() and not target.exists():
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
