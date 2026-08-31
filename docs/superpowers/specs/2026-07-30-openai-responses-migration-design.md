# OpenAI: migrate agno agents from `/v1/chat/completions` to `/v1/responses`

**Date:** 2026-07-30
**Status:** Approved, pending implementation plan
**Scope:** `src/resume_tailor_harness/llm_runner.py` (OpenAI provider branch only)

---

## Problem

`build_model()` builds every OpenAI agent on agno's `OpenAIChat`, which calls
`/v1/chat/completions`. That endpoint rejects function tools whenever the model
picks its own reasoning effort:

> `Function tools with reasoning_effort are not supported for gpt-5.6-terra in
> /v1/chat/completions. To use function tools, use /v1/responses or set
> reasoning_effort to 'none'.`

The codebase took the second branch of that advice. `_openai_disabled_effort()`
forces `reasoning_effort="none"` on every non-reasoning OpenAI agent, and its
docstring records the consequence: leaving effort unset "broke every tool-using
agent -- the coach and the interviewer -- outright."

Two costs follow.

1. **`gpt-5.5-pro` cannot use function tools at all.** Its `MODEL_CATALOG` entry
   declares `("medium", "high", "xhigh")` and no `"none"`, so there is no effort
   value that both the model and chat/completions accept. Sending a `"none"` it
   does not support would trade one 400 for another.
2. **Reasoning and tools are mutually exclusive on OpenAI.** Any agent that
   needs tools is clamped to no reasoning, regardless of the tier picker's
   configured effort.

`/v1/responses` has neither restriction, and OpenAI's migration guide reports it
is the better endpoint for this case: "Responses has better tool usage support
with reasoning models."

`OpenAIResponses` is already in the codebase — but only in
`build_search_equipped()`'s `native_openai` branch, for web search. The main
agent path never reaches it.

## Goal

Route every OpenAI agent through `/v1/responses` so that reasoning effort and
function tools coexist, and so the configured effort reaches the wire verbatim.

## Non-goals

- No change to Anthropic, Gemini, or DeepSeek branches.
- No change to the ~24 modules that call `build_model()`; they only ever see the
  returned object.
- No refactor toward a per-provider builder protocol. That reworks four
  providers to solve a problem in one.
- No new user-facing setting. The migration is unconditional.

---

## Decisions

| Question | Decision |
|---|---|
| Scope | All OpenAI agents, unconditionally. One code path. |
| Statefulness | `store=false` plus agno's automatic encrypted-reasoning replay. |
| Effort for non-reasoning agents | The lowest effort that model's catalog entry declares. |
| Effort for uncatalogued custom ids | Unset — no `reasoning` parameter sent. |
| Output cap | Explicit `max_output_tokens`, mirroring `_anthropic_max_tokens`. |

---

## Architecture

One new private seam holds every OpenAI request-shaping rule:

```python
def _build_openai_responses(
    model_id: str, *, api_key: str | None, reasoning: bool
) -> Any:
```

It instantiates the compatibility subclass described below, never
`OpenAIResponses` directly, and resolves effort, output cap, and `store` from
the rules that follow. When `_openai_effort()` yields `None` it passes
`reasoning=None`; the shim then removes the empty dict agno would otherwise
emit.

Exactly two callers, and no other OpenAI construction site remains:

| Caller | Before | After |
|---|---|---|
| `build_model()`, openai branch | `CompatibleOpenAIChat(...)` | `_build_openai_responses(model_id, api_key=key, reasoning=reasoning)` |
| `build_search_equipped()`, `native_openai` | inline `OpenAIResponses(...)` | `_build_openai_responses(...)`, plus `[OPENAI_WEB_SEARCH_TOOL]` |

Collapsing the search branch is part of the migration, not extra scope. Today it
carries its own effort mapper that the main path does not use; leaving it
separate would mean the search path silently missing the new effort floor and
output cap, which is the same drift that produced the current divergence.

### Deleted

- `_openai_disabled_effort()` — the `reasoning_effort="none"` clamp. Its only
  reason to exist was the chat/completions restriction.
- `_openai_responses_reasoning_effort_for()` and the
  `OpenAIResponsesReasoningEffort` Literal — the lossy `xhigh -> high`,
  `max -> high`, `none -> None` down-mapping.
- `_compatible_openai_chat_class()` and `CompatibleOpenAIChat` — no caller
  remains. `_without_ref_siblings` stays; Gemini still uses it.

