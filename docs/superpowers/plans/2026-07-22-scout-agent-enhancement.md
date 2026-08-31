# Scout Agent Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the two agno advisor agents (Source Scout, Search Scout) into ranked, web-cited, multi-axis advisors that exploit provider-native reasoning/caching/citations across Anthropic, OpenAI, Gemini, and DeepSeek — with graceful fallback when a provider lacks a feature.

**Architecture:** Keep the existing `research → format` two-agent pattern for both scouts. Add one shared capability seam (`provider_capabilities`) in `llm_runner.py` and thread a `reasoning` flag through `build_model` / `build_search_equipped`. Fit-scoring and avoid-judgment happen inside the reasoning-enabled research agent; the cheap Haiku formatter stays un-thought. New recommendation fields ride the existing untyped run-result dicts.

**Tech Stack:** Python 3.12, agno 2.6.x model wrappers, Pydantic (`ExtensibleModel` / `CamelModel`), pytest (fully offline — all agents + browser faked, no API key, no network).

## Global Constraints

- Tests run fully offline: `.venv/Scripts/python.exe -m pytest`. No API key, no network — fake every agent.
- Lint: `ruff check` must pass.
- All provider access stays behind the `build_model` / `build_search_equipped` seam — never import a concrete agno model class outside `llm_runner.py`.
- Capability probing must **never raise**; unknown/unresolvable provider → all-`False` (conservative, valid un-enriched output).
- Every enhancement is **best-effort**: a provider lacking reasoning/citations still produces valid output. Caching is cost-only — `cache_read == 0` is never an error.
- Fact-lock discipline preserved: research notes + citations are untrusted data; the formatter copies verbatim and never invents. `fit_score`/`signal`/`citations` are advisory display metadata and never write to `facts.json`.
- Scout results are **untyped run-result dicts** (hand-built camelCase keys), NOT governed by `api/schemas/suggestions.py`. New fields are added as camelCase keys to the service row dicts — no OpenAPI/TS contract regeneration for the scout payload.
- New Pydantic fields must be default-safe so the cheap formatter degrades cleanly.

## Correctness Amendments (binding)

These amendments were verified against the current repository contracts and the
installed Agno 2.6.12 adapters before implementation. They supersede conflicting
task snippets below.

1. **Keep the existing feature branch and protect unrelated edits.** This plan is
   already committed on `feat/scout-agent-enhancement`, which is the isolated branch
   for this work. The pre-existing uncommitted Lever connector changes are unrelated,
   remain untouched, and are excluded from task commits and verification conclusions.
2. **Capability resolution is conservative at both boundaries.** An empty model id,
   an unrecognised `provider:` prefix, or an unrecognised model family returns the
   all-`False` capability shape. `build_model(..., reasoning=True)` and
   `build_search_equipped(..., reasoning=True)` must also intersect the request with
   `provider_capabilities`; callers cannot accidentally attach unsupported kwargs.
   The Task 1 unknown-prefix test must assert all `False`, not Anthropic citations.
3. **Use verified Agno 2.6.12 kwargs.** Claude uses adaptive `thinking` plus
   `output_config.effort`; OpenAI Responses uses `reasoning_effort`; Gemini uses
   `thinking_level`; DeepSeek uses `use_thinking=True` with
   `reasoning_effort="max"`. Gemini native scout search uses Agno's
   `GeminiInteractions` wrapper with `search=True`, `thinking_level` when enabled,
   and `store=False` so profile/search context is not retained as a stored
   Interaction. OpenAI Responses native search likewise sets `store=False`.
4. **Runtime failure is not a silent no-reasoning retry.** Unsupported features are
   removed before construction. A real provider timeout/error follows the existing
   bounded `AgentRunner` retry policy and then surfaces; this change does not add a
   second, potentially costly fallback LLM call.
5. **The shared citation type lives in a shared module.** Add
   `discovery/scout_models.py` with `Citation`; neither scout imports domain models
   from the other scout. Only non-empty HTTP(S) citations cross the service boundary.
6. **Scores are validated, not merely documented.** Both schema fields use
   `Field(default=None, ge=0, le=100)`. Service ranking sorts descending by score
   with `None` last, while retaining deterministic input order for ties.
7. **URL-less avoid rows must survive.** Positive Source Scout rows still require an
   HTTP(S) careers URL. An explicit `avoid` row may omit it, skips dedupe and URL
   validation, and is returned with status/signal `avoid`; the UI renders it as
   non-selectable advisory evidence.
8. **Search kinds map to real config destinations.** `location -> locations`,
   `adjacent_role -> titles`, and `seniority -> experience_levels`. Seniority values
   are restricted to the existing LinkedIn vocabulary (`internship`, `entry`,
   `associate`, `mid-senior`, `director`, `executive`). Dedupe keys use the destination
   field, so `title` and `adjacent_role` cannot emit the same value twice in one run.
9. **Scout completion payloads are generic run results.** Do not edit the unrelated
   match-gap schemas in `api/schemas/suggestions.py`. `RunOut.result` is intentionally
   `Any`, so regenerating OpenAPI would not type these nested payloads. The effective
   consumer contract is the service row dict plus the local types in
   `web/src/features/{sources,search-scout}`; update those types, UI components, and
   focused component tests together. No OpenAPI/TypeScript regeneration is required
   unless a separate typed-run-result refactor is undertaken.
