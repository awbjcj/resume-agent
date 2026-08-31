# Scout Agent Enhancement — Design

**Date:** 2026-07-22
**Status:** Approved with correctness amendments; implementation in progress
**Scope:** Enhance the two agno-backed advisor agents — **Source Scout** (recommends
companies / careers-board URLs) and **Search Scout** (recommends keywords / titles /
role-anchors / exclude-terms) — to produce ranked, web-cited, multi-axis
recommendations, exploiting provider-native LLM capabilities across Anthropic,
OpenAI, Gemini, and DeepSeek.

## Goal

Make the scouts genuinely good advisors along three axes the user selected:

1. **Smarter recommendations** — ranked by profile fit, evidence-cited, not flat lists.
2. **Exploit provider-native features** — extended thinking/reasoning, prompt caching,
   structured outputs, web-search citations.
3. **Broaden what they recommend** — fit score + rationale per item, new recommendation
   types (adjacent/pivot roles, target locations & seniority, companies-to-avoid),
   web-cited evidence.

Explicitly **out of scope**: coordinated source+term bundles (the two scouts stay
independent), and any third LLM stage (fast-by-default posture preserved).

## Correctness amendments

The implementation audit found contract mismatches between the initial design, the
plan, and the running application. These rules are binding:

- Capability probing is conservative for unknown prefixes and unknown model families,
  and model builders re-check capabilities before attaching requested reasoning kwargs.
- Gemini native search uses Agno's Interactions wrapper with `store=False`; OpenAI
  Responses search also sets `store=False`. The scouts are single-turn and must not
  opt profile context into provider-side conversation retention merely to gain search.
- Provider runtime failures retain the existing bounded retry/error semantics. Only
  unsupported capabilities degrade pre-call; there is no hidden second LLM call.
- `Citation` is a shared scout model, HTTP(S)-only at the service boundary, and both
  fit-score fields are validated in the inclusive range 0-100.
- URL-less explicit `avoid` recommendations are retained and never probed. Positive
  source recommendations still require a careers URL.
- Search kinds map to persisted config fields: `location -> locations`,
  `adjacent_role -> titles`, `seniority -> experience_levels`; seniority uses the
  existing LinkedIn value vocabulary. Dedupe follows the destination field.
- Scout results are nested inside generic `RunOut.result: Any`; the unrelated
  match-gap suggestion schemas are not their contract. Update the service row shapes
  and the web client's local types/components/tests. A typed run-result/OpenAPI
  redesign remains out of scope.
- The existing web dialogs are part of this feature: they render rank/evidence/avoid
  state and can apply every actionable suggestion kind with accessible, base-nova
  shadcn composition.

## Structural decision

**Enrich the existing `research → format` two-agent pattern in place**, plus one new
shared capability seam in `llm_runner.py`. No new pipeline, no third "judge" call, no
unification refactor. Fit-scoring and avoid-judgment run **inside** the
reasoning-enabled research agent; the cheap formatter stays un-thought.

## The load-bearing constraint: DeepSeek forces best-effort everywhere

Provider capabilities are not uniform, and two facts drive the whole design:

- **Reasoning is model-gated, not just provider-gated.** The `mid_model` (Sonnet 5)
  supports adaptive thinking + `effort`; the `cheap_model` (**Haiku 4.5**) supports
  **neither** (`effort`/`budget_tokens` error on it). DeepSeek reasoning is a *separate
  model* (`deepseek-reasoner`), not a toggle on `deepseek-chat`.
- **DeepSeek has no native web search**, so it already falls through to the DuckDuckGo
  tool path, which yields no structured citations.

Therefore every enhancement (reasoning, citations) must be **optional and
capability-probed**, with a clean fallback. A provider lacking a feature must still
produce valid, un-enriched output.

---

## 1. Architecture & the capability seam

Both scouts keep `research → format`. The intelligence and provider-native features are
added **inside** those two existing agents, plus **one new seam** in `llm_runner.py`:

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_reasoning: bool
    supports_native_citations: bool
    supports_prompt_cache: bool