### Unchanged

`use_json_mode_for()` (both agno classes set
`supports_native_structured_outputs = True`, so OpenAI keeps strict structured
outputs and only DeepSeek and oversized Claude schemas fall to JSON mode),
`provider_capabilities()`, `resolve_api_key()`, `split_provider()`,
`MODEL_CATALOG`, `expect_schema`, `expect_text`, and `AgentRunner`'s retry
behaviour.

---

## Request-shaping rules

### 1. Reasoning effort

```python
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
```

`_openai_effort(model_id, *, reasoning) -> str | None`:

- No catalog entry, or an entry declaring no efforts, returns `None`. An
  uncatalogued id typed into the tier picker's custom field has no known
  vocabulary, so nothing is sent. This is safe on Responses in a way it was not
  on chat/completions, because a provider-chosen effort no longer breaks tools.
- `reasoning=True` returns `_reasoning_effort_for()`'s result when the entry
  declares it. Otherwise it chooses the nearest declared value in
  `_EFFORT_ORDER`, preferring the lower effort on a tie. That makes the future
  model fallback deterministic without unexpectedly jumping to the model's
  most expensive effort.
- `reasoning=False` returns the entry's floor,
  `min(entry.reasoning_efforts, key=_EFFORT_ORDER.index)`. Ordering comes from
  the explicit table, not from declaration order in `MODEL_CATALOG`.

Worked examples:

| Model | Catalog efforts | Non-reasoning | Reasoning (unconfigured) |
|---|---|---|---|
| `gpt-5.6-terra` | none, low, medium, high, xhigh, max | `none` | `high` |
| `gpt-5.5-pro` | medium, high, xhigh | `medium` | `high` |
| `gpt-5.4-mini` | none, low, medium, high, xhigh | `none` | `high` |
| custom id | — | unset | unset |

`gpt-5.5-pro` gains working function tools for the first time.

**The effort is passed as `reasoning={"effort": ...}`, not
`reasoning_effort=...`.** agno annotates `OpenAIResponses.reasoning_effort` as
`Literal["minimal", "low", "medium", "high"]`, so `"none"`, `"xhigh"`, and
`"max"` would fail the repo's pyright gate. The `reasoning` field is
`Optional[Dict[str, Any]]`, and `_set_reasoning_request_param` merges it
verbatim into the request, so the untyped field is both the legal and the more
capable route. OpenAI's reasoning guide lists `none`, `minimal`, `low`,
`medium`, `high`, `xhigh`, and `max` as valid values, model-dependent — the
exact vocabulary `MODEL_CATALOG` already declares per model, which is why the
down-mapping can be deleted rather than rewritten.

### 2. Output cap

```python
def _openai_max_output_tokens(*, reasoning: bool) -> int:
    return 32000 if reasoning else 16000
```

On Responses, `max_output_tokens` caps reasoning **plus** visible output — the
same trap `_anthropic_max_tokens` documents for Claude's `max_tokens`, where an
8192 default shared between a thinking budget and a full JSON body truncated
large structured outputs into an unparsed `str`. The OpenAI branch sets no cap
today; enabling reasoning on agents that previously had it clamped off raises
that risk, so the guard lands with the migration.

Simpler than the Anthropic version in one respect: there is no per-model
non-streaming ceiling constant to clamp against, so no SDK lookup.

*Stated assumption:* 32000 is untested against `max` effort on a large
`ResumeContent`. If truncation appears it surfaces as `UnparsedAgentOutput` with
`expect_schema`'s tail preview showing the cut, and the fix is one constant. An
effort-scaled cap is deliberately not pre-tuned on speculation.

### 3. Statefulness

`store=False`, unconditionally. This disables provider-managed response state;
it is not a broader data-retention guarantee. agno then appends
`reasoning.encrypted_content` to `include` for any `gpt-5*`, `o3*`, or
`o4-mini*` id, so reasoning items survive across tool-call turns without manual
wiring and matches what `build_search_equipped` already does.

**Cost consequence:** replayed encrypted reasoning items bill as *input* tokens
on every subsequent tool turn. `tenancy/usage.py` reads `input_tokens`
generically and will count them correctly, but multi-tool agents (coach,
interviewer, both scouts) will show higher per-run input token counts after this
lands. That is expected behaviour, not a regression in the cost-quota work in
flight on this branch.

