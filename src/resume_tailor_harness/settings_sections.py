"""The single enumeration of user-customizable settings.

Every surface that needs to answer "what can a user customize" reads this
table: the settings bundle (export and import), the reset-to-default controls,
and workspace provisioning. Adding a setting is one row here and it appears in
all three for free.

This table is an ALLOWLIST, and that is load-bearing. It spans the workspace
root, whose other occupants include secrets.env, gmail_token.json,
resume_tailor_harness.db, and config/gmail_credentials.json (an OAuth client secret). A
file not named here can never leave a workspace inside a bundle, nor enter one
from an imported bundle.

Paths are written in the canonical relative form tenancy/paths.py already
speaks -- "config/connectors.yaml", "data/profile/overrides.yaml". One string
serves as the live-file key (via resolve_tenant_path), the archive arcname, and
the lookup for a shipped default.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from resume_tailor_harness.tenancy.paths import resolve_tenant_path

# src/resume_tailor_harness/settings_sections.py -> resume_tailor_harness -> src -> repository
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
    SettingsSection("agent_guidance", "Agent prompts", ("config/agent_guidance.yaml",)),
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


def is_customized(section: SettingsSection) -> bool:
    """True when the user has content here they would not want silently lost.

    An absent file that has a shipped default counts as NOT customized: there
    is nothing to lose, and reset would only put the default back. The badge
    answers "do you have changes worth exporting", not "does this byte-match a
    pristine install".
    """
    for entry in section.files:
        default = default_path(entry)
        paths = live_paths(entry)
        if default is None:
            if paths:
                return True
            continue
        if paths and paths[0].read_bytes() != default.read_bytes():
            return True
    return False


def seedable_entries() -> tuple[str, ...]:
    """Entries a fresh workspace is provisioned with.

    Exactly the entries that ship a `.example`. Provisioning and resetting
    therefore cannot drift: both mean "put the shipped default here".
    """
    return tuple(
        entry
        for section in SETTINGS_SECTIONS
        for entry in section.files
        if default_path(entry) is not None
    )


def reset_section(section: SettingsSection) -> None:
    """Restore one section to defaults.

    The rule is policy-free and identical to fresh provisioning: copy the
    shipped `.example` when the repository ships one, otherwise delete the
    file. The five sections that ship no example -- agent guidance, custom
    templates, and the three correction ledgers -- all land on their true
    defaults by being removed.
    """
    for entry in section.files:
        for path in live_paths(entry):
            path.unlink(missing_ok=True)
        default = default_path(entry)
        if default is None:
            continue
        target = resolve_tenant_path(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default, target)
