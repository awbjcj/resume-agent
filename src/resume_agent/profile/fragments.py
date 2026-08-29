"""Per-document extraction fragments cached by content hash and prompt version."""

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner, run_with_cleanup
from resume_agent.models.base import Source
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.corpus import (
    FRAGMENTS_DIRNAME,
    SourceDoc,
    SourceManifest,
    doc_path,
    save_manifest,
)
from resume_agent.profile.extractor import PROMPT_VERSION, aextract_profile_facts
from resume_agent.profile.ids import assign_fact_ids
from resume_agent.profile.project_extractor import (
    PROJECT_PROMPT_VERSION,
    aextract_project_facts,
)
from resume_agent.profile.resume_reader import CONVERTER_VERSION, read_document_text
from resume_agent.profile.synthesis import (
    SYNTHESIS_PROMPT_VERSION,
    asynthesize_document,
    fragment_to_facts,
)
from resume_agent.security.paths import confined_path
from resume_agent.tenancy.paths import resolve_tenant_path

CacheStatus = Literal["cached", "stale", "source-changed", "missing"]


@dataclass
class FragmentResult:
    fragments: dict[str, ProfileFacts] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    drops: dict[str, list[str]] = field(default_factory=dict)


def _paths(profile_dir: str | Path, doc_id: str) -> tuple[Path, Path]:
    root = resolve_tenant_path(profile_dir) / FRAGMENTS_DIRNAME
    return (
        confined_path(root, f"{doc_id}.json"),
        confined_path(root, f"{doc_id}.meta.json"),
    )


def evidence_path(profile_dir: str | Path, doc_id: str) -> Path:
    root = resolve_tenant_path(profile_dir) / FRAGMENTS_DIRNAME
    return confined_path(root, f"{doc_id}.evidence.json")


def load_fragment(profile_dir: str | Path, doc_id: str) -> ProfileFacts | None:
    fragment_path, _ = _paths(profile_dir, doc_id)
    try:
        return ProfileFacts.model_validate_json(
            fragment_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None


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


def _literal_meta(sha256: str) -> dict:
    return {
        "sha256": sha256,
        "prompt_version": PROMPT_VERSION,
        "converter_version": CONVERTER_VERSION,
    }


def _synthesis_meta(doc: SourceDoc, sha256: str) -> dict:
    return {
        "sha256": sha256,
        "synthesis_prompt_version": SYNTHESIS_PROMPT_VERSION,
        "converter_version": CONVERTER_VERSION,
        "mode": doc.mode,
        "anchor": doc.anchor,
    }


def _project_meta(sha256: str) -> dict:
    return {
        "sha256": sha256,
        "project_prompt_version": PROJECT_PROMPT_VERSION,
        "converter_version": CONVERTER_VERSION,
    }


def _meta_equals(meta_path: Path, expected: dict) -> bool:
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return metadata == expected


def _expected_meta(doc: SourceDoc, sha256: str) -> dict:
    if doc.mode == "synthesis":
        return _synthesis_meta(doc, sha256)
    if doc.mode == "project":
        return _project_meta(sha256)
    return _literal_meta(sha256)


def fragment_cache_status(profile_dir: str | Path, doc: SourceDoc) -> CacheStatus:
    fragment_path, meta_path = _paths(profile_dir, doc.id)
    try:
        observed_sha = hashlib.sha256(
            doc_path(profile_dir, doc).read_bytes()
        ).hexdigest()
    except OSError:
        return "stale" if fragment_path.exists() else "missing"
    if observed_sha != doc.sha256:
        return "source-changed"
    if _meta_equals(meta_path, _expected_meta(doc, observed_sha)) and load_fragment(
        profile_dir, doc.id
    ):
        return "cached"
    return "stale" if fragment_path.exists() or meta_path.exists() else "missing"


@dataclass
class Produced:
    """What one producer yields for one document."""

    facts: ProfileFacts
    evidence: dict | None = None
    drops: list[str] | None = None


@dataclass(frozen=True)
class FragmentProducer:
    """One extraction mode behind the fragment cache walk."""

    selects: Callable[[SourceDoc], bool]
    expected_meta: Callable[[SourceDoc, str], dict]
    produce: Callable[[SourceDoc, str, asyncio.Semaphore], Awaitable[Produced]]
    runners: tuple[Any, ...] = ()


@dataclass
class _Pending:
    doc: SourceDoc
    text: str
    meta: dict
    source_changed: bool


def _record_failure(
    result: FragmentResult,
    profile_dir: str | Path,
    doc: SourceDoc,
    exc: BaseException,
) -> None:
    previous = load_fragment(profile_dir, doc.id)
    if previous is None:
        result.status[doc.id] = f"failed: {exc}"
    else:
        result.fragments[doc.id] = previous
        result.status[doc.id] = f"stale: {exc}"


def _save_produced(
    profile_dir: str | Path, doc_id: str, produced: Produced, meta: dict
) -> None:
    fragment_path, meta_path = _paths(profile_dir, doc_id)
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(fragment_path, produced.facts.model_dump_json(indent=2) + "\n")
    if produced.evidence is not None:
        _atomic_write(
            evidence_path(profile_dir, doc_id),
            json.dumps(produced.evidence, indent=2, sort_keys=True) + "\n",
        )
    _atomic_write(meta_path, json.dumps(meta, sort_keys=True) + "\n")


def _apply_produced(
    result: FragmentResult, profile_dir: str | Path, item: _Pending, produced: Produced
) -> None:
    _save_produced(profile_dir, item.doc.id, produced, item.meta)
    result.fragments[item.doc.id] = produced.facts
    result.status[item.doc.id] = (
        "source-changed" if item.source_changed else "extracted"
    )
    if produced.drops is not None:
        result.drops[item.doc.id] = produced.drops


def _walk_fragments(
    profile_dir: str | Path, manifest: SourceManifest, producer: FragmentProducer
) -> FragmentResult:
    result = FragmentResult()
    manifest_changed = False
    pending: list[_Pending] = []
    for doc in manifest.docs:
        if not producer.selects(doc):
            continue
        _, meta_path = _paths(profile_dir, doc.id)
        source_path = doc_path(profile_dir, doc)
        try:
            observed_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            _record_failure(result, profile_dir, doc, exc)
            continue

        source_changed = observed_sha != doc.sha256
        if source_changed:
            doc.sha256 = observed_sha
            manifest_changed = True
        expected = producer.expected_meta(doc, observed_sha)
        if _meta_equals(meta_path, expected):
            cached = load_fragment(profile_dir, doc.id)
            if cached is not None:
                result.fragments[doc.id] = cached
                result.status[doc.id] = "cached"
                continue

        try:
            text = read_document_text(source_path)
        except Exception as exc:
            _record_failure(result, profile_dir, doc, exc)
            continue
        pending.append(_Pending(doc, text, expected, source_changed))

    if pending:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        produced_results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    pending,
                    lambda item: producer.produce(item.doc, item.text, sem),
                ),
                *producer.runners,
            )
        )
        for item, res in zip(pending, produced_results):
            if not res.ok or res.value is None:
                _record_failure(
                    result,
                    profile_dir,
                    item.doc,
                    res.error
                    if res.error is not None
                    else RuntimeError("produce failed"),
                )
                continue
            _apply_produced(result, profile_dir, item, res.value)

    if manifest_changed:
        save_manifest(manifest, profile_dir)
    return result


