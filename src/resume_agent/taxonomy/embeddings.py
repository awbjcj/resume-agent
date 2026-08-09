"""Small, dependency-free embedding retrieval for the skill taxonomy.

Embeddings only reduce the candidate set sent to the LLM.  They never decide a
synonym or domain assignment by themselves, which keeps taxonomy changes
auditable and safe to fall back from when an OpenAI key is unavailable.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import struct
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.state import taxonomy_root
from resume_agent.tracking.match_gap import normalize_skill


DEFAULT_EMBEDDING_MODEL = "openai:text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 256
CANONICAL_CANDIDATE_LIMIT = 8
DOMAIN_CANDIDATE_LIMIT = 8
PEER_CANDIDATE_LIMIT = 5


class EmbeddingUnavailable(RuntimeError):
    """A recoverable embedding access or provider failure."""


class EmbeddingProvider(Protocol):
    model_id: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    """Direct OpenAI SDK seam with the repository's key and usage accounting."""

    def __init__(self, model_id: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.model_id = model_id

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, list(texts))

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        from resume_agent.llm_runner import (
            model_access_available,
            resolve_api_key,
            split_provider,
        )

        if not model_access_available(self.model_id):
            raise EmbeddingUnavailable("OpenAI embeddings are not currently funded")
        api_key = resolve_api_key(self.model_id)
        if not api_key:
            raise EmbeddingUnavailable("no OpenAI key is configured for embeddings")
        provider, model = split_provider(self.model_id)
        try:
            from resume_agent.tenancy.limits import enforce_agent_budget

            enforce_agent_budget(
                SimpleNamespace(model=SimpleNamespace(id=model, provider=provider))
            )
            from openai import OpenAI

            response = OpenAI(api_key=api_key).embeddings.create(
                model=model,
                input=texts,
                encoding_format="float",
            )
        except EmbeddingUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - caller has a deterministic fallback
            raise EmbeddingUnavailable(f"embedding provider failed: {exc}") from exc

        vectors = [
            list(item.embedding)
            for item in sorted(response.data, key=lambda item: item.index)
        ]
        if len(vectors) != len(texts) or not all(vectors):
            raise EmbeddingUnavailable(
                "embedding provider returned an incomplete batch"
            )
        usage = getattr(response, "usage", None)
        try:
            from resume_agent.tenancy.costs import MeteredUsage
            from resume_agent.tenancy.usage import record_direct_usage

            tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            record_direct_usage(
                MeteredUsage(
                    provider=provider,
                    model=model,
                    input_tokens=tokens,
                    total_tokens=int(getattr(usage, "total_tokens", 0) or tokens),
                )
            )
        except Exception:
            # A useful embedding response must not be discarded because usage
            # telemetry is unavailable outside a tenant context.
            pass
        return vectors


class _EmbeddingRecord(ExtensibleModel):
    descriptor_sha256: str
    dimensions: int
    vector_base64: str


class _EmbeddingCacheFile(ExtensibleModel):
    model_id: str
    records: dict[str, _EmbeddingRecord] = Field(default_factory=dict)


def embedding_cache_path(cluster_path: str | Path) -> Path:
    return taxonomy_root(cluster_path) / "skill_embeddings.json"


def _descriptor_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _encode_vector(vector: Sequence[float]) -> str:
    if not vector:
        raise ValueError("embedding vectors must not be empty")
    packed = struct.pack(f"<{len(vector)}f", *vector)
    return base64.b64encode(packed).decode("ascii")


def _decode_vector(record: _EmbeddingRecord) -> tuple[float, ...] | None:
    try:
        raw = base64.b64decode(record.vector_base64, validate=True)
        if len(raw) != record.dimensions * 4 or record.dimensions < 1:
            return None
        return struct.unpack(f"<{record.dimensions}f", raw)
    except (ValueError, struct.error):
        return None


def _load_cache(path: Path, model_id: str) -> _EmbeddingCacheFile:
    try:
        parsed = _EmbeddingCacheFile.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return _EmbeddingCacheFile(model_id=model_id)
    return (
        parsed
        if parsed.model_id == model_id
        else _EmbeddingCacheFile(model_id=model_id)
    )


