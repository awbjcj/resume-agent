"""Source-document registry for the fact-lock profile corpus."""

import hashlib
import os
import re
import shutil
import tempfile
from ipaddress import ip_address
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.resume_reader import SUPPORTED_SUFFIXES
from resume_agent.security.paths import confined_path
from resume_agent.tenancy.paths import resolve_tenant_path

MANIFEST_NAME = "sources.json"
SOURCES_DIRNAME = "sources"
FRAGMENTS_DIRNAME = "fragments"

_SLUG = re.compile(r"[^a-z0-9]+")

SourceMode = Literal["literal", "synthesis", "project"]
SourceOrigin = Literal["upload", "github"]

_UNSET: object = object()


def default_mode(filename: str) -> SourceMode:
    """Decks default to synthesis; everything else stays literal extraction."""
    return "synthesis" if Path(filename).suffix.lower() == ".pptx" else "literal"


class SourceDoc(ExtensibleModel):
    id: str
    filename: str
    sha256: str
    added_at: str
    primary: bool = False
    mode: SourceMode = "literal"
    anchor: str | None = None
    origin: SourceOrigin = "upload"


class SourceManifest(ExtensibleModel):
    docs: list[SourceDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_docs(self) -> "SourceManifest":
        if self.docs and sum(doc.primary for doc in self.docs) != 1:
            raise ValueError(
                "a non-empty source manifest must have exactly one primary"
            )
        for doc in self.docs:
            if doc.primary and doc.mode != "literal":
                raise ValueError(f"primary source {doc.id} must use literal mode")
            if doc.anchor is not None and doc.mode != "synthesis":
                raise ValueError(f"anchor on {doc.id} requires synthesis mode")
        return self


def sources_dir(profile_dir: str | Path) -> Path:
    return resolve_tenant_path(profile_dir) / SOURCES_DIRNAME


def doc_path(profile_dir: str | Path, doc: SourceDoc) -> Path:
    return confined_path(sources_dir(profile_dir), doc.filename)


def _manifest_path(profile_dir: str | Path) -> Path:
    return resolve_tenant_path(profile_dir) / MANIFEST_NAME


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


_FRONTMATTER = re.compile(
    rb"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?(?:\n|\Z)", re.DOTALL
)


def _valid_repo_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.strip("/")
        ):
            return False
        if host.casefold() == "localhost" or host.casefold().endswith(".localhost"):
            return False
        try:
            return ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def frontmatter_repo_url(data: bytes) -> str | None:
    """Return a valid public HTTP(S) repo URL from leading YAML frontmatter."""
    match = _FRONTMATTER.match(data)
    if match is None:
        return None
    try:
        block = match.group(1).decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in block.splitlines():
        key, separator, raw_value = line.partition(":")
        if separator and key.strip() == "repo_url":
            value = raw_value.strip().strip("'\"")
            return value if _valid_repo_url(value) else None
    return None


def add_source(
    profile_dir: str | Path,
    file_path: str | Path,
    primary: bool = False,
    mode: SourceMode | None = None,
    anchor: str | None = None,
    origin: SourceOrigin = "upload",
) -> SourceDoc:
    source = Path(file_path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(
            f"Unsupported document format: {suffix or '(none)'} (use {supported})"
        )

    # ``file_path`` is a local CLI selection or an API-created temporary upload, not an HTTP path.
    # codeql[py/path-injection] -- Intentional local source-file read; persisted destination is confined.
    data = source.read_bytes()
    dossier_mode = (
        source.suffix.lower() == ".md" and frontmatter_repo_url(data) is not None
    )
    resolved_mode = mode or ("project" if dossier_mode else default_mode(source.name))
    if anchor is not None and resolved_mode != "synthesis":
        raise ValueError("anchor requires synthesis mode")
    sha256 = hashlib.sha256(data).hexdigest()
    manifest = load_manifest(profile_dir)
    existing = next((doc for doc in manifest.docs if doc.sha256 == sha256), None)
    if existing is not None:
        changed = False
        if primary and not existing.primary:
            for doc in manifest.docs:
                doc.primary = doc.id == existing.id
            changed = True
        if (mode is not None or dossier_mode) and existing.mode != resolved_mode:
            existing.mode = resolved_mode
            if resolved_mode != "synthesis":
                existing.anchor = None
            changed = True
        if anchor is not None and existing.anchor != anchor:
            existing.anchor = anchor
            changed = True
        if changed:
            save_manifest(manifest, profile_dir)
        return existing

    primary = primary or not manifest.docs
    if primary and resolved_mode != "literal":
        raise ValueError(
            "the first source becomes the primary resume and must be literal — "
            "add your resume first, or pass --mode literal"
        )
    doc = SourceDoc(
        id=_doc_id(source.name, sha256),
        filename=source.name,
        sha256=sha256,
        added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        primary=primary,
        mode=resolved_mode,
        anchor=anchor,
        origin=origin,
    )
    target_dir = sources_dir(profile_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = doc_path(profile_dir, doc)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
        doc.filename = f"{doc.id}{suffix}"
        target = doc_path(profile_dir, doc)
    # codeql[py/path-injection] -- Local source capability is compared with a confined destination.
    if source.resolve() != target.resolve():
        # codeql[py/path-injection] -- Source is the intentional local file selected above.
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
        (
            candidate
            for candidate in manifest.docs
            if ident in (candidate.id, candidate.filename)
        ),
        None,
    )
    if doc is None:
        return None
    manifest.docs = [candidate for candidate in manifest.docs if candidate.id != doc.id]
    if doc.primary and manifest.docs:
        replacement = next(
            (candidate for candidate in manifest.docs if candidate.mode == "literal"),
            None,
        )
        if replacement is None:
            raise ValueError(
                "cannot remove the primary source while only synthesis-mode "
                "sources remain — the primary must be a literal document"
            )
        replacement.primary = True
    save_manifest(manifest, profile_dir)

    fragments = resolve_tenant_path(profile_dir) / FRAGMENTS_DIRNAME
    for stale in (
        confined_path(fragments, f"{doc.id}.json"),
        confined_path(fragments, f"{doc.id}.meta.json"),
        confined_path(fragments, f"{doc.id}.evidence.json"),
    ):
        stale.unlink(missing_ok=True)
    if purge:
        doc_path(profile_dir, doc).unlink(missing_ok=True)
    return doc


def update_source(
    profile_dir: str | Path,
    ident: str,
    *,
    mode: SourceMode | None = None,
    anchor: str | None | object = _UNSET,
    primary: bool | None = None,
) -> SourceDoc | None:
    """Update a registered doc's mode/anchor/primary. anchor=None clears it."""
    manifest = load_manifest(profile_dir)
    doc = next(
        (c for c in manifest.docs if ident in (c.id, c.filename)),
        None,
    )
    if doc is None:
        return None
    if mode is not None:
        doc.mode = mode
        if mode != "synthesis":
            doc.anchor = None
    if anchor is not _UNSET:
        doc.anchor = anchor  # type: ignore[assignment]
    if primary:
        for other in manifest.docs:
            other.primary = other.id == doc.id
    save_manifest(manifest, profile_dir)
    return doc


def migrate_legacy(
    profile_dir: str | Path, resume_path: str | None
) -> SourceDoc | None:
    """Register the legacy configured resume as the primary source once."""
    if load_manifest(profile_dir).docs:
        return None
    if not resume_path or not Path(resume_path).exists():
        return None
    return add_source(profile_dir, resume_path, primary=True)
