"""Root-confined, hash-verified local career skill registry."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from resume_agent.career_skills.models import (
    AgentFamily,
    SkillCapability,
    SkillManifest,
    SkillManifestEntry,
    SkillRef,
)

MAX_SKILL_BYTES = 256 * 1024
_FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---(?:\s*\n|\Z)", re.DOTALL)


class SkillUnavailable(RuntimeError):
    """A requested skill is unavailable without guessing a substitute."""

    code = "CAPABILITY_UNAVAILABLE"

    def __init__(self, code: str, skill_name: str, reason: str) -> None:
        self.code = code
        self.skill_name = skill_name
        self.reason = reason
        super().__init__(f"{skill_name}: {reason}")


@dataclass(frozen=True)
class VerifiedSkill:
    ref: SkillRef
    directory: Path
    uses: frozenset[str]


@dataclass(frozen=True)
class _EntryState:
    entry: SkillManifestEntry
    description: str
    verified: VerifiedSkill | None
    unavailable_reason: str | None = None


def _canonical_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _manifest_relative_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("manifest path must stay below the configured skill root")
    parts = path.parts
    if parts and parts[0].casefold() == root.name.casefold():
        parts = parts[1:]
    if not parts:
        raise ValueError("manifest path is empty")
    return Path(*parts)


def _confined_skill_path(root: Path, value: str) -> Path:
    relative = _manifest_relative_path(root, value)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("manifest path contains a symlink")
    resolved = cursor.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("manifest path escapes the configured skill root")
    return resolved


def _frontmatter(text: str, expected_name: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError("SKILL.md has no frontmatter")
    data = yaml.safe_load(match.group("body")) or {}
    if not isinstance(data, dict) or data.get("name") != expected_name:
        raise ValueError("SKILL.md frontmatter name does not match the manifest key")
    description = data.get("description", "")
    return str(data.get("name")), str(description) if description else ""


class CareerSkillRegistry:
    def __init__(
        self,
        root: Path,
        manifest_path: Path,
        manifest: SkillManifest | None,
        states: dict[str, _EntryState],
        manifest_error: str | None = None,
    ) -> None:
        self.root = root
        self.manifest_path = manifest_path
        self.manifest = manifest
        self._states = states
        self._manifest_error = manifest_error

    @classmethod
    def from_settings(cls, settings: Any) -> CareerSkillRegistry:
        root = Path(settings.career_skill_root)
        manifest = Path(settings.career_skill_manifest)
        # The shipped defaults are repository-relative. Resolve them from the
        # source tree when a caller changes cwd (tests, CLI wrappers, and
        # installed development tools), but preserve an explicitly configured
        # or partially present path so readiness still reports the defect.
        if (
            root == Path("skills")
            and manifest == Path("skills-lock.json")
            and not root.exists()
            and not manifest.exists()
        ):
            source_root = Path(__file__).resolve().parents[3]
            candidate_root = source_root / root
            candidate_manifest = source_root / manifest
            if candidate_root.is_dir() and candidate_manifest.is_file():
                root, manifest = candidate_root, candidate_manifest
        return registry_for_paths(root, manifest)

    @classmethod
    def from_paths(
        cls, root: Path | str, manifest: Path | str
    ) -> CareerSkillRegistry:
        resolved_root = Path(root).expanduser().resolve(strict=False)
        resolved_manifest = Path(manifest).expanduser().resolve(strict=False)
        return cls._load(resolved_root, resolved_manifest)

    @classmethod
    def _load(cls, root: Path, manifest_path: Path) -> CareerSkillRegistry:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = SkillManifest.model_validate(payload)
        except Exception as exc:  # manifest failures are a readiness defect, not a 500
            return cls(root, manifest_path, None, {}, f"invalid skill manifest: {exc}")

        states: dict[str, _EntryState] = {}
        claimed_paths: dict[Path, str] = {}
        for name, entry in manifest.skills.items():
            description = ""
            verified: VerifiedSkill | None = None
            reason: str | None = None
            try:
                skill_file = _confined_skill_path(root, entry.skill_path)
                if skill_file in claimed_paths:
                    raise ValueError(
                        f"skill path is already registered by {claimed_paths[skill_file]}"
                    )
                claimed_paths[skill_file] = name
                if skill_file.name != "SKILL.md":
                    raise ValueError("manifest must point to SKILL.md")
                if not skill_file.is_file() or skill_file.is_symlink():
                    raise ValueError("SKILL.md must be a regular non-symlink file")
                with skill_file.open("rb") as handle:
                    raw = handle.read(MAX_SKILL_BYTES + 1)
                if len(raw) > MAX_SKILL_BYTES:
                    raise ValueError(f"SKILL.md exceeds {MAX_SKILL_BYTES} bytes")
                canonical = _canonical_bytes(raw)
                text = canonical.decode("utf-8")
                _, description = _frontmatter(text, name)
                observed = hashlib.sha256(canonical).hexdigest()
                if observed != entry.computed_hash:
                    raise ValueError("SKILL.md hash does not match the manifest")
                verified = VerifiedSkill(
                    ref=SkillRef(
                        name=name,
                        version=entry.local_version,
                        sha256=observed,
                        family=entry.family,
                    ),
                    directory=skill_file.parent,
                    uses=entry.uses,
                )
            except (OSError, UnicodeError, ValueError) as exc:
                reason = str(exc)
            states[name] = _EntryState(
                entry=entry,
                description=description,
                verified=verified,
                unavailable_reason=reason,
            )
        return cls(root, manifest_path, manifest, states)

    def all(self) -> list[VerifiedSkill]:
        return [state.verified for state in self._states.values() if state.verified]

    def capabilities(self, *, include_internal: bool = True) -> list[SkillCapability]:
        rows: list[SkillCapability] = []
        for name, state in sorted(self._states.items()):
            if not include_internal and state.entry.visibility != "public":
                continue
            rows.append(
                SkillCapability(
                    name=name,
                    description=state.description,
                    family=state.entry.family,
                    uses=sorted(state.entry.uses),
                    is_available=state.verified is not None,
                    unavailable_reason=state.unavailable_reason,
                )
            )
        if self._manifest_error:
            rows.append(
                SkillCapability(
                    name="__manifest__",
                    description="The approved skill manifest could not be verified.",
                    family=AgentFamily.INTERNAL_PROFILE,
                    uses=[],
                    is_available=False,
                    unavailable_reason=self._manifest_error,
                )
            )
        return rows

    def public_capabilities(self) -> list[SkillCapability]:
        return self.capabilities(include_internal=False)

    def require(self, name: str, *, family: AgentFamily, use: str) -> VerifiedSkill:
        state = self._states.get(name)
        if state is None:
            raise SkillUnavailable("CAPABILITY_UNAVAILABLE", name, "skill is not in the manifest")
        if state.verified is None:
            raise SkillUnavailable(
                "CAPABILITY_UNAVAILABLE", name, state.unavailable_reason or "skill is unavailable"
            )
        if state.entry.family != family:
            raise SkillUnavailable(
                "CAPABILITY_UNAVAILABLE", name, f"skill belongs to {state.entry.family.value}"
            )
        if use not in state.entry.uses:
            raise SkillUnavailable("CAPABILITY_UNAVAILABLE", name, f"use is not allowed: {use}")
        return state.verified


def resolve_skill(
    skill: VerifiedSkill | None,
    *,
    name: str,
    family: AgentFamily,
    use: str,
) -> VerifiedSkill:
    """Validate an injected skill or resolve the approved default skill."""
    if skill is not None:
        if skill.ref.name != name or skill.ref.family != family or use not in skill.uses:
            raise SkillUnavailable(
                "CAPABILITY_UNAVAILABLE",
                name,
                "provided skill does not match the fixed agent route",
            )
        return skill
    from resume_agent.config import get_settings

    return CareerSkillRegistry.from_settings(get_settings()).require(
        name, family=family, use=use
    )


@lru_cache(maxsize=16)
def registry_for_paths(root: Path | str, manifest: Path | str) -> CareerSkillRegistry:
    root_path = Path(root).expanduser().resolve(strict=False)
    manifest_path = Path(manifest).expanduser().resolve(strict=False)
    return CareerSkillRegistry._load(root_path, manifest_path)