10. **UI work is in scope.** Render fit scores, evidence links, and avoid state using
    the existing shadcn/base-nova primitives and semantic tokens. Wire all actionable
    Search Scout kinds into the Search settings draft. Avoid rows and duplicates are
    never selectable. Evidence links open safely with `rel="noreferrer"`.
11. **Final verification covers the full story.** In addition to the backend suite,
    run scoped frontend tests, frontend lint/build, the OpenAPI drift gate (expected
    unchanged for this generic payload), provider-import seam grep, and a browser
    walkthrough of both dialogs when the local runtime can be started.

---

### Task 1: Provider capability seam

**Files:**
- Modify: `src/resume_tailor_harness/llm_runner.py` (add after `plan_search`, ~line 204)
- Test: `tests/test_llm_runner_capabilities.py` (create)

**Interfaces:**
- Consumes: `split_provider(model_id) -> tuple[str, str]` (existing).
- Produces:
  - `ProviderCapabilities` — frozen dataclass with bool fields `supports_reasoning`, `supports_native_citations`, `supports_prompt_cache`.
  - `provider_capabilities(model_id: str) -> ProviderCapabilities`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_runner_capabilities.py`:

```python
from resume_tailor_harness.llm_runner import ProviderCapabilities, provider_capabilities


def test_anthropic_sonnet_full_reasoning_and_citations():
    caps = provider_capabilities("claude-sonnet-5")
    assert caps == ProviderCapabilities(
        supports_reasoning=True,
        supports_native_citations=True,
        supports_prompt_cache=True,
    )


def test_anthropic_haiku_has_no_reasoning():
    caps = provider_capabilities("claude-haiku-4-5-20251001")
    assert caps.supports_reasoning is False
    assert caps.supports_native_citations is True
    assert caps.supports_prompt_cache is True


def test_openai_gpt5_reasons_and_cites():
    caps = provider_capabilities("openai:gpt-5")
    assert caps.supports_reasoning is True
    assert caps.supports_native_citations is True
    assert caps.supports_prompt_cache is True


def test_openai_non_reasoning_model():
    caps = provider_capabilities("openai:gpt-4o")
    assert caps.supports_reasoning is False
    assert caps.supports_native_citations is True


def test_gemini_3_reasons_and_cites():
    caps = provider_capabilities("gemini:gemini-3.5-flash")
    assert caps.supports_reasoning is True
    assert caps.supports_native_citations is True


def test_deepseek_reasoner_reasons_but_no_citations():
    caps = provider_capabilities("deepseek:deepseek-reasoner")
    assert caps.supports_reasoning is True
    assert caps.supports_native_citations is False
    assert caps.supports_prompt_cache is True


def test_deepseek_chat_has_no_reasoning():
    caps = provider_capabilities("deepseek:deepseek-chat")
    assert caps.supports_reasoning is False
    assert caps.supports_native_citations is False


def test_unknown_prefix_is_conservative_anthropic():
    # A Workday-style "tenant:site" resolves to anthropic (bare id path) but the
    # bare id itself is unknown -> reasoning stays on the anthropic default unless haiku.
    caps = provider_capabilities("acme:workday")
    # "acme" is not a known provider, so split_provider returns anthropic + full id.
    assert caps.supports_native_citations is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_capabilities.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProviderCapabilities'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/llm_runner.py`, add these imports at the top if missing (`dataclasses.dataclass` is already used for `SearchPlan` — confirm `from dataclasses import dataclass` exists near the top; it does). Add directly after `plan_search` (after line ~204):

```python
# Anthropic models without extended thinking / effort (Haiku family rejects effort).
_ANTHROPIC_NO_REASONING = ("haiku",)
# OpenAI reasoning-model id prefixes.
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")
# Gemini thinking-capable id markers.
_GEMINI_REASONING_MARKERS = ("gemini-3", "2.5")
# DeepSeek legacy non-thinking id.
_DEEPSEEK_NON_REASONING = ("deepseek-chat",)


@dataclass(frozen=True)
class ProviderCapabilities:
    """What provider-native features a resolved model can use, best-effort."""

    supports_reasoning: bool
    supports_native_citations: bool
    supports_prompt_cache: bool


def provider_capabilities(model_id: str) -> ProviderCapabilities:
    """Map a (possibly provider-prefixed) model id to its native features.

    Never raises. Unknown providers and unresolvable ids fall back to the
    conservative all-False shape so callers still produce valid, un-enriched
    output. Reasoning is model-gated (not just provider-gated) — the Haiku
    formatter and DeepSeek's legacy chat id have no reasoning.
    """
    provider, model = split_provider(model_id)
    folded = model.casefold()
    if provider == "anthropic":
        reasoning = not any(mark in folded for mark in _ANTHROPIC_NO_REASONING)
        return ProviderCapabilities(reasoning, True, True)
    if provider == "openai":
        reasoning = folded.startswith(_OPENAI_REASONING_PREFIXES)
        return ProviderCapabilities(reasoning, True, True)
    if provider == "gemini":
        reasoning = any(mark in folded for mark in _GEMINI_REASONING_MARKERS)
        return ProviderCapabilities(reasoning, True, True)
    if provider == "deepseek":
        reasoning = folded not in _DEEPSEEK_NON_REASONING
        return ProviderCapabilities(reasoning, False, True)
    return ProviderCapabilities(False, False, False)
```

