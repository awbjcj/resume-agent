import asyncio
from types import SimpleNamespace

import pytest

from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.embeddings import (
    EmbeddingUnavailable,
    OpenAIEmbeddingProvider,
    build_candidate_context,
    cached_embeddings,
    embed_descriptors,
    embedding_cache_path,
)


class _EmbeddingProvider:
    model_id = "openai:text-embedding-3-small"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if any(term in lowered for term in ("python", "rust", "backend", "go")):
            return [1.0, 0.0]
        return [0.0, 1.0]


class _UnavailableProvider:
    model_id = "openai:text-embedding-3-small"

    async def embed(self, texts):
        raise EmbeddingUnavailable("offline")


def test_embedding_cache_batches_hits_and_invalidates_descriptors(tmp_path):
    provider = _EmbeddingProvider()
    descriptors = {"a": "python", "b": "java", "c": "rust"}

    first = asyncio.run(
        cached_embeddings(
            cluster_path=tmp_path / "cluster_map.json",
            descriptors=descriptors,
            provider=provider,
            batch_size=2,
        )
    )
    second = asyncio.run(
        cached_embeddings(
            cluster_path=tmp_path / "cluster_map.json",
            descriptors=descriptors,
            provider=provider,
            batch_size=2,
        )
    )
    third = asyncio.run(
        cached_embeddings(
            cluster_path=tmp_path / "cluster_map.json",
            descriptors={**descriptors, "b": "java platform"},
            provider=provider,
            batch_size=2,
        )
    )

    assert [len(call) for call in provider.calls] == [2, 1, 1]
    assert first == second
    assert third["b"] == (0.0, 1.0)
    assert embedding_cache_path(tmp_path / "cluster_map.json").exists()


def test_embedding_result_reports_real_cache_and_provider_work(tmp_path):
    provider = _EmbeddingProvider()
    cluster_path = tmp_path / "cluster_map.json"
    descriptors = {"a": "python", "b": "java", "c": "rust"}

    cold = asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors=descriptors,
            provider=provider,
            batch_size=2,
        )
    )
    warm = asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors=descriptors,
            provider=provider,
            batch_size=2,
        )
    )

    assert cold.cache_hits == 0
    assert cold.cache_misses == 3
    assert cold.provider_batches == 2
    assert cold.cache_bytes > 0
    assert warm.cache_hits == 3
    assert warm.cache_misses == 0
    assert warm.provider_batches == 0
    assert warm.elapsed_ms >= 0


def test_embedding_cache_prunes_stale_records_in_managed_namespaces(tmp_path):
    provider = _EmbeddingProvider()
    cluster_path = tmp_path / "cluster_map.json"

    asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors={"query:a": "alpha", "query:b": "beta"},
            provider=provider,
            managed_namespaces=frozenset({"query"}),
        )
    )
    asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors={"query:b": "beta", "query:c": "gamma"},
            provider=provider,
            managed_namespaces=frozenset({"query"}),
        )
    )

    import json

    payload = json.loads(embedding_cache_path(cluster_path).read_text(encoding="utf-8"))
    assert set(payload["records"]) == {"query:b", "query:c"}


def test_candidate_context_scans_aliases_a_constant_number_of_times(tmp_path):
    class _CountingAliases(dict[str, str]):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    aliases = _CountingAliases(
        {f"skill-{index}": f"skill-{index}" for index in range(8_000)}
    )
    existing = ClusterMap(aliases=aliases)

    asyncio.run(
        build_candidate_context(
            cluster_path=tmp_path / "cluster_map.json",
            tokens={"new skill"},
            existing=existing,
            provider=_UnavailableProvider(),
        )
    )

    assert aliases.items_calls <= 4


def test_embedding_cache_never_sends_more_than_256_descriptors(tmp_path):
    provider = _EmbeddingProvider()
    descriptors = {f"skill-{index}": f"descriptor {index}" for index in range(300)}

    asyncio.run(
        cached_embeddings(
            cluster_path=tmp_path / "cluster_map.json",
            descriptors=descriptors,
            provider=provider,
            # Direct callers cannot bypass the provider-call safety bound.
            batch_size=999,
        )
    )

    assert [len(call) for call in provider.calls] == [256, 44]


def test_embedding_fanout_honours_run_cancellation(tmp_path):
    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(
            embed_descriptors(
                cluster_path=tmp_path / "cluster_map.json",
                descriptors={"query:a": "alpha"},
                provider=_EmbeddingProvider(),
                checkpoint=cancelled,
            )
        )


