"""Source-document registry for the fact-lock profile corpus."""

import hashlib
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field, model_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.resume_reader import SUPPORTED_SUFFIXES

MANIFEST_NAME = "sources.json"
SOURCES_DIRNAME = "sources"
FRAGMENTS_DIRNAME = "fragments"

_SLUG = re.compile(r"[^a-z0-9]+")


class SourceDoc(ExtensibleModel):
    id: str
    filename: str
    sha256: str
    added_at: str
    primary: bool = False


class SourceManifest(ExtensibleModel):
    docs: list[SourceDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def exactly_one_primary_when_nonempty(self) -> "SourceManifest":
        if self.docs and sum(doc.primary for doc in self.docs) != 1:
            raise ValueError("a non-empty source manifest must have exactly one primary")
        return self


def sources_dir(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / SOURCES_DIRNAME


def doc_path(profile_dir: str | Path, doc: SourceDoc) -> Path:
    return sources_dir(profile_dir) / doc.filename


def _manifest_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / MANIFEST_NAME


def load_manifest(profile_dir: str | Path) -> SourceManifest:
    path = _manifest_path(profile_dir)
    if not path.exists():
        return SourceManifest()
    try:
        return SourceManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid source manifest: {path}") from exc


def save_manifest(manifest: SourceManifest, profile_dir: str | Path) -> None:
    validated = SourceManifest.model_validate(manifest.model_dump())
    path = _manifest_path(profile_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(validated.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _doc_id(filename: str, sha256: str) -> str:
    slug = _SLUG.sub("-", Path(filename).stem.casefold()).strip("-") or "doc"
    return f"{slug}-{sha256[:8]}"


def add_source(
    profile_dir: str | Path, file_path: str | Path, primary: bool = False
) -> SourceDoc:
    source = Path(file_path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(
            f"Unsupported document format: {suffix or '(none)'} (use {supported})"
        )

    data = source.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    manifest = load_manifest(profile_dir)
    existing = next((doc for doc in manifest.docs if doc.sha256 == sha256), None)
    if existing is not None:
        if primary and not existing.primary:
            for doc in manifest.docs:
                doc.primary = doc.id == existing.id
            save_manifest(manifest, profile_dir)
        return existing

    primary = primary or not manifest.docs
    doc = SourceDoc(
        id=_doc_id(source.name, sha256),
        filename=source.name,
        sha256=sha256,
        added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        primary=primary,
    )
    target_dir = sources_dir(profile_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / doc.filename
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
        doc.filename = f"{doc.id}{suffix}"
        target = target_dir / doc.filename
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)

    if primary:
        for other in manifest.docs:
            other.primary = False
    manifest.docs.append(doc)
    save_manifest(manifest, profile_dir)
    return doc


def remove_source(
    profile_dir: str | Path, ident: str, purge: bool = False
) -> SourceDoc | None:
    manifest = load_manifest(profile_dir)
    doc = next(
        (candidate for candidate in manifest.docs if ident in (candidate.id, candidate.filename)),
        None,
    )
    if doc is None:
        return None
    manifest.docs = [candidate for candidate in manifest.docs if candidate.id != doc.id]
    if doc.primary and manifest.docs:
        manifest.docs[0].primary = True
    save_manifest(manifest, profile_dir)

    fragments = Path(profile_dir) / FRAGMENTS_DIRNAME
    for stale in (fragments / f"{doc.id}.json", fragments / f"{doc.id}.meta.json"):
        stale.unlink(missing_ok=True)
    if purge:
        doc_path(profile_dir, doc).unlink(missing_ok=True)
    return doc


def migrate_legacy(profile_dir: str | Path, resume_path: str | None) -> SourceDoc | None:
    """Register the legacy configured resume as the primary source once."""
    if load_manifest(profile_dir).docs:
        return None
    if not resume_path or not Path(resume_path).exists():
        return None
    return add_source(profile_dir, resume_path, primary=True)