---

## Compatibility shim

`_compatible_openai_responses_class()` replaces
`_compatible_openai_chat_class()`. It subclasses `OpenAIResponses` and overrides
`get_request_params` — matching Responses' signature, which takes `messages`
first, unlike `OpenAIChat`'s. It does two things.

**1. Strips `$ref` siblings** at `params["text"]["format"]["schema"]`.

Still required: agno's `sanitize_response_schema` handles
`additionalProperties`, `required`, and null defaults, but does not remove
keywords that sit beside `$ref`. Only the JSON path moves — Responses flattens
the schema out of `response_format.json_schema` into `text.format`.

**2. Drops an empty `reasoning` dict.**

agno's `_set_reasoning_request_param` always assigns the key:

```python
base_params["reasoning"] = self.reasoning or {}
...
request_params = {k: v for k, v in base_params.items() if v is not None}
```

`{}` is not `None`, so it survives the filter and **every** Responses request
carries `reasoning: {}`. That is invisible today because the only Responses
caller is the search path on `gpt-5.x` ids. Once `build_model` routes all OpenAI
ids here, a custom non-reasoning id from the tier picker's free-text field
(e.g. `openai:gpt-4.1`) would carry a reasoning parameter it cannot honour.
Popping the key when falsy is what makes the "uncatalogued means unset" rule
above actually mean unset.

---

## Error handling

No new machinery. Provider rejections continue to arrive as agno
`RunOutput.status = ERROR` with the error body assigned to `content` as a plain
`str`; `expect_schema` and `expect_text` remain the single diagnostic seam and
already report model, provider, run status, token counts, and a head-and-tail
preview.

`AgentRunner`'s retry path is unaffected. `is_transient` reads `status_code` or
walks the exception MRO, and the openai SDK raises the same `RateLimitError`,
`APITimeoutError`, and `APIStatusError` classes off the same client regardless
of which endpoint method was called.

The one new failure mode is a model rejecting an effort value it does not
declare. The catalog clamp is the guard, and it would surface through the same
seam.

---

## Testing

The offline suite fakes agents, so these assert on constructed request
parameters rather than live calls. Files: `tests/test_llm_runner.py`,
`tests/test_llm_runner_build_model.py`, `tests/test_llm_runner_search_equipped.py`,
`tests/test_agent_json_mode.py`.

| # | Assertion | Pins |
|---|---|---|
| 1 | openai branch returns `OpenAIResponses`, never `OpenAIChat` | the migration itself |
| 2 | one constructed request contains both a function tool and non-`none` reasoning | the bug being fixed |
| 3 | `gpt-5.5-pro` non-reasoning resolves to `medium`; `gpt-5.6-terra` to `none` | effort floor |
| 4 | `reasoning=True` sends `xhigh` and `max` verbatim | regression pin against re-introducing the down-mapping |
| 5 | uncatalogued id sends no `reasoning` key at all | the empty-dict fix |
| 6 | `store=False` on both callers | statefulness |
| 7 | `max_output_tokens` present and differs by `reasoning` | output cap |
| 8 | `$ref` siblings stripped at `text.format.schema` | shim relocation |
| 9 | `build_search_equipped` native_openai construction matches `build_model`'s, plus the web-search tool | the dedup; stops the two paths drifting again |

**Not covered offline:** that `/v1/responses` actually accepts these bodies.
That requires one live call per catalog model and is a manual post-merge check,
not something the suite verifies.

---

## Post-merge manual verification

For each id in `MODEL_CATALOG["openai"]`, with a real `OPENAI_API_KEY`:

1. A structured-output call (no tools) returns a parsed schema, not a `str`.
2. A tool-using agent (coach or interviewer) completes a turn with reasoning
   enabled — the case that is a hard 400 today.
3. Reported `reasoning_tokens` is zero for a non-reasoning agent on a model
   whose floor is `none`, and non-zero for a reasoning agent.

Record results in the implementation plan's verification section.

---

## Documentation

`CLAUDE.md`'s "LLM providers" section states the provider rules. Add: OpenAI
agents run on `/v1/responses`, effort rides `reasoning={"effort": ...}` because
agno's typed field is narrower than the API, the non-reasoning floor is the
catalog's lowest declared effort, and `store=False` trades replayed encrypted
reasoning tokens for provider-side retention. The existing note that a bare
`isinstance` check on agent output is a regression is unaffected.
