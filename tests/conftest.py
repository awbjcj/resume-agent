"""Repository-wide test isolation.

The suite's standing contract is that it runs offline: no API key, no network.
Agent calls are faked at their runner seams, but skill-taxonomy retrieval
resolves its embedding provider from ``Settings`` instead of from an argument,
and ``Settings`` reads the project ``.env`` -- so on any machine with a real
``OPENAI_API_KEY`` in that file, a cluster refresh quietly made a live
embeddings request. That is slow enough to blow the API tests' run-completion
budget and makes results depend on ambient credentials.

Default the provider to absent so retrieval deterministically exercises its
lexical fallback. Tests that want embeddings still pass ``embedding_provider``
explicitly, which never consults this seam.
"""

import pytest

import resume_tailor_harness.taxonomy.embeddings as embeddings


@pytest.fixture(autouse=True)
def _offline_embedding_provider(monkeypatch):
    monkeypatch.setattr(embeddings, "_provider_from_settings", lambda: None)