def _save_cache(path: Path, cache: _EmbeddingCacheFile) -> None:
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
            handle.write(cache.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def cached_embeddings(
    *,
    cluster_path: str | Path,
    descriptors: Mapping[str, str],
    provider: EmbeddingProvider,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> dict[str, tuple[float, ...]]:
    """Embed changed descriptors only, then atomically refresh the local cache."""

    if batch_size < 1:
        raise ValueError("embedding batch_size must be positive")
    # The taxonomy contract deliberately limits provider calls to 256 short
    # descriptors.  Clamp rather than reject an injected caller so the cache
    # remains a safe boundary even outside Settings validation.
    batch_size = min(batch_size, EMBEDDING_BATCH_SIZE)
    cache_path = embedding_cache_path(cluster_path)
    cache = _load_cache(cache_path, provider.model_id)
    result: dict[str, tuple[float, ...]] = {}
    missing: list[tuple[str, str]] = []
    for key, text in descriptors.items():
        digest = _descriptor_hash(text)
        record = cache.records.get(key)
        decoded = (
            _decode_vector(record)
            if record is not None and record.descriptor_sha256 == digest
            else None
        )
        if decoded is None:
            missing.append((key, text))
        else:
            result[key] = decoded

    for index in range(0, len(missing), batch_size):
        shard = missing[index : index + batch_size]
        vectors = await provider.embed([text for _key, text in shard])
        if len(vectors) != len(shard):
            raise EmbeddingUnavailable(
                "embedding provider returned an incomplete batch"
            )
        for (key, text), vector in zip(shard, vectors, strict=True):
            if not vector:
                raise EmbeddingUnavailable(
                    "embedding provider returned an empty vector"
                )
            encoded = _EmbeddingRecord(
                descriptor_sha256=_descriptor_hash(text),
                dimensions=len(vector),
                vector_base64=_encode_vector(vector),
            )
            cache.records[key] = encoded
            result[key] = tuple(float(value) for value in vector)
    if missing:
        _save_cache(cache_path, cache)
    return result


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return -1.0
    return numerator / (left_norm * right_norm)


def _terms(value: str) -> set[str]:
    return {term for term in normalize_skill(value).split() if term}


def _lexical_score(query: str, candidate: str) -> float:
    left, right = _terms(query), _terms(candidate)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _rank(
    query: str,
    *,
    query_vector: Sequence[float] | None,
    candidates: Mapping[str, str],
    candidate_vectors: Mapping[str, Sequence[float]],
    limit: int,
) -> list[str]:
    scored = []
    for key, descriptor in candidates.items():
        vector = candidate_vectors.get(key)
        score = (
            cosine_similarity(query_vector, vector)
            if query_vector is not None and vector is not None
            else _lexical_score(query, descriptor)
        )
        scored.append((score, key))
    return [
        key
        for _score, key in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    ]


def skill_descriptor(token: str, aliases: Mapping[str, str]) -> str:
    forms = sorted(alias for alias, canonical in aliases.items() if canonical == token)
    aliases_text = ", ".join(forms[:12])
    return f"technical skill: {token}" + (
        f"; aliases: {aliases_text}" if aliases_text else ""
    )


def domain_descriptor(domain_id: str, cmap: ClusterMap) -> str:
    members = sorted(
        token for token, value in cmap.domain_of.items() if value == domain_id
    )
    category = cmap.category_of.get(domain_id, "other")
    label = cmap.domain_label.get(domain_id, domain_id)
    return f"skill taxonomy category: {category}; domain: {label}; members: {', '.join(members[:24])}"


@dataclass(frozen=True)
class CandidateContext:
    mode: str
    canonical_candidates: dict[str, tuple[str, ...]]
    domain_candidates: dict[str, tuple[str, ...]]
    peer_candidates: dict[str, tuple[str, ...]]


def _provider_from_settings() -> EmbeddingProvider | None:
    model_id = getattr(
        get_settings(), "skill_embedding_model", DEFAULT_EMBEDDING_MODEL
    ).strip()
    return OpenAIEmbeddingProvider(model_id) if model_id else None


async def build_candidate_context(
    *,
    cluster_path: str | Path,
    tokens: set[str],
    existing: ClusterMap,
    provider: EmbeddingProvider | None = None,
) -> CandidateContext:
    """Return bounded synonym/domain/peer candidates with a lexical fallback."""

    normalized = {token for raw in tokens if (token := normalize_skill(raw))}
    # Older maps may contain a canonical domain assignment without an explicit
    # identity alias.  It is still a legitimate synonym candidate, so derive
    # the candidate universe from both axes of the canonical tree.
    canonical_ids = sorted(set(existing.aliases.values()) | set(existing.domain_of))
    domain_ids = sorted(set(existing.domain_of.values()) | set(existing.domain_label))
    canonical_descriptors = {
        token: skill_descriptor(token, existing.aliases) for token in canonical_ids
    }
    domain_descriptors = {
        domain_id: domain_descriptor(domain_id, existing) for domain_id in domain_ids
    }
    new_descriptors = {
        token: skill_descriptor(token, existing.aliases) for token in normalized
    }
    resolved_provider = provider or _provider_from_settings()
    vectors: dict[str, tuple[float, ...]] = {}
    mode = "lexical"
    if resolved_provider is not None:
        try:
            descriptors = {
                **{
                    f"skill:{key}": value
                    for key, value in canonical_descriptors.items()
                },
                **{f"domain:{key}": value for key, value in domain_descriptors.items()},
                **{f"query:{key}": value for key, value in new_descriptors.items()},
            }
            vectors = await cached_embeddings(
                cluster_path=cluster_path,
                descriptors=descriptors,
                provider=resolved_provider,
                batch_size=get_settings().skill_embedding_batch_size,
            )
            mode = "embedding"
        except EmbeddingUnavailable:
            vectors = {}

    canonical_vectors = {
        key: vectors[f"skill:{key}"]
        for key in canonical_ids
        if f"skill:{key}" in vectors
    }
    domain_vectors = {
        key: vectors[f"domain:{key}"]
        for key in domain_ids
        if f"domain:{key}" in vectors
    }
    canonical_candidates: dict[str, tuple[str, ...]] = {}
    domain_candidates: dict[str, tuple[str, ...]] = {}
    peer_candidates: dict[str, tuple[str, ...]] = {}
    for token, descriptor in new_descriptors.items():
        query_vector = vectors.get(f"query:{token}")
        canonical_candidates[token] = tuple(
            key
            for key in _rank(
                descriptor,
                query_vector=query_vector,
                candidates=canonical_descriptors,
                candidate_vectors=canonical_vectors,
                limit=CANONICAL_CANDIDATE_LIMIT,
            )
            if key != token
        )
        domain_candidates[token] = tuple(
            _rank(
                descriptor,
                query_vector=query_vector,
                candidates=domain_descriptors,
                candidate_vectors=domain_vectors,
                limit=DOMAIN_CANDIDATE_LIMIT,
            )
        )
        peers = {key: value for key, value in new_descriptors.items() if key != token}
        peer_vectors = {
            key: vectors[f"query:{key}"] for key in peers if f"query:{key}" in vectors
        }
        peer_candidates[token] = tuple(
            _rank(
                descriptor,
                query_vector=query_vector,
                candidates=peers,
                candidate_vectors=peer_vectors,
                limit=PEER_CANDIDATE_LIMIT,
            )
        )
    return CandidateContext(
        mode=mode,
        canonical_candidates=canonical_candidates,
        domain_candidates=domain_candidates,
        peer_candidates=peer_candidates,
    )


async def domain_neighbor_candidates(
    *,
    cluster_path: str | Path,
    cmap: ClusterMap,
    provider: EmbeddingProvider | None = None,
    limit: int = 3,
) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Retrieve bounded semantic neighbours for maintenance planning."""

    domain_ids = sorted(set(cmap.domain_of.values()) | set(cmap.domain_label))
    descriptors = {
        domain_id: domain_descriptor(domain_id, cmap) for domain_id in domain_ids
    }
    resolved_provider = provider or _provider_from_settings()
    vectors: dict[str, tuple[float, ...]] = {}
    mode = "lexical"
    if resolved_provider is not None:
        try:
            vectors = await cached_embeddings(
                cluster_path=cluster_path,
                descriptors={
                    f"maintenance-domain:{key}": value
                    for key, value in descriptors.items()
                },
                provider=resolved_provider,
                batch_size=get_settings().skill_embedding_batch_size,
            )
            mode = "embedding"
        except EmbeddingUnavailable:
            vectors = {}
    candidate_vectors = {
        key: vectors[f"maintenance-domain:{key}"]
        for key in domain_ids
        if f"maintenance-domain:{key}" in vectors
    }
    result: dict[str, tuple[str, ...]] = {}
    for domain_id, descriptor in descriptors.items():
        alternatives = {
            key: value for key, value in descriptors.items() if key != domain_id
        }
        result[domain_id] = tuple(
            _rank(
                descriptor,
                query_vector=candidate_vectors.get(domain_id),
                candidates=alternatives,
                candidate_vectors=candidate_vectors,
                limit=limit,
            )
        )
    return mode, result
