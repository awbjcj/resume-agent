"""Small, dependency-free embedding retrieval for the skill taxonomy.

Embeddings only reduce the candidate set sent to the LLM.  They never decide a
synonym or domain assignment by themselves, which keeps taxonomy changes
auditable and safe to fall back from when an OpenAI key is unavailable.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import weakref
from array import array
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from pydantic import Field

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.taxonomy.clusters import ClusterMap
from resume_tailor_harness.taxonomy.state import taxonomy_root
from resume_tailor_harness.taxonomy.vocabulary import SKILL_GROUPS
from resume_tailor_harness.tracking.match_gap import normalize_skill


DEFAULT_EMBEDDING_MODEL = "openai:text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 256
# A full taxonomy refresh embeds every canonical, every domain, and every query
# descriptor -- tens of thousands of short strings, so dozens of provider calls.
# They are independent, so run a bounded number concurrently rather than paying
# the round trip serially.
EMBEDDING_CONCURRENCY = 4
CANONICAL_CANDIDATE_LIMIT = 8
DOMAIN_CANDIDATE_LIMIT = 8
PEER_CANDIDATE_LIMIT = 5
# Weight applied to a query term matched in a candidate's supporting text
# (a domain's member skills) rather than its identity (label + category).
_SECONDARY_MATCH_WEIGHT = 0.6


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
        from resume_tailor_harness.llm_runner import (
            model_access_available,
            provider_sdk_base_url,
            resolve_route,
            split_provider,
        )

        if not model_access_available(self.model_id):
            raise EmbeddingUnavailable("OpenAI embeddings are not currently funded")
        route = resolve_route(self.model_id)
        if not route.api_key:
            raise EmbeddingUnavailable("no OpenAI key is configured for embeddings")
        provider, model = split_provider(self.model_id)
        try:
            from resume_tailor_harness.tenancy.limits import enforce_agent_budget

            enforce_agent_budget(
                SimpleNamespace(model=SimpleNamespace(id=model, provider=provider))
            )
            from openai import OpenAI

            response = OpenAI(
                api_key=route.api_key,
                base_url=provider_sdk_base_url(provider, route.base_url),
            ).embeddings.create(
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
            from resume_tailor_harness.tenancy.costs import MeteredUsage
            from resume_tailor_harness.tenancy.usage import record_direct_usage

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


def _decode_vector(record: _EmbeddingRecord) -> array[float] | None:
    try:
        raw = base64.b64decode(record.vector_base64, validate=True)
        if len(raw) != record.dimensions * 4 or record.dimensions < 1:
            return None
        decoded = array("f")
        decoded.frombytes(raw)
        if sys.byteorder != "little":
            decoded.byteswap()
        return decoded
    except (ValueError, EOFError):
        return None


_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
    weakref.WeakValueDictionary()
)


def _cache_lock(path: Path) -> threading.RLock:
    key = path.resolve()
    with _CACHE_LOCKS_GUARD:
        return _CACHE_LOCKS.setdefault(key, threading.RLock())


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


@dataclass(frozen=True)
class EmbeddingResult:
    """Whatever could be embedded, plus why anything else could not."""

    vectors: dict[str, Sequence[float]]
    requested: int
    failed: int
    reason: str = ""
    cache_hits: int = 0
    cache_misses: int = 0
    provider_batches: int = 0
    cache_bytes: int = 0
    elapsed_ms: int = 0

    @property
    def complete(self) -> bool:
        return self.failed == 0


async def embed_descriptors(
    *,
    cluster_path: str | Path,
    descriptors: Mapping[str, str],
    provider: EmbeddingProvider,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    concurrency: int = EMBEDDING_CONCURRENCY,
    managed_namespaces: frozenset[str] = frozenset(),
    checkpoint: Callable[[], None] | None = None,
) -> EmbeddingResult:
    """Embed changed descriptors concurrently and keep every batch that lands.

    A full refresh needs dozens of provider calls.  Losing all of them because
    the last one was rate-limited is what kept this cache permanently empty: the
    next run then re-requested the identical work and lost it the same way, so
    retrieval never once ran on real vectors.  Every successful shard is
    therefore persisted regardless of its siblings, and a shard failure degrades
    the result instead of discarding it.
    """

    started = time.monotonic()
    if batch_size < 1:
        raise ValueError("embedding batch_size must be positive")
    if concurrency < 1:
        raise ValueError("embedding concurrency must be positive")
    # The taxonomy contract deliberately limits provider calls to 256 short
    # descriptors.  Clamp rather than reject an injected caller so the cache
    # remains a safe boundary even outside Settings validation.
    batch_size = min(batch_size, EMBEDDING_BATCH_SIZE)
    cache_path = embedding_cache_path(cluster_path)
    lock = _cache_lock(cache_path)
    with lock:
        cache = _load_cache(cache_path, provider.model_id)
    result: dict[str, Sequence[float]] = {}
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

    shards = [
        missing[index : index + batch_size]
        for index in range(0, len(missing), batch_size)
    ]
    semaphore = asyncio.Semaphore(concurrency)

    async def embed_shard(shard: list[tuple[str, str]]) -> list[list[float]]:
        async with semaphore:
            vectors = await provider.embed([text for _key, text in shard])
        if len(vectors) != len(shard) or not all(vectors):
            raise EmbeddingUnavailable(
                "embedding provider returned an incomplete batch"
            )
        return vectors

    from resume_tailor_harness.concurrency import gather_isolated

    outcomes = await gather_isolated(shards, embed_shard, checkpoint=checkpoint)
    failed = 0
    landed: dict[str, _EmbeddingRecord] = {}
    reasons: list[str] = []
    for shard, outcome in zip(shards, outcomes, strict=True):
        if not outcome.ok or outcome.value is None:
            failed += len(shard)
            reasons.append(str(outcome.error or "embedding batch failed"))
            continue
        for (key, text), vector in zip(shard, outcome.value, strict=True):
            record = _EmbeddingRecord(
                descriptor_sha256=_descriptor_hash(text),
                dimensions=len(vector),
                vector_base64=_encode_vector(vector),
            )
            landed[key] = record
            result[key] = array("f", (float(value) for value in vector))
    active = set(descriptors)
    if landed or managed_namespaces:
        # Provider work happens outside the file critical section. Re-read and
        # merge under the lock so concurrent Workspaces never lose a sibling's
        # successful shard. Managed namespaces also drop query/domain records
        # that no longer describe the active taxonomy.
        with lock:
            latest = _load_cache(cache_path, provider.model_id)
            stale = [
                key
                for key in latest.records
                if key.partition(":")[0] in managed_namespaces and key not in active
            ]
            for key in stale:
                latest.records.pop(key, None)
            latest.records.update(landed)
            if landed or stale:
                _save_cache(cache_path, latest)
    try:
        cache_bytes = cache_path.stat().st_size
    except OSError:
        cache_bytes = 0
    return EmbeddingResult(
        vectors=result,
        requested=len(descriptors),
        failed=failed,
        reason=reasons[0] if reasons else "",
        cache_hits=len(descriptors) - len(missing),
        cache_misses=len(missing),
        provider_batches=len(shards),
        cache_bytes=cache_bytes,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


async def cached_embeddings(
    *,
    cluster_path: str | Path,
    descriptors: Mapping[str, str],
    provider: EmbeddingProvider,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> dict[str, tuple[float, ...]]:
    """Embed changed descriptors only, then atomically refresh the local cache."""

    result = await embed_descriptors(
        cluster_path=cluster_path,
        descriptors=descriptors,
        provider=provider,
        batch_size=batch_size,
    )
    if not result.vectors and result.failed:
        raise EmbeddingUnavailable(result.reason)
    return {key: tuple(vector) for key, vector in result.vectors.items()}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return -1.0
    return numerator / (left_norm * right_norm)


def _terms(value: str) -> frozenset[str]:
    return frozenset(term for term in normalize_skill(value).split() if term)


@dataclass(frozen=True)
class _Candidate:
    """A retrieval candidate split into what it *is* and what it contains."""

    identity: frozenset[str]
    support: frozenset[str]


class _LexicalCorpus:
    """IDF-weighted lexical retrieval used whenever embeddings are unavailable.

    The previous fallback scored symmetric Jaccard over a whole descriptor.  A
    domain descriptor lists up to 24 member skills, so the union denominator
    grew with domain size and the *smallest* domain won almost every query --
    measured against a real 155-domain taxonomy, one two-member domain ranked
    first for 42 of 60 consecutive queries.  Scoring the query's own coverage
    removes that size bias (a larger candidate can only ever help), and IDF
    stops shared boilerplate from carrying a match on its own.
    """

    def __init__(self, entries: Mapping[str, tuple[str, str]]) -> None:
        self._entries = {
            key: _Candidate(identity=_terms(identity), support=_terms(support))
            for key, (identity, support) in entries.items()
        }
        self._keys = tuple(sorted(self._entries))
        document_frequency: dict[str, int] = {}
        postings: dict[str, list[str]] = defaultdict(list)
        for key, candidate in self._entries.items():
            for term in candidate.identity | candidate.support:
                document_frequency[term] = document_frequency.get(term, 0) + 1
                postings[term].append(key)
        total = len(self._entries)
        self._unseen = math.log(1 + total)
        self._idf = {
            term: math.log(1 + total / (1 + count))
            for term, count in document_frequency.items()
        }
        self._postings = {term: tuple(sorted(keys)) for term, keys in postings.items()}

    def _weight(self, term: str) -> float:
        # A term no candidate holds is maximally specific: it can only ever
        # lower a score by widening the denominator, never inflate one.
        return self._idf.get(term, self._unseen)

    def keys(self) -> tuple[str, ...]:
        return self._keys

    def contains(self, key: str) -> bool:
        return key in self._entries

    def matching_keys(self, query_terms: frozenset[str]) -> set[str]:
        """Return only candidates sharing a query term via the inverted index."""

        matches: set[str] = set()
        for term in query_terms:
            matches.update(self._postings.get(term, ()))
        return matches

    def score(self, query_terms: frozenset[str], key: str) -> float:
        candidate = self._entries.get(key)
        if candidate is None or not query_terms:
            return 0.0
        total = sum(self._weight(term) for term in query_terms)
        if not total:
            return 0.0
        matched = 0.0
        for term in query_terms:
            if term in candidate.identity:
                matched += self._weight(term)
            elif term in candidate.support:
                matched += self._weight(term) * _SECONDARY_MATCH_WEIGHT
        return matched / total


def _rank(
    query_terms: frozenset[str],
    *,
    query_vector: Sequence[float] | None,
    corpus: _LexicalCorpus,
    candidate_vectors: Mapping[str, Sequence[float]],
    limit: int,
    exclude: frozenset[str] = frozenset(),
) -> list[str]:
    # Cosine and lexical coverage are different scales, so a partially
    # embedded corpus must never rank the two against each other. An embedded
    # query competes only among embedded candidates; the rest wait for a warmer
    # cache rather than being ordered by an incomparable score.
    if query_vector is not None:
        scored = [
            (cosine_similarity(query_vector, vector), key)
            for key, vector in candidate_vectors.items()
            if key not in exclude and corpus.contains(key)
        ]
        return [
            key
            for _score, key in sorted(scored, key=lambda item: (-item[0], item[1]))[
                :limit
            ]
        ]

    # Lexical scoring is positive only when a query term occurs in a candidate,
    # so the inverted index avoids the old full-corpus score pass per query.
    # Preserve the previous deterministic zero-score tail when fewer than
    # ``limit`` candidates match.
    scored = [
        (corpus.score(query_terms, key), key)
        for key in corpus.matching_keys(query_terms)
        if key not in exclude
    ]
    ranked = [
        key
        for _score, key in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    ]
    if len(ranked) >= limit:
        return ranked
    selected = set(ranked)
    for key in corpus.keys():
        if key in exclude or key in selected:
            continue
        ranked.append(key)
        if len(ranked) >= limit:
            break
    return ranked


# How much of a long alias or member list a descriptor is allowed to carry.
ALIAS_PREVIEW = 12
MEMBER_PREVIEW = 24

# The four functions below and CandidateIndex both render these strings, but
# they must not share a lookup: the single-token functions scan the whole map
# to find one entry's forms, which is correct once and quadratic across a
# taxonomy.  So only the wording is shared, and each caller supplies the forms
# it already has.


def _skill_descriptor_text(token: str, forms: Sequence[str]) -> str:
    aliases_text = ", ".join(forms[:ALIAS_PREVIEW])
    return f"technical skill: {token}" + (
        f"; aliases: {aliases_text}" if aliases_text else ""
    )


def _domain_descriptor_text(category: str, label: str, members: Sequence[str]) -> str:
    member_text = ", ".join(members[:MEMBER_PREVIEW])
    return (
        f"skill taxonomy category: {category}; domain: {label}; members: {member_text}"
    )


def _skill_lexical_text(token: str, forms: Sequence[str]) -> tuple[str, str]:
    return token, ", ".join(forms[:ALIAS_PREVIEW])


def _domain_lexical_text(
    category: str, label: str, members: Sequence[str]
) -> tuple[str, str]:
    return (
        f"{label} {SKILL_GROUPS.get(category, category)}",
        ", ".join(members[:MEMBER_PREVIEW]),
    )


def _alias_forms(token: str, aliases: Mapping[str, str]) -> list[str]:
    return sorted(alias for alias, canonical in aliases.items() if canonical == token)


def _domain_members(domain_id: str, cmap: ClusterMap) -> list[str]:
    return sorted(
        token for token, value in cmap.domain_of.items() if value == domain_id
    )


def skill_descriptor(token: str, aliases: Mapping[str, str]) -> str:
    return _skill_descriptor_text(token, _alias_forms(token, aliases))


def domain_descriptor(domain_id: str, cmap: ClusterMap) -> str:
    return _domain_descriptor_text(
        cmap.category_of.get(domain_id, "other"),
        cmap.domain_label.get(domain_id, domain_id),
        _domain_members(domain_id, cmap),
    )


def skill_lexical_parts(token: str, aliases: Mapping[str, str]) -> tuple[str, str]:
    """Split a skill into its own name and the synonyms that merely support it."""

    return _skill_lexical_text(token, _alias_forms(token, aliases))


def domain_lexical_parts(domain_id: str, cmap: ClusterMap) -> tuple[str, str]:
    """Split a domain into its identity (label + category) and its members.

    The human category label is used rather than the slug because a query like
    ``3d object detection`` shares real words with "AI & Machine Learning" and
    none with ``ai-ml``.
    """

    return _domain_lexical_text(
        cmap.category_of.get(domain_id, "other"),
        cmap.domain_label.get(domain_id, domain_id),
        _domain_members(domain_id, cmap),
    )


@dataclass(frozen=True)
class CandidateIndex:
    """Revision-scoped retrieval data derived once from a Cluster map.

    Reverse aliases, domain membership, descriptors, and lexical corpora used
    to be rebuilt by independently scanning the full taxonomy for every query.
    Keeping them behind this module concentrates both ranking knowledge and the
    scale characteristic callers rely on.
    """

    revision: str
    canonical_ids: tuple[str, ...]
    domain_ids: tuple[str, ...]
    aliases_by_canonical: Mapping[str, tuple[str, ...]]
    members_by_domain: Mapping[str, tuple[str, ...]]
    canonical_descriptors: Mapping[str, str]
    domain_descriptors: Mapping[str, str]
    canonical_lexical_parts: Mapping[str, tuple[str, str]]
    domain_lexical_parts: Mapping[str, tuple[str, str]]
    canonical_corpus: _LexicalCorpus
    domain_corpus: _LexicalCorpus

    @classmethod
    def build(cls, cmap: ClusterMap, revision: str) -> CandidateIndex:
        aliases: dict[str, list[str]] = defaultdict(list)
        for alias, canonical in cmap.aliases.items():
            aliases[canonical].append(alias)
        aliases_by_canonical = {
            canonical: tuple(sorted(forms)) for canonical, forms in aliases.items()
        }

        members: dict[str, list[str]] = defaultdict(list)
        for token, domain_id in cmap.domain_of.items():
            members[domain_id].append(token)
        members_by_domain = {
            domain_id: tuple(sorted(tokens)) for domain_id, tokens in members.items()
        }

        canonical_ids = tuple(sorted(set(cmap.aliases.values()) | set(cmap.domain_of)))
        domain_ids = tuple(
            sorted(set(cmap.domain_of.values()) | set(cmap.domain_label))
        )

        def describe_domain(domain_id: str) -> str:
            return _domain_descriptor_text(
                cmap.category_of.get(domain_id, "other"),
                cmap.domain_label.get(domain_id, domain_id),
                members_by_domain.get(domain_id, ()),
            )

        canonical_descriptors = {
            token: _skill_descriptor_text(token, aliases_by_canonical.get(token, ()))
            for token in canonical_ids
        }
        domain_descriptors = {
            domain_id: describe_domain(domain_id) for domain_id in domain_ids
        }
        canonical_parts = {
            token: _skill_lexical_text(token, aliases_by_canonical.get(token, ()))
            for token in canonical_ids
        }
        domain_parts = {
            domain_id: _domain_lexical_text(
                cmap.category_of.get(domain_id, "other"),
                cmap.domain_label.get(domain_id, domain_id),
                members_by_domain.get(domain_id, ()),
            )
            for domain_id in domain_ids
        }
        return cls(
            revision=revision,
            canonical_ids=canonical_ids,
            domain_ids=domain_ids,
            aliases_by_canonical=aliases_by_canonical,
            members_by_domain=members_by_domain,
            canonical_descriptors=canonical_descriptors,
            domain_descriptors=domain_descriptors,
            canonical_lexical_parts=canonical_parts,
            domain_lexical_parts=domain_parts,
            canonical_corpus=_LexicalCorpus(canonical_parts),
            domain_corpus=_LexicalCorpus(domain_parts),
        )

    def skill_descriptor(self, token: str) -> str:
        cached = self.canonical_descriptors.get(token)
        if cached is not None:
            return cached
        return _skill_descriptor_text(token, self.aliases_by_canonical.get(token, ()))

    def skill_lexical_parts(self, token: str) -> tuple[str, str]:
        cached = self.canonical_lexical_parts.get(token)
        if cached is not None:
            return cached
        return _skill_lexical_text(token, self.aliases_by_canonical.get(token, ()))


_INDEX_CACHE_LIMIT = 8
_INDEX_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: OrderedDict[str, CandidateIndex] = OrderedDict()


def _index_revision(cmap: ClusterMap) -> str:
    payload = json.dumps(
        {
            "aliases": cmap.aliases,
            "domain_of": cmap.domain_of,
            "domain_label": cmap.domain_label,
            "category_of": cmap.category_of,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def candidate_index(cmap: ClusterMap, revision: str | None = None) -> CandidateIndex:
    revision = revision or _index_revision(cmap)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(revision)
        if cached is not None:
            _INDEX_CACHE.move_to_end(revision)
            return cached
    built = CandidateIndex.build(cmap, revision)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.setdefault(revision, built)
        _INDEX_CACHE.move_to_end(revision)
        while len(_INDEX_CACHE) > _INDEX_CACHE_LIMIT:
            _INDEX_CACHE.popitem(last=False)
        return cached


@dataclass(frozen=True)
class CandidateRetrievalMetrics:
    elapsed_ms: int = 0
    index_ms: int = 0
    ranking_ms: int = 0
    descriptors: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    provider_batches: int = 0
    cache_bytes: int = 0


@dataclass(frozen=True)
class CandidateContext:
    mode: str
    canonical_candidates: dict[str, tuple[str, ...]]
    domain_candidates: dict[str, tuple[str, ...]]
    peer_candidates: dict[str, tuple[str, ...]]
    # Why retrieval degraded, when it did.  Without this a total embedding
    # outage is indistinguishable from a healthy run anywhere downstream.
    reason: str = ""
    metrics: CandidateRetrievalMetrics = field(
        default_factory=CandidateRetrievalMetrics
    )

    @property
    def degraded(self) -> bool:
        return self.mode != "embedding"


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
    revision: str | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> CandidateContext:
    """Return bounded synonym/domain/peer candidates with a lexical fallback."""

    started = time.monotonic()
    normalized = {token for raw in tokens if (token := normalize_skill(raw))}
    # Older maps may contain a canonical domain assignment without an explicit
    # identity alias.  It is still a legitimate synonym candidate, so derive
    # the candidate universe from both axes of the canonical tree.
    index_started = time.monotonic()
    index = candidate_index(existing, revision)
    index_ms = round((time.monotonic() - index_started) * 1000)
    canonical_ids = index.canonical_ids
    domain_ids = index.domain_ids
    canonical_descriptors = index.canonical_descriptors
    domain_descriptors = index.domain_descriptors
    new_descriptors = {token: index.skill_descriptor(token) for token in normalized}
    resolved_provider = provider or _provider_from_settings()
    vectors: dict[str, Sequence[float]] = {}
    mode = "lexical"
    reason = "no embedding provider is configured"
    embedding_metrics = EmbeddingResult(vectors={}, requested=0, failed=0)
    if resolved_provider is not None:
        descriptors = {
            **{f"skill:{key}": value for key, value in canonical_descriptors.items()},
            **{f"domain:{key}": value for key, value in domain_descriptors.items()},
            **{f"query:{key}": value for key, value in new_descriptors.items()},
        }
        outcome = await embed_descriptors(
            cluster_path=cluster_path,
            descriptors=descriptors,
            provider=resolved_provider,
            batch_size=get_settings().skill_embedding_batch_size,
            managed_namespaces=frozenset({"skill", "domain", "query"}),
            checkpoint=checkpoint,
        )
        vectors = outcome.vectors
        if outcome.complete:
            mode, reason = "embedding", ""
        elif outcome.vectors:
            mode, reason = "partial", outcome.reason
        else:
            mode, reason = "lexical", outcome.reason
        embedding_metrics = outcome

    ranking_started = time.monotonic()
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
    peer_vectors = {
        key: vectors[f"query:{key}"] for key in normalized if f"query:{key}" in vectors
    }
    # One corpus per axis, built once.  Peers exclude the query at rank time
    # rather than rebuilding an n-1 corpus for every one of n tokens.
    canonical_corpus = index.canonical_corpus
    domain_corpus = index.domain_corpus
    peer_corpus = _LexicalCorpus(
        {token: index.skill_lexical_parts(token) for token in normalized}
    )
    canonical_candidates: dict[str, tuple[str, ...]] = {}
    domain_candidates: dict[str, tuple[str, ...]] = {}
    peer_candidates: dict[str, tuple[str, ...]] = {}
    for token in new_descriptors:
        query_vector = vectors.get(f"query:{token}")
        query_terms = _terms(token)
        canonical_candidates[token] = tuple(
            _rank(
                query_terms,
                query_vector=query_vector,
                corpus=canonical_corpus,
                candidate_vectors=canonical_vectors,
                limit=CANONICAL_CANDIDATE_LIMIT,
                exclude=frozenset({token}),
            )
        )
        domain_candidates[token] = tuple(
            _rank(
                query_terms,
                query_vector=query_vector,
                corpus=domain_corpus,
                candidate_vectors=domain_vectors,
                limit=DOMAIN_CANDIDATE_LIMIT,
            )
        )
        peer_candidates[token] = tuple(
            _rank(
                query_terms,
                query_vector=query_vector,
                corpus=peer_corpus,
                candidate_vectors=peer_vectors,
                limit=PEER_CANDIDATE_LIMIT,
                exclude=frozenset({token}),
            )
        )
    return CandidateContext(
        mode=mode,
        canonical_candidates=canonical_candidates,
        domain_candidates=domain_candidates,
        peer_candidates=peer_candidates,
        reason=reason,
        metrics=CandidateRetrievalMetrics(
            elapsed_ms=round((time.monotonic() - started) * 1000),
            index_ms=index_ms,
            ranking_ms=round((time.monotonic() - ranking_started) * 1000),
            descriptors=(
                len(canonical_descriptors)
                + len(domain_descriptors)
                + len(new_descriptors)
            ),
            cache_hits=embedding_metrics.cache_hits,
            cache_misses=embedding_metrics.cache_misses,
            provider_batches=embedding_metrics.provider_batches,
            cache_bytes=embedding_metrics.cache_bytes,
        ),
    )


async def domain_neighbor_candidates(
    *,
    cluster_path: str | Path,
    cmap: ClusterMap,
    provider: EmbeddingProvider | None = None,
    limit: int = 3,
) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Retrieve bounded semantic neighbours for maintenance planning."""

    index = candidate_index(cmap)
    domain_ids = index.domain_ids
    descriptors = index.domain_descriptors
    resolved_provider = provider or _provider_from_settings()
    vectors: dict[str, Sequence[float]] = {}
    mode = "lexical"
    if resolved_provider is not None:
        outcome = await embed_descriptors(
            cluster_path=cluster_path,
            descriptors={
                f"maintenance-domain:{key}": value for key, value in descriptors.items()
            },
            provider=resolved_provider,
            batch_size=get_settings().skill_embedding_batch_size,
            managed_namespaces=frozenset({"maintenance-domain"}),
        )
        vectors = outcome.vectors
        mode = (
            "embedding"
            if outcome.complete
            else ("partial" if outcome.vectors else "lexical")
        )
    candidate_vectors = {
        key: vectors[f"maintenance-domain:{key}"]
        for key in domain_ids
        if f"maintenance-domain:{key}" in vectors
    }
    corpus = index.domain_corpus
    result: dict[str, tuple[str, ...]] = {}
    for domain_id in domain_ids:
        identity, _support = index.domain_lexical_parts[domain_id]
        result[domain_id] = tuple(
            _rank(
                _terms(identity),
                query_vector=candidate_vectors.get(domain_id),
                corpus=corpus,
                candidate_vectors=candidate_vectors,
                limit=limit,
                exclude=frozenset({domain_id}),
            )
        )
    return mode, result