def extract_fragments(
    profile_dir: str | Path, manifest: SourceManifest, agent: Runner
) -> FragmentResult:
    """Extract literal-mode documents, reusing valid cached fragments."""

    async def _produce(doc: SourceDoc, text: str, sem: asyncio.Semaphore) -> Produced:
        facts = assign_fact_ids(
            await aextract_profile_facts(text, agent, sem=sem), doc.id
        )
        return Produced(facts=facts)

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode == "literal",
            expected_meta=lambda doc, sha: _literal_meta(sha),
            produce=_produce,
            runners=(agent,),
        ),
    )


def extract_project_fragments(
    profile_dir: str | Path,
    manifest: SourceManifest,
    agent: Runner,
) -> FragmentResult:
    """Extract project-mode documents through the closed project schema."""

    async def _produce(doc: SourceDoc, text: str, sem: asyncio.Semaphore) -> Produced:
        source = Source.github if doc.origin == "github" else Source.manual
        facts = await aextract_project_facts(text, agent, source=source, sem=sem)
        return Produced(facts=assign_fact_ids(facts, doc.id))

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode == "project",
            expected_meta=lambda _doc, sha: _project_meta(sha),
            produce=_produce,
            runners=(agent,),
        ),
    )


def extract_synthesis_fragments(
    profile_dir: str | Path,
    manifest: SourceManifest,
    skeleton: list[dict],
    synthesis_agent: Runner,
    entailment_agent: Runner,
) -> FragmentResult:
    """Synthesize registered synthesis-mode documents, reusing valid caches."""

    async def _produce(doc: SourceDoc, text: str, sem: asyncio.Semaphore) -> Produced:
        fragment, drops = await asynthesize_document(
            doc, text, skeleton, synthesis_agent, entailment_agent, sem=sem
        )
        facts, evidence = fragment_to_facts(doc, fragment, skeleton)
        return Produced(facts=facts, evidence=evidence, drops=drops)

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode == "synthesis",
            expected_meta=_synthesis_meta,
            produce=_produce,
            runners=(synthesis_agent, entailment_agent),
        ),
    )