Note: `str.startswith` accepts a tuple, so `folded.startswith(_OPENAI_REASONING_PREFIXES)` works as written.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_capabilities.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/llm_runner.py tests/test_llm_runner_capabilities.py
git commit -m "feat(llm): add provider_capabilities seam for reasoning/citations/cache gating"
```

---

### Task 2: Thread reasoning through `build_model`

**Files:**
- Modify: `src/resume_tailor_harness/llm_runner.py:244-277` (`build_model`)
- Test: `tests/test_llm_runner_build_model.py` (create)

**Interfaces:**
- Consumes: `provider_capabilities` (Task 1), existing `split_provider`, `resolve_api_key`.
- Produces: `build_model(model_id, api_key=None, *, cache_system_prompt=False, reasoning=False) -> Any` — when `reasoning=True`, attaches the provider-appropriate agno reasoning kwarg (Anthropic `thinking`+`output_config`, OpenAI `reasoning_effort`, Gemini `thinking_level`, DeepSeek `use_thinking`+`reasoning_effort`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_runner_build_model.py`:

```python
from resume_tailor_harness import llm_runner
from resume_tailor_harness.llm_runner import build_model


def test_anthropic_reasoning_attaches_thinking_and_effort():
    model = build_model("claude-sonnet-5", api_key="k", reasoning=True)
    assert model.thinking == {"type": "adaptive"}
    assert model.output_config == {"effort": "high"}


def test_anthropic_no_reasoning_leaves_thinking_unset():
    model = build_model("claude-sonnet-5", api_key="k", reasoning=False)
    assert model.thinking is None


def test_anthropic_cache_flag_forwarded():
    model = build_model("claude-sonnet-5", api_key="k", cache_system_prompt=True)
    assert model.cache_system_prompt is True


def test_openai_reasoning_sets_effort():
    model = build_model("openai:gpt-5", api_key="k", reasoning=True)
    assert model.reasoning_effort == "high"


def test_gemini_reasoning_sets_thinking_level():
    model = build_model("gemini:gemini-3.5-flash", api_key="k", reasoning=True)
    assert model.thinking_level == "high"


def test_deepseek_reasoning_forces_thinking():
    model = build_model("deepseek:deepseek-reasoner", api_key="k", reasoning=True)
    assert model.use_thinking is True
    assert model.reasoning_effort == "max"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -v`
Expected: FAIL — `build_model() got an unexpected keyword argument 'reasoning'`.

- [ ] **Step 3: Write minimal implementation**

Replace `build_model` (lines 244-277) with:

```python
def build_model(
    model_id: str,
    api_key: str | None = None,
    *,
    cache_system_prompt: bool = False,
    reasoning: bool = False,
) -> Any:
    """Construct the agno model for a (possibly provider-prefixed) ``model_id``.

    Provider SDK modules are imported lazily, per branch: a Claude-only run never
    imports ``openai`` or ``google-genai``, and a missing optional SDK fails only
    when that provider is actually selected. ``cache_system_prompt`` is forwarded
    only to Anthropic. ``reasoning`` attaches the provider-appropriate reasoning
    kwarg; callers gate it via ``provider_capabilities`` so an unsupported model
    is never asked to reason.
    """
    provider, model = split_provider(model_id)
    key = api_key or resolve_api_key(model_id) or None
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        kwargs: dict[str, Any] = {}
        if reasoning:
            kwargs["reasoning_effort"] = "high"
        return OpenAIChat(id=model, api_key=key, **kwargs)
    if provider == "gemini":
        from agno.models.google import Gemini

        kwargs = {}
        if reasoning:
            kwargs["thinking_level"] = "high"
        return Gemini(id=model, api_key=key, **kwargs)
    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        kwargs = {}
        if reasoning:
            kwargs["use_thinking"] = True
            kwargs["reasoning_effort"] = "max"
        return DeepSeek(id=model, api_key=key, **kwargs)
    from agno.models.anthropic import Claude

    kwargs = {}
    if reasoning:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "high"}
    return Claude(
        id=model,
        api_key=key,
        cache_system_prompt=cache_system_prompt,
        **kwargs,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/llm_runner.py tests/test_llm_runner_build_model.py
git commit -m "feat(llm): thread reasoning kwarg through build_model per provider"
```

---

### Task 3: Thread reasoning + caching through `build_search_equipped`

**Files:**
- Modify: `src/resume_tailor_harness/llm_runner.py:280-308` (`build_search_equipped`)
- Test: `tests/test_llm_runner_search_equipped.py` (create)

