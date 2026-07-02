"""Per-document extraction fragments cached by content hash and prompt version."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from resume_agent.llm_runner import Runner
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.corpus import (
    FRAGMENTS_DIRNAME,
    SourceDoc,
    SourceManifest,
    doc_path,
    save_manifest,
)
from resume_agent.profile.extractor import PROMPT_VERSION, extract_profile_facts
from resume_agent.profile.ids import assign_fact_ids
from resume_agent.profile.resume_reader import read_document_text

CacheStatus = Literal["cached", "stale", "source-changed", "missing"]


@dataclass
class FragmentResult:
    fragments: dict[str, ProfileFacts] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)


def _paths(profile_dir: str | Path, doc_id: str) -> tuple[Path, Path]:
    root = Path(profile_dir) / FRAGMENTS_DIRNAME
    return root / f"{doc_id}.json", root / f"{doc_id}.meta.json"


def load_fragment(profile_dir: str | Path, doc_id: str) -> ProfileFacts | None:
    fragment_path, _ = _paths(profile_dir, doc_id)
    try:
        return ProfileFacts.model_validate_json(fragment_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _meta_matches(meta_path: Path, sha256: str) -> bool:
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(metadata, dict)
        and metadata.get("sha256") == sha256
        and metadata.get("prompt_version") == PROMPT_VERSION
    )


def _atomic_write(path: Path, content: str) -> None:
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
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _save(
    profile_dir: str | Path, doc_id: str, facts: ProfileFacts, sha256: str
) -> None:
    fragment_path, meta_path = _paths(profile_dir, doc_id)
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(fragment_path, facts.model_dump_json(indent=2) + "\n")
    metadata = {"sha256": sha256, "prompt_version": PROMPT_VERSION}
    _atomic_write(meta_path, json.dumps(metadata, sort_keys=True) + "\n")


def fragment_cache_status(profile_dir: str | Path, doc: SourceDoc) -> CacheStatus:
    fragment_path, meta_path = _paths(profile_dir, doc.id)
    try:
        observed_sha = hashlib.sha256(doc_path(profile_dir, doc).read_bytes()).hexdigest()
    except OSError:
        return "missing"
    if observed_sha != doc.sha256:
        return "source-changed"
    if _meta_matches(meta_path, observed_sha) and load_fragment(profile_dir, doc.id):
        return "cached"
    return "stale" if fragment_path.exists() or meta_path.exists() else "missing"


def extract_fragments(
    profile_dir: str | Path, manifest: SourceManifest, agent: Runner
) -> FragmentResult:
    """Extract registered documents, reusing valid cached fragments."""
    result = FragmentResult()
    manifest_changed = False
    for doc in manifest.docs:
        _, meta_path = _paths(profile_dir, doc.id)
        source_path = doc_path(profile_dir, doc)
        try:
            observed_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            previous = load_fragment(profile_dir, doc.id)
            if previous is None:
                result.status[doc.id] = f"failed: {exc}"
            else:
                result.fragments[doc.id] = previous
                result.status[doc.id] = f"stale: {exc}"
            continue

        source_changed = observed_sha != doc.sha256
        if source_changed:
            doc.sha256 = observed_sha
            manifest_changed = True
        if _meta_matches(meta_path, observed_sha):
            cached = load_fragment(profile_dir, doc.id)
            if cached is not None:
                result.fragments[doc.id] = cached
                result.status[doc.id] = "cached"
                continue

        try:
            text = read_document_text(source_path)
            facts = assign_fact_ids(extract_profile_facts(text, agent), doc.id)
        except Exception as exc:
            previous = load_fragment(profile_dir, doc.id)
            if previous is None:
                result.status[doc.id] = f"failed: {exc}"
            else:
                result.fragments[doc.id] = previous
                result.status[doc.id] = f"stale: {exc}"
            continue

        _save(profile_dir, doc.id, facts, observed_sha)
        result.fragments[doc.id] = facts
        result.status[doc.id] = "source-changed" if source_changed else "extracted"

    if manifest_changed:
        save_manifest(manifest, profile_dir)
    return result