def test_embeddings_rank_bounded_candidates_and_fall_back_to_lexical(tmp_path):
    existing = ClusterMap(
        aliases={"python": "python", "java": "java"},
        domain_of={"python": "backend", "java": "jvm"},
        domain_label={"backend": "Backend APIs", "jvm": "JVM"},
        category_of={"backend": "backend-apis", "jvm": "languages"},
    )

    semantic = asyncio.run(
        build_candidate_context(
            cluster_path=tmp_path / "cluster_map.json",
            tokens={"rust", "go"},
            existing=existing,
            provider=_EmbeddingProvider(),
        )
    )
    fallback = asyncio.run(
        build_candidate_context(
            cluster_path=tmp_path / "fallback" / "fallback.json",
            tokens={"rust"},
            existing=existing,
            provider=_UnavailableProvider(),
        )
    )

    assert semantic.mode == "embedding"
    assert semantic.canonical_candidates["rust"][0] == "python"
    assert semantic.domain_candidates["rust"][0] == "backend"
    assert semantic.peer_candidates["rust"] == ("go",)
    assert fallback.mode == "lexical"
    assert len(fallback.canonical_candidates["rust"]) <= 8


def test_openai_embedding_provider_records_usage_through_direct_usage_seam(
    monkeypatch,
):
    import openai

    import resume_agent.llm_runner as llm_runner
    import resume_agent.tenancy.limits as limits
    import resume_agent.tenancy.usage as usage

    class _Embeddings:
        def create(self, **_kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                    SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                ],
                usage=SimpleNamespace(prompt_tokens=7, total_tokens=7),
            )

    class _Client:
        embeddings = _Embeddings()

    recorded = []
    monkeypatch.setattr(llm_runner, "model_access_available", lambda _model: True)
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda _model: "key")
    monkeypatch.setattr(
        llm_runner,
        "split_provider",
        lambda _model: ("openai", "text-embedding-3-small"),
    )
    monkeypatch.setattr(limits, "enforce_agent_budget", lambda _agent: None)
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _Client())
    monkeypatch.setattr(usage, "record_direct_usage", recorded.append)

    vectors = OpenAIEmbeddingProvider()._embed_sync(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert recorded[0].provider == "openai"
    assert recorded[0].model == "text-embedding-3-small"
    assert recorded[0].input_tokens == 7


def test_a_failed_shard_never_discards_the_batches_that_succeeded(tmp_path):
    """Partial progress must survive, or the cache can never fill.

    A full refresh needs dozens of provider calls.  Discarding all of them
    because one was rate-limited is what kept this cache permanently empty:
    the next run re-requested the identical work and lost it the same way, so
    retrieval silently ran on the lexical fallback forever.
    """

    class _Flaky:
        model_id = "openai:text-embedding-3-small"

        def __init__(self) -> None:
            self.calls: list[list[str]] = []
            self.fail = True

        async def embed(self, texts):
            self.calls.append(list(texts))
            if self.fail and any("boom" in text for text in texts):
                raise EmbeddingUnavailable("rate limited")
            return [[1.0, 0.0] for _ in texts]

    cluster_path = tmp_path / "cluster_map.json"
    descriptors = {"a": "alpha", "b": "boom"}

    provider = _Flaky()
    first = asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors=descriptors,
            provider=provider,
            batch_size=1,
        )
    )

    assert set(first.vectors) == {"a"}
    assert first.failed == 1
    assert first.complete is False
    assert "rate limited" in first.reason
    assert embedding_cache_path(cluster_path).exists()

    recovered = _Flaky()
    recovered.fail = False
    second = asyncio.run(
        embed_descriptors(
            cluster_path=cluster_path,
            descriptors=descriptors,
            provider=recovered,
            batch_size=1,
        )
    )

    # Only the descriptor that failed is re-requested; the survivor was kept.
    assert recovered.calls == [["boom"]]
    assert set(second.vectors) == {"a", "b"}
    assert second.complete is True


def test_lexical_ranking_is_not_won_by_the_smallest_domain(tmp_path):
    """The fallback must rank on shared meaning, not on descriptor length.

    Symmetric Jaccard divided by the union, so a domain listing 24 members was
    penalised for its own size and a two-member domain won almost everything --
    on a real 155-domain taxonomy one domain ranked first for 42 of 60
    consecutive queries.
    """

    existing = ClusterMap(
        aliases={},
        domain_of={
            "object detection": "computer-vision",
            "image segmentation": "computer-vision",
            "image classification": "computer-vision",
            "optical flow": "computer-vision",
            "pose estimation": "computer-vision",
            "payroll": "hr-tools",
        },
        domain_label={"computer-vision": "Computer Vision", "hr-tools": "HR"},
        category_of={"computer-vision": "ai-ml", "hr-tools": "domain-knowledge"},
    )

    context = asyncio.run(
        build_candidate_context(
            cluster_path=tmp_path / "cluster_map.json",
            tokens={"3d object detection"},
            existing=existing,
            provider=_UnavailableProvider(),
        )
    )

    assert context.mode == "lexical"
    assert context.degraded is True
    assert context.domain_candidates["3d object detection"][0] == "computer-vision"
