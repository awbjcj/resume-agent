import asyncio
from types import SimpleNamespace

from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.embeddings import (
    EmbeddingUnavailable,
    OpenAIEmbeddingProvider,
    build_candidate_context,
    cached_embeddings,
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