**Interfaces:**
- Consumes: `build_model` (Task 2), existing `plan_search`, `split_provider`, `resolve_api_key`.
- Produces: `build_search_equipped(model_id, mode=None, *, reasoning=False, cache_system_prompt=False) -> tuple[Any, list[Any]]` — reasoning/cache flags reach the native OpenAI/Gemini branches and the Anthropic branch (via `build_model`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_runner_search_equipped.py`:

```python
from resume_tailor_harness.llm_runner import build_search_equipped


def test_anthropic_native_search_forwards_reasoning_and_cache():
    model, tools = build_search_equipped(
        "claude-sonnet-5", mode="native", reasoning=True, cache_system_prompt=True
    )
    assert model.thinking == {"type": "adaptive"}
    assert model.cache_system_prompt is True
    assert tools and tools[0]["name"] == "web_search"


def test_openai_native_search_forwards_reasoning():
    model, _tools = build_search_equipped(
        "openai:gpt-5", mode="native", reasoning=True
    )
    assert model.reasoning_effort == "high"


def test_gemini_native_search_forwards_reasoning():
    model, _tools = build_search_equipped(
        "gemini:gemini-3.5-flash", mode="native", reasoning=True
    )
    assert model.thinking_level == "high"


def test_tool_fallback_still_returns_duckduckgo():
    model, tools = build_search_equipped(
        "deepseek:deepseek-reasoner", mode="tool", reasoning=True
    )
    assert model.use_thinking is True
    assert tools  # DuckDuckGoTools present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_search_equipped.py -v`
Expected: FAIL — `build_search_equipped() got an unexpected keyword argument 'reasoning'`.

- [ ] **Step 3: Write minimal implementation**

Replace `build_search_equipped` (lines 280-308) with:

```python
def build_search_equipped(
    model_id: str,
    mode: SearchMode | None = None,
    *,
    reasoning: bool = False,
    cache_system_prompt: bool = False,
) -> tuple[Any, list[Any]]:
    """Build a model and its search tools for advisor research.

    ``reasoning`` / ``cache_system_prompt`` are best-effort and gated by the
    caller via ``provider_capabilities``; they reach the native OpenAI/Gemini
    branches directly and the Anthropic/tool branches through ``build_model``.
    """
    settings = get_settings()
    plan = plan_search(model_id, mode or settings.search_mode)
    if plan.strategy == "none":
        raise ValueError("advisor web search is disabled by search_mode=off")
    _provider, model_name = split_provider(model_id)
    api_key = resolve_api_key(model_id) or None

    if plan.strategy == "native_openai":
        from agno.models.openai.responses import OpenAIResponses

        kwargs: dict[str, Any] = {}
        if reasoning:
            kwargs["reasoning_effort"] = "high"
        return (
            OpenAIResponses(id=model_name, api_key=api_key, **kwargs),
            [OPENAI_WEB_SEARCH_TOOL],
        )
    if plan.strategy == "native_gemini":
        from agno.models.google import Gemini

        kwargs = {}
        if reasoning:
            kwargs["thinking_level"] = "high"
        return Gemini(id=model_name, api_key=api_key, search=True, **kwargs), []

    model = build_model(
        model_id,
        api_key=api_key,
        reasoning=reasoning,
        cache_system_prompt=cache_system_prompt,
    )
    if plan.strategy == "native_anthropic":
        return model, [ANTHROPIC_WEB_SEARCH_TOOL]
    if plan.strategy == "tool":
        from agno.tools.duckduckgo import DuckDuckGoTools

        return model, [DuckDuckGoTools()]
    raise AssertionError(f"unhandled search strategy: {plan.strategy}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_search_equipped.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/llm_runner.py tests/test_llm_runner_search_equipped.py
git commit -m "feat(llm): thread reasoning/cache through build_search_equipped native branches"
```

---

### Task 4: Source Scout schema + instructions (fit score, avoid, citations)

**Files:**
- Modify: `src/resume_tailor_harness/discovery/source_scout.py`
- Test: `tests/test_source_scout_schema.py` (create)

**Interfaces:**
- Consumes: `ExtensibleModel` (existing), `provider_capabilities` (Task 1), `build_scout_research_agent` (existing signature unchanged; wiring happens in Task 6).
- Produces:
  - `Citation(ExtensibleModel)` with `url: str = ""`, `title: str = ""`.
  - `ScoutCandidate` gains `fit_score: int | None = None`, `signal: Literal["positive","avoid"] = "positive"`, `citations: list[Citation] = Field(default_factory=list)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_source_scout_schema.py`:

```python
from resume_tailor_harness.discovery.source_scout import Citation, ScoutCandidate


def test_candidate_defaults_are_safe():
    c = ScoutCandidate()
    assert c.fit_score is None
    assert c.signal == "positive"
    assert c.citations == []


def test_candidate_accepts_enrichment():
    c = ScoutCandidate(
        company="Acme",
        careers_url="https://acme.com/careers",
        fit_score=82,
        signal="avoid",
        citations=[Citation(url="https://news/x", title="Acme layoffs")],
    )
    assert c.fit_score == 82
    assert c.signal == "avoid"
    assert c.citations[0].title == "Acme layoffs"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_scout_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'Citation'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/discovery/source_scout.py`, replace the `ScoutCandidate` class (currently lines 31-35) and add `Citation` before it:

```python
class Citation(ExtensibleModel):
    url: str = ""
    title: str = ""


class ScoutCandidate(ExtensibleModel):
    company: str = ""
    careers_url: str = ""
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    fit_score: int | None = None
    signal: Literal["positive", "avoid"] = "positive"
    citations: list[Citation] = Field(default_factory=list)
```

Then extend `_RESEARCH_INSTRUCTIONS` (after the existing final bullet) and `_FORMAT_INSTRUCTIONS` to teach scoring/avoid/citations. Append to `_RESEARCH_INSTRUCTIONS`:

```python
    "For each recommendation, give a fit_score from 0-100 estimating how well the "
    "company matches the supplied profile titles/skills, and cite the web result(s) "
    "(url + title) that justify it. When a company shows a clear negative signal "
    "(layoffs, hiring freeze, poor fit), mark it as an AVOID recommendation with its "
    "evidence instead of a board suggestion.",
```

Append to `_FORMAT_INSTRUCTIONS`:

```python
    "Copy fit_score, signal (positive/avoid), and citations verbatim from the notes; "
    "never invent a score or a citation. Set signal to 'avoid' only when the notes "
    "explicitly report a negative signal. Positive rows still need an HTTP(S) URL; "
    "avoid rows may omit it.",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_scout_schema.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/source_scout.py tests/test_source_scout_schema.py
git commit -m "feat(scout): add fit_score, avoid signal, citations to ScoutCandidate"
```

---

### Task 5: Search Scout schema + instructions (new kinds, fit score, citations)

**Files:**
- Modify: `src/resume_tailor_harness/discovery/search_scout.py`
- Test: `tests/test_search_scout_schema.py` (create)

**Interfaces:**
- Consumes: `Citation` from `source_scout` (Task 4), `ExtensibleModel` (existing).
- Produces:
  - `SuggestionKind` extended to include `"location"`, `"seniority"`, `"adjacent_role"`.
  - `SearchSuggestion` gains `fit_score: int | None = None`, `citations: list[Citation] = Field(default_factory=list)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_search_scout_schema.py`:

```python
from resume_tailor_harness.discovery.search_scout import SearchSuggestion
from resume_tailor_harness.discovery.source_scout import Citation


def test_suggestion_defaults_are_safe():
    s = SearchSuggestion()
    assert s.fit_score is None
    assert s.citations == []
    assert s.kind == "keyword"


def test_new_kinds_accepted():
    for kind in ("location", "seniority", "adjacent_role"):
        s = SearchSuggestion(value="x", kind=kind)
        assert s.kind == kind


def test_suggestion_accepts_citation():
    s = SearchSuggestion(
        value="Platform Engineer",
        kind="adjacent_role",
        fit_score=74,
        citations=[Citation(url="https://x", title="demand up")],
    )
    assert s.fit_score == 74
    assert s.citations[0].url == "https://x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_scout_schema.py -v`
Expected: FAIL — `ValidationError` for `kind="location"` (not yet in the Literal).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/discovery/search_scout.py`, update the import and models. Add to the imports at top:

```python
from resume_tailor_harness.discovery.source_scout import Citation
```

Replace the `SuggestionKind` alias and `SearchSuggestion` class (currently lines 32 and 35-38):

```python
SuggestionKind = Literal[
    "keyword",
    "title",
    "role_anchor",
    "exclude_term",
    "location",
    "seniority",
    "adjacent_role",
]


class SearchSuggestion(ExtensibleModel):
    value: str = ""
    kind: SuggestionKind = "keyword"
    reason: str = ""
    fit_score: int | None = None
    citations: list[Citation] = Field(default_factory=list)
```

Append to `_RESEARCH_INSTRUCTIONS` (new bullet):

```python
    "Beyond keywords/titles/anchors/excludes, you may also recommend target locations "
    "(kind=location), seniority levels (kind=seniority), and adjacent or pivot roles the "
    "profile could credibly reach (kind=adjacent_role). Give each a fit_score 0-100 and "
    "cite the web result(s) that justify it.",
```

Append to `_FORMAT_INSTRUCTIONS`:

```python
    "kind is one of keyword, title, role_anchor, exclude_term, location, seniority, "
    "adjacent_role. Copy fit_score and citations verbatim from the notes; never invent them.",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_scout_schema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/search_scout.py tests/test_search_scout_schema.py
git commit -m "feat(scout): add location/seniority/adjacent_role kinds, fit_score, citations"
```

---

### Task 6: Source discovery service — reasoning wiring, ranking, avoid, citation rows

**Files:**
- Modify: `src/resume_tailor_harness/services/source_discovery.py`
- Test: `tests/test_source_discovery_enrichment.py` (create)

**Interfaces:**
- Consumes: `ScoutReport`, `ScoutCandidate`, `Citation` (Task 4); `provider_capabilities`, `build_scout_research_agent` (existing); `_row` (existing helper).
- Produces: `run_source_discovery(...)` returns candidates ranked by fit_score within status groups; `avoid` candidates skip validation and carry `signal`/`fitScore`/`citations` camelCase keys.

- [ ] **Step 1: Write the failing test**

Create `tests/test_source_discovery_enrichment.py`. Use fake research/formatter runners (mirroring the pattern in the existing `run_source_discovery` tests — inject via `research_agent` / `formatter_agent` params):

```python
from types import SimpleNamespace

from resume_tailor_harness.discovery.source_scout import Citation, ScoutCandidate, ScoutReport
from resume_tailor_harness.services import source_discovery


class _FakeRunner:
    def __init__(self, content):
        self._content = content

    def run(self, _prompt):
        return SimpleNamespace(content=self._content)


class _Reporter:
    def begin(self, *a, **k):
        pass

    def step(self, *a, **k):
        pass

    def checkpoint(self, *a, **k):
        pass


def _run(report, tmp_path, monkeypatch):
    # No positive candidate needs real validation: fake preview_source to "validated".
    monkeypatch.setattr(
        source_discovery,
        "preview_source",
        lambda url, **k: source_discovery.SourcePreview(ok=True, url=url),
    )
    return source_discovery.run_source_discovery(
        _Reporter(),
        prompt="p",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=False,
        research_agent=_FakeRunner("notes"),
        formatter_agent=_FakeRunner(report),
    )


def test_avoid_row_skips_validation_and_keeps_signal(tmp_path, monkeypatch):
    report = ScoutReport(
        candidates=[
            ScoutCandidate(
                company="RiskCo",
                careers_url="https://riskco.com/careers",
                signal="avoid",
                fit_score=10,
                citations=[Citation(url="https://news/x", title="layoffs")],
            )
        ]
    )
    out = _run(report, tmp_path, monkeypatch)
    row = out["candidates"][0]
    assert row["signal"] == "avoid"
    assert row["status"] == "avoid"
    assert row["fitScore"] == 10
    assert row["citations"] == [{"url": "https://news/x", "title": "layoffs"}]


def test_positive_rows_ranked_by_fit_score(tmp_path, monkeypatch):
    report = ScoutReport(
        candidates=[
            ScoutCandidate(company="Low", careers_url="https://low.com/careers", fit_score=30),
            ScoutCandidate(company="High", careers_url="https://high.com/careers", fit_score=90),
        ]
    )
    out = _run(report, tmp_path, monkeypatch)
    companies = [r["company"] for r in out["candidates"]]
    assert companies == ["High", "Low"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_discovery_enrichment.py -v`
Expected: FAIL — `KeyError: 'signal'` (the `_row` dict has no signal/fitScore/citations yet) and ranking not applied.

- [ ] **Step 3: Write minimal implementation**

Three edits in `src/resume_tailor_harness/services/source_discovery.py`.

**(a)** Extend `_row` (lines 118-130) to emit the new camelCase keys and a citation serializer:

```python
def _row(candidate: ScoutCandidate, preview: SourcePreview | None, status: str) -> dict:
    return {
        "company": candidate.company,
        "url": preview.url if preview is not None else candidate.careers_url,
        "reason": candidate.reason,
        "confidence": candidate.confidence,
        "status": status,
        "signal": candidate.signal,
        "fitScore": candidate.fit_score,
        "citations": [
            {"url": c.url, "title": c.title} for c in candidate.citations
        ],
        "ats": preview.kind if preview is not None else None,
        "token": preview.token if preview is not None else None,
        "roleCount": preview.role_count if preview is not None else None,
        "error": preview.error if preview is not None and status == "failed" else None,
        "errorCode": preview.error_code if preview is not None else None,
    }
```

**(b)** In `run_source_discovery`, after building `candidates` (line ~156) and before the dedupe loop, split avoid rows out so they never enter validation. Replace the dedupe-loop preamble (lines 159-168) with:

```python
    seen = _existing_keys(_load_connectors(connectors_path))
    rows: list[dict | None] = [None] * len(candidates)
    fresh: list[tuple[int, ScoutCandidate]] = []
    for index, candidate in enumerate(candidates):
        if candidate.signal == "avoid":
            rows[index] = _row(candidate, None, "avoid")
            continue
        keys = _candidate_keys(candidate.careers_url)
        if keys & seen:
            rows[index] = _row(candidate, None, "duplicate")
        else:
            seen.update(keys)
            fresh.append((index, candidate))
```

**(c)** At the end of `run_source_discovery`, replace the final `return` (lines 208-215) so the candidate list is ranked. Insert a ranking helper before the return:

```python
    _STATUS_ORDER = {"validated": 0, "unverified": 1, "avoid": 2, "failed": 3, "duplicate": 4}

    def _rank_key(row: dict) -> tuple[int, int]:
        status_rank = _STATUS_ORDER.get(row["status"], 5)
        # Higher fitScore first; None sorts last within a status group.
        score = row["fitScore"]
        score_rank = -score if isinstance(score, int) else 1
        return (status_rank, score_rank)

    ranked = sorted((row for row in rows if row is not None), key=_rank_key)
    scrape_available = (
        get_settings().browser_enabled if browser_enabled is None else browser_enabled
    )
    return {
        "prompt": prompt,
        "candidates": ranked,
        "scrapeAvailable": scrape_available,
        "scrapeUnavailableReason": (
            None if scrape_available else "Scrape targets require a local browser."
        ),
    }
```

(Define `_STATUS_ORDER` at module level instead of inline if preferred; keeping it near the return is acceptable for this single use.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_discovery_enrichment.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the existing source-discovery tests to confirm no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "source_discovery" -v`
Expected: PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/services/source_discovery.py tests/test_source_discovery_enrichment.py
git commit -m "feat(scout): rank source candidates, skip validation for avoid rows, emit citations"
```

---

### Task 7: Search discovery service — new-kind dedupe, ranking, citation rows

**Files:**
- Modify: `src/resume_tailor_harness/services/search_discovery.py`
- Test: `tests/test_search_discovery_enrichment.py` (create)

**Interfaces:**
- Consumes: `SearchSuggestions`, `SearchSuggestion`, `Citation` (Task 5); existing `_EXISTING_FIELD`, `run_search_discovery` signature.
- Produces: `run_search_discovery(...)` rows carry `fitScore`/`citations` camelCase keys, dedupe `location→locations` and `adjacent_role→titles`, always mark `seniority` as `new`, and rank by fit_score.

- [ ] **Step 1: Write the failing test**

Create `tests/test_search_discovery_enrichment.py`:

```python
from types import SimpleNamespace

from resume_tailor_harness.discovery.search_scout import SearchSuggestion, SearchSuggestions
from resume_tailor_harness.discovery.source_scout import Citation
from resume_tailor_harness.services import search_discovery


class _FakeRunner:
    def __init__(self, content):
        self._content = content

    def run(self, _prompt):
        return SimpleNamespace(content=self._content)


class _Reporter:
    def begin(self, *a, **k):
        pass

    def step(self, *a, **k):
        pass


def _run(report, tmp_path):
    return search_discovery.run_search_discovery(
        _Reporter(),
        prompt="p",
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        research_agent=_FakeRunner("notes"),
        formatter_agent=_FakeRunner(report),
    )


def test_new_kinds_and_citations_flow_through(tmp_path):
    report = SearchSuggestions(
        suggestions=[
            SearchSuggestion(
                value="Berlin",
                kind="location",
                fit_score=60,
                citations=[Citation(url="https://x", title="hub")],
            ),
            SearchSuggestion(value="Staff", kind="seniority", fit_score=80),
        ]
    )
    out = _run(report, tmp_path)
    by_value = {r["value"]: r for r in out["suggestions"]}
    assert by_value["Berlin"]["kind"] == "location"
    assert by_value["Berlin"]["citations"] == [{"url": "https://x", "title": "hub"}]
    # seniority has no search.yaml field -> always new.
    assert by_value["Staff"]["status"] == "new"


def test_ranked_by_fit_score(tmp_path):
    report = SearchSuggestions(
        suggestions=[
            SearchSuggestion(value="low", kind="keyword", fit_score=20),
            SearchSuggestion(value="high", kind="keyword", fit_score=95),
        ]
    )
    out = _run(report, tmp_path)
    assert [r["value"] for r in out["suggestions"]] == ["high", "low"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_discovery_enrichment.py -v`
Expected: FAIL — row dict has no `fitScore`/`citations`, and ranking not applied.

- [ ] **Step 3: Write minimal implementation**

Edit `src/resume_tailor_harness/services/search_discovery.py`. The `_EXISTING_FIELD` map (lines 25-30) already covers keyword/title/role_anchor/exclude_term; `location` and `adjacent_role` need dedupe targets, `seniority` intentionally none. Replace the row-building loop and return (lines 103-121) with:

```python
    existing = _existing_terms(search_path)
    # Dedupe targets for the broadened kinds; kinds absent here never dedupe.
    dedupe_kind_field = {
        "keyword": "keywords",
        "title": "titles",
        "role_anchor": "role_anchors",
        "exclude_term": "exclude_terms",
        "location": "locations",
        "adjacent_role": "titles",
    }
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for suggestion in report.suggestions[:MAX_SUGGESTIONS]:
        value = suggestion.value.strip()
        if not value:
            continue
        kind = suggestion.kind
        fold = value.casefold()
        dedupe_key = (kind, fold)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        field = dedupe_kind_field.get(kind)
        status = "duplicate" if field and fold in existing.get(kind, set()) else "new"
        rows.append(
            {
                "value": value,
                "kind": kind,
                "reason": suggestion.reason,
                "status": status,
                "fitScore": suggestion.fit_score,
                "citations": [
                    {"url": c.url, "title": c.title} for c in suggestion.citations
                ],
            }
        )
    rows.sort(
        key=lambda r: -r["fitScore"] if isinstance(r["fitScore"], int) else 1
    )
    reporter.step(1)
    return {"prompt": prompt, "suggestions": rows}
```

Also update `_existing_terms` (lines 74-82): it currently iterates `_EXISTING_FIELD`; `location` must dedupe against `search.locations`. Change the map it walks so `location → locations` is available. Replace `_existing_terms` with a version keyed by the broadened map:

```python
_DEDUPE_KIND_FIELD = {
    "keyword": "keywords",
    "title": "titles",
    "role_anchor": "role_anchors",
    "exclude_term": "exclude_terms",
    "location": "locations",
    "adjacent_role": "titles",
}


def _existing_terms(search_path: str) -> dict[str, set[str]]:
    try:
        search = load_search_config(search_path)
    except (OSError, ValueError):
        return {kind: set() for kind in _DEDUPE_KIND_FIELD}
    return {
        kind: {term.casefold() for term in getattr(search, field, [])}
        for kind, field in _DEDUPE_KIND_FIELD.items()
    }
```

Then in the loop, replace the local `dedupe_kind_field` with the module-level `_DEDUPE_KIND_FIELD` (remove the duplicate local definition; use `_DEDUPE_KIND_FIELD.get(kind)`). Remove the now-unused `_EXISTING_FIELD` constant (lines 25-30) if nothing else references it — grep first: `grep -rn "_EXISTING_FIELD" src/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_discovery_enrichment.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run existing search-discovery tests**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "search_discovery" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/services/search_discovery.py tests/test_search_discovery_enrichment.py
git commit -m "feat(scout): broaden search suggestion kinds, dedupe, rank, and cite"
```

---

### Task 8: Wire capability-gated reasoning + caching into both research agents

**Files:**
- Modify: `src/resume_tailor_harness/discovery/source_scout.py` (`build_scout_research_agent`)
- Modify: `src/resume_tailor_harness/discovery/search_scout.py` (`build_search_scout_research_agent`)
- Test: `tests/test_scout_research_agent_wiring.py` (create)

**Interfaces:**
- Consumes: `provider_capabilities`, `build_search_equipped` (with `reasoning`/`cache_system_prompt`, Tasks 1 & 3).
- Produces: both research-agent builders pass `reasoning=caps.supports_reasoning`, `cache_system_prompt=caps.supports_prompt_cache` into `build_search_equipped`, resolved from `settings.mid_model`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scout_research_agent_wiring.py`. Assert the builder forwards capability-derived flags by spying on `build_search_equipped`:

```python
from resume_tailor_harness.discovery import search_scout, source_scout


def test_source_research_agent_forwards_reasoning_and_cache(monkeypatch):
    captured = {}

    def fake_build(model_id, mode=None, *, reasoning=False, cache_system_prompt=False):
        captured["reasoning"] = reasoning
        captured["cache"] = cache_system_prompt
        return object(), []

    monkeypatch.setattr(source_scout, "build_search_equipped", fake_build)
    # mid_model default is claude-sonnet-5 -> reasoning + cache both True.
    source_scout.build_scout_research_agent(lambda url: "{}")
    assert captured == {"reasoning": True, "cache": True}


def test_search_research_agent_forwards_reasoning_and_cache(monkeypatch):
    captured = {}

    def fake_build(model_id, mode=None, *, reasoning=False, cache_system_prompt=False):
        captured["reasoning"] = reasoning
        captured["cache"] = cache_system_prompt
        return object(), []

    monkeypatch.setattr(search_scout, "build_search_equipped", fake_build)
    search_scout.build_search_scout_research_agent()
    assert captured == {"reasoning": True, "cache": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scout_research_agent_wiring.py -v`
Expected: FAIL — builders call `build_search_equipped(settings.mid_model)` with no reasoning/cache kwargs, so `captured == {"reasoning": False, "cache": False}`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/discovery/source_scout.py`, add to the `llm_runner` import list `provider_capabilities`, then replace `build_scout_research_agent` (lines 98-110) body's model construction:

```python
def build_scout_research_agent(check_source: Callable[[str], str]) -> Runner:
    settings = get_settings()
    caps = provider_capabilities(settings.mid_model)
    model, search_tools = build_search_equipped(
        settings.mid_model,
        reasoning=caps.supports_reasoning,
        cache_system_prompt=caps.supports_prompt_cache,
    )
    return AgentRunner(
        Agent(
            model=model,
            tools=[*search_tools, check_source],
            description="Research careers boards matching a user's company prompt.",
            instructions=with_guidance("source-scout-research", _RESEARCH_INSTRUCTIONS),
            **tool_kwargs(),
            **retry_kwargs(),
        )
    )
```

In `src/resume_tailor_harness/discovery/search_scout.py`, add `provider_capabilities` to the `llm_runner` import list, then replace `build_search_scout_research_agent` (lines 64-76) model construction:

```python
def build_search_scout_research_agent() -> Runner:
    settings = get_settings()
    caps = provider_capabilities(settings.mid_model)
    model, search_tools = build_search_equipped(
        settings.mid_model,
        reasoning=caps.supports_reasoning,
        cache_system_prompt=caps.supports_prompt_cache,
    )
    return AgentRunner(
        Agent(
            model=model,
            tools=[*search_tools],
            description="Research search conditions matching a user's profile and goal.",
            instructions=with_guidance("search-scout-research", _RESEARCH_INSTRUCTIONS),
            **tool_kwargs(),
            **retry_kwargs(),
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scout_research_agent_wiring.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/source_scout.py src/resume_tailor_harness/discovery/search_scout.py tests/test_scout_research_agent_wiring.py
git commit -m "feat(scout): gate research-agent reasoning/caching via provider_capabilities"
```

---

### Task 9: Full-suite verification + lint

**Files:**
- Verification task after the backend and in-repository `web/` scout UI changes from
  Correctness Amendment 10 are complete.

- [ ] **Step 1: Run the full offline suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (all existing + new tests; no network, no key).

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: no errors. Fix any (e.g. unused `_EXISTING_FIELD` import if it lingered, or unused `Literal` imports).

- [ ] **Step 3: Confirm no raw provider-SDK import leaked outside the seam**

Run: `grep -rn "from agno.models" src/resume_tailor_harness/ | grep -v llm_runner.py`
Expected: no output (all agno model imports stay in `llm_runner.py`).

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A
git commit -m "chore(scout): lint cleanup after enrichment"
```

---

## Notes for the executor

- **Ranking `None` scores sort last** within a status group — this is deliberate (a scored recommendation outranks an unscored one).
- **`avoid` rows never hit the URL probe** — they carry evidence only. The in-repository
  web layer renders them as non-selectable advisory rows in this implementation.
- **Caching is cost-only.** Do not add a test that asserts a cache hit — the offline suite fakes the model, so there is no real cache to read. Task 3 asserts the *kwarg is attached*, which is the correct offline boundary.
- **DeepSeek path is exercised only at the capability/build layer** (Tasks 1-3). No live DeepSeek call is made anywhere in the suite.
- If `settings.mid_model` is ever configured to a Haiku or `deepseek-chat` id, Task 8's wiring correctly passes `reasoning=False` — the research agent still runs, just without a deliberation budget.
