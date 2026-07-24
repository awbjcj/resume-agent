"""Settings-only bundle: export, preview, and section-level import.

A bundle carries exactly the sections declared in settings_sections.py --
never the database, the derived profile corpus, or any credential. Import
replaces the sections a bundle names and leaves every other section untouched,
so a bundle can add or replace settings but never clear them. Clearing is what
reset is for.
"""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml

from resume_agent.api.schemas.config import ProfileConfigDoc
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.profile.group_corrections import GroupCorrections
from resume_agent.profile.matrix import load_overrides
from resume_agent.prompts.guidance import MAX_GUIDANCE_CHARS
from resume_agent.render.render_config import RenderConfig
from resume_agent.render.templates import validate_custom_stem
from resume_agent.services.backup import UnsafeArchiveError, _extract_validated
from resume_agent.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    arcname_for,
    live_paths,
)
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.tracking.prune_config import PruneConfig

BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"


class InvalidBundleError(ValueError):
    """The upload is not a readable settings bundle."""


class UnsupportedBundleVersionError(InvalidBundleError):
    """The bundle was written by a version this build does not understand."""


def export_settings_bundle(out_dir: Path) -> Path:
    """Write a tar.gz of every populated section into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC)
    archive = out_dir / f"resume-agent-settings-{stamp.date().isoformat()}.tar.gz"

    sections: list[str] = []
    members: list[tuple[str, Path]] = []
    for section in SETTINGS_SECTIONS:
        found = [
            (arcname_for(entry, path), path)
            for entry in section.files
            for path in live_paths(entry)
        ]
        if found:
            sections.append(section.id)
            members.extend(found)

    manifest = json.dumps(
        {
            "version": BUNDLE_VERSION,
            "exportedAt": stamp.isoformat(),
            "sections": sections,
        },
        indent=2,
    ).encode("utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        info.mtime = int(stamp.timestamp())
        tar.addfile(info, io.BytesIO(manifest))
        for arcname, path in members:
            tar.add(path, arcname=arcname)
    return archive


@dataclass(frozen=True)
class BundleManifest:
    version: int
    exported_at: str
    sections: tuple[str, ...]
    unknown_sections: tuple[str, ...]


def _yaml_doc(model: type) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    return check


def _check_guidance(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError("agent guidance must be a mapping")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("agent guidance entries must be strings")
        if len(value.strip()) > MAX_GUIDANCE_CHARS:
            raise ValueError(f"guidance for {key!r} exceeds {MAX_GUIDANCE_CHARS}")


def _check_text(path: Path) -> None:
    path.read_text(encoding="utf-8")


def _check_group_corrections(path: Path) -> None:
    # NOT load_group_corrections: it swallows ValueError and returns an empty
    # ledger, which would let a truncated file import as "no corrections".
    GroupCorrections.model_validate_json(path.read_text(encoding="utf-8"))


def _check_taxonomy_corrections(path: Path) -> None:
    # NOT load_taxonomy_corrections, for the same reason. Semantic
    # unfamiliarity is fine -- dangling references are inert by design and are
    # dropped at read time by sanitize_taxonomy_corrections.
    TaxonomyCorrections.model_validate(json.loads(path.read_text(encoding="utf-8")))


_VALIDATORS: dict[str, Callable[[Path], None]] = {
    "config/connectors.yaml": _yaml_doc(ConnectorsConfig),
    "config/search.yaml": _yaml_doc(SearchConfig),
    "config/review.yaml": _yaml_doc(ReviewConfig),
    "config/review_deep.yaml": _yaml_doc(ReviewConfig),
    "config/render.yaml": _yaml_doc(RenderConfig),
    "config/prune.yaml": _yaml_doc(PruneConfig),
    "config/profile_sources.yaml": _yaml_doc(ProfileConfigDoc),
    "config/agent_guidance.yaml": _check_guidance,
    "config/style_guide.md": _check_text,
    "data/profile/overrides.yaml": lambda path: load_overrides(path),
    "data/profile/group_corrections.json": _check_group_corrections,
    "data/taxonomy/taxonomy_corrections.json": _check_taxonomy_corrections,
}


def validate_member(arcname: str, path: Path) -> None:
    """Parse a staged member strictly; raise InvalidBundleError on corruption.

    `_extract_validated` already rejects `..` in a raw archive member's path,
    but `arcname` here may instead be recomputed from a glob match (see
    `_claim` in the import path), so this does not assume its caller already
    ruled out traversal -- `Path(arcname).stem` alone would not catch it,
    since the stem is just the final component.
    """
    if ".." in PurePosixPath(arcname).parts:
        raise InvalidBundleError(f"unsafe path in bundle: {arcname}")
    try:
        if arcname.startswith("config/templates/"):
            validate_custom_stem(Path(arcname).stem)
            _check_text(path)
            return
        checker = _VALIDATORS.get(arcname)
        if checker is None:
            return
        checker(path)
    except InvalidBundleError:
        raise
    except Exception as error:
        raise InvalidBundleError(f"{arcname} is not valid: {error}") from error


def read_bundle_manifest(archive: Path) -> BundleManifest:
    """Extract only the manifest, so a preview never touches live files."""
    with tempfile.TemporaryDirectory(prefix="ra-settings-preview-") as temporary:
        stage = Path(temporary)
        try:
            _extract_validated(archive, stage)
        except UnsafeArchiveError:
            raise
        except Exception as error:
            raise InvalidBundleError("upload is not a readable bundle") from error
        return _manifest_from_stage(stage)


def _manifest_from_stage(stage: Path) -> BundleManifest:
    source = stage / MANIFEST_NAME
    if not source.is_file():
        raise InvalidBundleError("bundle is missing manifest.json")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidBundleError("manifest.json is not readable JSON") from error
    if not isinstance(data, dict):
        raise InvalidBundleError("manifest.json must be an object")
    if data.get("version") != BUNDLE_VERSION:
        raise UnsupportedBundleVersionError(
            f"bundle version {data.get('version')!r} is not supported"
        )
    raw = data.get("sections")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise InvalidBundleError("manifest sections must be a list of strings")
    known = tuple(item for item in raw if item in SECTIONS_BY_ID)
    unknown = tuple(item for item in raw if item not in SECTIONS_BY_ID)
    exported = data.get("exportedAt")
    return BundleManifest(
        version=BUNDLE_VERSION,
        exported_at=exported if isinstance(exported, str) else "",
        sections=known,
        unknown_sections=unknown,
    )