def provider_capabilities(model_id: str) -> ProviderCapabilities: ...
```

- Resolves via the existing `split_provider` + `plan_search`.
  - **Anthropic / OpenAI / Gemini** → full caps (reasoning only on models that support
    it — Haiku 4.5 → `reasoning=False`).
  - **DeepSeek** → `reasoning=True` only when the resolved id is a reasoner model;
    `citations=False` (no native search); `cache=True` (implicit caching).
  - **Unknown provider / unknown prefix** → all-`False` (conservative).
- `build_search_equipped`, `build_scout_research_agent`, and
  `build_search_scout_research_agent` consult it to decide which agno model kwargs to
  attach (thinking/effort, cache directives).
- **Never raises.** A resolution failure returns the conservative all-`False` value.

This is the **only** place feature-gating lives, so DeepSeek's fallback (and every
future provider's) is defined once.

## 2. Schema extensions (both scouts, additive)

A new shared model:

```python
class Citation(ExtensibleModel):
    url: str = ""
    title: str = ""
```

`ScoutCandidate` (`discovery/source_scout.py`) gains:

- `fit_score: int | None = None` — 0–100, agent-judged against the supplied
  profile/search context; `None` when the model does not provide one.
- `signal: Literal["positive", "avoid"] = "positive"` — `avoid` marks a
  company-to-skip (layoffs, hiring freeze, poor fit). Display-only: an `avoid` row is
  **never validated and never added as a source**.
- `citations: list[Citation] = Field(default_factory=list)` — from native web search;
  `[]` on DeepSeek/DuckDuckGo.

`SearchSuggestion` (`discovery/search_scout.py`):

- `SuggestionKind` extended to
  `Literal["keyword", "title", "role_anchor", "exclude_term", "location", "seniority", "adjacent_role"]`.
- `fit_score: int | None = None`
- `citations: list[Citation] = Field(default_factory=list)`

All new fields are default-safe so the cheap formatter degrades cleanly when a provider
supplies nothing.

## 3. Provider-native feature mapping

| Feature | Anthropic | OpenAI | Gemini | DeepSeek | Where it attaches |
|---|---|---|---|---|---|
| Reasoning on **research** agent | Sonnet-5 adaptive thinking + `effort` | reasoning-effort | thinking budget | `deepseek-reasoner` only | research builder, gated by cap |
| Reasoning on **formatter** | ❌ Haiku 4.5 no effort | n/a | n/a | n/a | never enabled |
| Prompt caching of grounding block | `cache_control` | implicit | implicit | implicit | context assembly (stable prefix) |
| Native citations | web_search | web_search | `search=True` | ❌ → `[]` | research → notes → formatter |
| Structured output | agno `output_schema` (already) | same | same | same | formatter (unchanged) |

- **Fit-scoring + avoid-judgment run inside the reasoning-enabled research agent** — no
  third LLM call. When reasoning is unavailable (Haiku formatter, `deepseek-chat`,
  unknown provider) the research agent still scores, just without a deliberation budget.
- **Prompt caching**: Anthropic's stable system/tool prefix is marked cacheable;
  OpenAI/Gemini/DeepSeek may use their provider-managed implicit caches. Per-run profile
  grounding stays in the user message because it changes by workspace/run and must not
  be mistaken for a reusable system prefix. Caching is **cost-only** — correctness never
  depends on a cache hit, and a `cache_read == 0` outcome is not a failure.
- All four features are **best-effort**; a provider lacking one produces valid,
  un-enriched output.
- All model-feature kwargs are attached through **agno** model params via the
  `build_model` / `build_search_equipped` seam — never raw provider SDKs.

## 4. Service-layer flow

Changes in `services/source_discovery.py` and `services/search_discovery.py`:

- `scout_context` / `scout_search_context` remain the context producers and stay in the
  per-run user message. The stable research instructions and tool definitions form the
  only explicitly cacheable Anthropic prefix.
- **Ranking**: sort by `fit_score` descending within each status group. Source Scout
  status precedence: `validated` > `unverified` > `avoid` > `failed` > `duplicate`;
  Search Scout: `new` > `duplicate`. `None` scores sort last within their group.
- **Validation fan-out runs only on `positive` candidates.** `avoid` rows skip the URL
  probe entirely and are returned with their citations + rationale, no ATS/reachability
  fields.
- **Dedupe and apply targets for new kinds** (extends `_EXISTING_FIELD`):
  - `location → search.locations`
  - `adjacent_role → search.titles`
  - `seniority → search.experience_levels` using the existing LinkedIn vocabulary.
  In-run dedupe is by destination field plus folded value, not by presentation kind.
- **Citations flow** research → formatter as untrusted data; the formatter copies them
  verbatim and never invents — the existing fact-lock / untrusted-notes discipline is
  preserved. Set `fit_score` high-confidence only when the notes explicitly support it,
  mirroring the current "confidence high only on explicit check_source success" rule.

## 5. API and web contract

- Scout completion data remains an additive camelCase dict nested in generic
  `RunOut.result: Any`. Do not modify `api/schemas/suggestions.py`; it belongs to the
  separate match-gap advisor.
- Update the local web consumer types and both scout dialogs in the same change as the
  service rows. Those types are the concrete checked consumer contract for this
  intentionally generic run-result payload.
- `tests/api/test_openapi_contract.py` must remain green and the generated contract must
  remain unchanged. A separately designed typed-run-result union would be required
  before OpenAPI could describe result shapes by run kind.
- The response additions are backward-compatible: no existing key is removed or renamed.

## 6. Error handling

- **Capability probe**: never raises; unknown/unresolvable → conservative all-`False`.
- **Reasoning failure/timeout**: handled by the existing bounded `AgentRunner`
  `is_transient` retry policy. If retries are exhausted the run fails normally; there is
  no hidden fallback request without reasoning.
- **Citations absent** (DeepSeek/DuckDuckGo, or provider returned none): `citations=[]`,
  the rationale stands alone. No hard failure.
- **Caching**: cost-only; `cache_read == 0` is never treated as an error.
- **Fit score**: agent-produced, bounded 0–100, `None` when absent; the formatter must
  not fabricate a score.
- Existing per-URL failure isolation (Source Scout validation) and the
  `TypeError`-on-wrong-report-type guards are unchanged.

## 7. Testing (offline)

Matches the existing suite: all agent calls and the Playwright browser are faked; no API
key, no network.

- **Unit-test `provider_capabilities`** across all four providers plus an unknown prefix,
  including the DeepSeek `reasoner`-vs-`chat` split and Haiku-4.5-no-reasoning.
- **Faked research/formatter agents** return notes carrying citations, fit scores,
  `avoid` signals, and new-kind suggestions; assert:
  - ranking by `fit_score` within status groups,
  - `avoid` rows skip the validation fan-out,
  - dedupe/apply mapping of `location`, `adjacent_role`, and canonical `seniority`,
  - citation passthrough (formatter copies verbatim).
- **Capability-mapping assertions**: verify *which* agno model kwargs get attached per
  provider+model (reasoning on research-with-capable-model, never on formatter, cache
  directive on the stable prefix). Caching/citation *capture* is asserted at this
  mapping layer, not against a live provider.
- Contract drift gate (`test_openapi_contract.py`) green after regeneration.

## Files touched

| Path | Change |
|---|---|
| `src/resume_tailor_harness/llm_runner.py` | New `provider_capabilities` seam + `ProviderCapabilities`; builders attach gated kwargs |
| `src/resume_tailor_harness/discovery/scout_models.py` | Shared citation value model |
| `src/resume_tailor_harness/discovery/source_scout.py` | `Citation`, `ScoutCandidate` fields (`fit_score`, `signal`, `citations`); research instructions for scoring/avoid/citations |
| `src/resume_tailor_harness/discovery/search_scout.py` | New `SuggestionKind`s, `fit_score`, `citations`; research instructions |
| `src/resume_tailor_harness/services/source_discovery.py` | Ranking, avoid-skips-validation, citation rows |
| `src/resume_tailor_harness/services/search_discovery.py` | Ranking, new-kind dedupe, citation rows |
| `web/src/features/sources/*` | Typed enriched Source Scout rows and accessible evidence/avoid UI |
| `web/src/features/search-scout/*` | Typed enriched Search Scout rows, grouping, evidence, and apply mapping |
| `tests/` | Capability probe unit tests; enriched scout service tests |

## Non-goals / preserved invariants

- Two scouts stay independent (no coordinated bundles).
- No third LLM stage; fast-by-default posture intact.
- Fact-lock discipline: notes/citations are untrusted data; the formatter copies, never
  invents; `avoid`/`fit_score` are advisory display metadata and never write to
  `facts.json` or gate anything.
- All provider access remains behind the `build_model` seam (no raw SDK imports added).
