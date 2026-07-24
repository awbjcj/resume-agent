"""The single enumeration of user-customizable settings.

Every surface that needs to answer "what can a user customize" reads this
table: the settings bundle (export and import), the reset-to-default controls,
and workspace provisioning. Adding a setting is one row here and it appears in
all three for free.

This table is an ALLOWLIST, and that is load-bearing. It spans the workspace
root, whose other occupants include secrets.env, gmail_token.json,
resume_agent.db, and config/gmail_credentials.json (an OAuth client secret). A
file not named here can never leave a workspace inside a bundle, nor enter one
from an imported bundle.

Paths are written in the canonical relative form tenancy/paths.py already
speaks -- "config/connectors.yaml", "data/profile/overrides.yaml". One string
serves as the live-file key (via resolve_tenant_path), the archive arcname, and
the lookup for a shipped default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from resume_agent.tenancy.paths import resolve_tenant_path

# src/resume_agent/settings_sections.py -> resume_agent -> src -> repository
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SettingsSection:
    """One resettable, transferable unit of user customization."""

    id: str
    label: str
    files: tuple[str, ...]


SETTINGS_SECTIONS: tuple[SettingsSection, ...] = (
    SettingsSection("sources", "Company sources", ("config/connectors.yaml",)),
    SettingsSection("search", "Search", ("config/search.yaml",)),
    SettingsSection(
        "review",
        "Review panel",
        ("config/review.yaml", "config/review_deep.yaml"),
    ),
    SettingsSection(
        "agent_guidance", "Agent prompts", ("config/agent_guidance.yaml",)
    ),
    SettingsSection("style_guide", "Style guide", ("config/style_guide.md",)),
    SettingsSection("render", "Rendering", ("config/render.yaml",)),
    SettingsSection(
        "templates", "Custom resume templates", ("config/templates/*.typ",)
    ),
    SettingsSection("prune", "Pruning", ("config/prune.yaml",)),
    SettingsSection(
        "profile_sources", "Profile sources", ("config/profile_sources.yaml",)
    ),
    SettingsSection(
        "skill_overrides", "Skill overrides", ("data/profile/overrides.yaml",)
    ),
    SettingsSection(
        "skill_groups",
        "Skill group corrections",
        ("data/profile/group_corrections.json",),
    ),
    SettingsSection(
        "taxonomy",
        "Taxonomy corrections",
        ("data/taxonomy/taxonomy_corrections.json",),
    ),
)

SECTIONS_BY_ID: dict[str, SettingsSection] = {
    section.id: section for section in SETTINGS_SECTIONS
}


def section_for(section_id: str) -> SettingsSection | None:
    return SECTIONS_BY_ID.get(section_id)


def live_paths(entry: str) -> list[Path]:
    """Existing workspace files this entry names, sorted by name."""
    resolved = resolve_tenant_path(entry)
    if "*" in entry:
        return sorted(
            (path for path in resolved.parent.glob(resolved.name) if path.is_file()),
            key=lambda path: path.name,
        )
    return [resolved] if resolved.is_file() else []


def default_path(entry: str) -> Path | None:
    """The shipped `.example` for an entry, when the repository ships one.

    Globs never have a default: a directory of user uploads resets by being
    emptied, not by being repopulated.
    """
    if "*" in entry:
        return None
    candidate = _REPOSITORY_ROOT / f"{entry}.example"
    return candidate if candidate.is_file() else None


def arcname_for(entry: str, path: Path) -> str:
    """Archive member name for a live file matched by `entry`."""
    return str(PurePosixPath(entry).parent / path.name)
