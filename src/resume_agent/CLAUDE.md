# Core package developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/`.

## LLM providers (`llm_runner.py`)

Every LLM agent is built through one seam — `build_model(model_id)` in
`llm_runner.py` — which is the **only** place that knows about provider SDKs. No
builder imports a concrete agno model class directly.

- **Provider-prefixed model ids.** `split_provider` reads a `provider:model`
  prefix: `openai:` / `gemini:` / `deepseek:` route to that provider; a bare id
  (or an unknown prefix, e.g. a Workday `tenant:site`) defaults to **Anthropic**,
  so legacy Claude ids pass through unchanged.
- **Per-provider keys.** `resolve_api_key(model_id)` maps the resolved provider to
  its `Settings` field (`anthropic_api_key` / `openai_api_key` / `gemini_api_key`
  / `deepseek_api_key`). `relevance.py`'s "no key → return `None`" guard uses it,
  so it is provider-aware.
- **Subscription routing stays inside the spend decision.** Deployment-level
  `SUB2API_BASE_URL`, one `SUB2API_<PROVIDER>_KEY` per provider, and each
  `<PROVIDER>_ROUTE_MODE` (`auto` / `subscription` / `api`) are resolved by
  `tenancy/spend.py` together with the funding key. `auto` uses the gateway only
  when that provider has a subscription key; an explicit `subscription` pin
  fails loudly when incomplete. `build_model` and `build_search_equipped` carry
  the resulting key and endpoint together through the provider SDK's native
  base-URL spelling. Audio transcription remains on direct provider APIs.
- **Lazy SDK imports.** `build_model` imports the agno provider class _inside_ its
  branch, so a Claude-only run never imports `openai` or `google-genai`, and a
  missing optional SDK fails only when that provider is actually selected.
- **OpenAI agents use `/v1/responses`.** `_build_openai_responses` is the only
  OpenAI construction site; both `build_model` and `build_search_equipped` use
  it so reasoning, output-budget, and state policies cannot drift. Responses
  allows reasoning and function tools in the same request.
- **OpenAI effort uses `reasoning={"effort": ...}`.** Agno's typed
  `reasoning_effort` field omits valid Responses values such as `none`, `xhigh`,
  and `max`. A catalogued non-reasoning model receives its lowest declared
  effort; an uncatalogued id omits `reasoning` because its vocabulary is
  unknown.
- **OpenAI output and state are explicit.** `max_output_tokens` leaves room for
  reasoning plus visible structured output. `store=False` disables
  provider-managed response state (not broader provider retention), while
  Agno requests `reasoning.encrypted_content` so stateless tool turns can replay
  opaque reasoning items. Those replayed items count as later input tokens.
- **OpenAI must always request a reasoning summary — otherwise agno relabels the
  answer as reasoning.** agno's Responses adapter reads "a `reasoning` config
  was sent but no `reasoning_summary`" as "the visible output text _is_ the
  reasoning" and copies **every** `output_text` delta into `reasoning_content`.
  Because a catalogued id always carries an explicit effort (even `none`), that
  fired on every OpenAI agent: each delta arrived as a `ReasoningDelta` _and_ a
  byte-identical `TextDelta`, alternating the two kinds on every token, so the
  chat rendered one "Show reasoning" disclosure plus one markdown block per
  token (239 SSE events on a coach turn where 16 suffice).
  `_build_openai_responses` therefore sends `reasoning_summary="auto"` whenever
  it sends `reasoning`, and nothing when the id is uncatalogued. Verified live
  on `gpt-5.6-terra`: accepted at every effort, duplication drops to zero, and a
  genuinely reasoning call streams real summaries (752 reasoning tokens) instead
  of an echo of its own answer. `_map_stream_event` additionally refuses to
  forward a `reasoning_content` equal to the event's `content` — the seam's
  standing rule that the visible answer is never reasoning.
- **Tiers unchanged.** `model_for_tier` still maps `cheap`/`mid`/`premium` →
  `Settings.{cheap,mid,premium}_model`; the prefix lives inside those ids.
- **Dependency note.** agno 2.6.x's Gemini import needs `google-genai`'s
  `step_delta` submodule, renamed to `stepdelta` in 2.9.0 — `pyproject.toml`
  caps it at `<2.9.0`. DeepSeek and OpenAI both ride the `openai` SDK.
- **Gemini thinking is generation-specific — never send `thinking_budget` to
  Gemini 3.** Gemini treats an unset thinking config as "provider decides"
  (unbounded automatic budget), so non-reasoning agents must bound it. But
  Gemini 3 replaced `thinking_budget` with `thinking_level` and **rejects the
  budget outright**: `thinking_budget=0` fails the whole request with `400
INVALID_ARGUMENT` before generating anything, and agno then hands back the
  error body as a plain `str` — surfacing as "Expected ResumeContent, got str"
  rather than as an HTTP error. `build_model` therefore bounds Gemini 3 with
  `thinking_level` (`low` when not reasoning, `high` when reasoning) and keeps
  `thinking_budget=0` only for pre-3 ids. Verified live against
  `gemini-3.6-flash`: `thinking_level="low"` reports no thought tokens;
  `thinking_budget=0` is a hard 400.
- **A Gemini model's thinking vocabulary is per-snapshot, and the catalog tuple
  is the enforcement.** `gemini-3.7-flash` supports only `low`/`medium`/`high`
  — it dropped the `minimal` level that `gemini-3.6-flash` and
  `gemini-3.5-flash` both have. No generation check guards this because none is
  needed: `_gemini_interactions_thinking_level_for` returns `"minimal"` only
  for an effort that is *in* the entry's `reasoning_efforts`, so omitting it
  from the tuple makes it unreachable, and `build_model`'s non-reasoning branch
  bounds at `"low"`, which every Gemini 3 snapshot accepts. Do not borrow a
  sibling model's levels when adding a snapshot — read its own row in the
  provider matrix.
- **DeepSeek runs on the Responses API, and its whole request surface changed
  with it.** DeepSeek serves the OpenAI Responses wire format at
  `base_url="https://api.deepseek.com"`, so `_compatible_deepseek_responses_class`
  subclasses `CompatibleOpenAIResponses` — inheriting the truncation recording
  and `$ref`-sibling stripping. `agno.models.deepseek.DeepSeek` (Chat
  Completions) is no longer used, and the legacy `deepseek-chat` /
  `deepseek-reasoner` ids are retired; only `deepseek-v4-flash` and
  `deepseek-v4-pro` are catalogued. Five things ride on this:
  - **`provider = "DeepSeek"` is load-bearing, not cosmetic.**
    `tenancy/costs.py::normalize_provider` tests for `"openai"` **before**
    `"deepseek"`, so a subclass that inherited the parent's `"OpenAI"` would bill
    every DeepSeek call against the OpenAI budget, resolve the OpenAI key, and
    report `openai:deepseek-…` from `_agent_model_id`.
  - **`reasoning.effort` is both the thinking toggle and the effort dial**, which
    is the fourth instance of the "unset means provider decides" trap. Verified
    live on `deepseek-v4-flash`: omitting `reasoning` spends 46 reasoning tokens
    and emits a reasoning output item; `effort="none"` spends **zero** and emits
    none. So the catalog declares `("none", "low", "high", "max")` and
    `_responses_effort` (shared with OpenAI) picks the lowest declared effort for
    a non-reasoning agent — which *is* the off switch. The Chat Completions
    `extra_body={"thinking": {"type": "disabled"}}` side-channel is gone.
    DeepSeek maps requested→actual as low→low, medium→high, high→high,
    xhigh→high, max→max.
  - **agno copies the visible answer into `reasoning_content` on every
    non-streaming call.** It reads reasoning from a reasoning item's `summary`;
    DeepSeek documents `reasoning.summary` as "accepted but no summary is
    generated" and live responses confirm `summary` is always `[]`, with the real
    chain-of-thought in `content[].text` under `type == "reasoning_text"`. Finding
    no summary, agno falls to `reasoning_content = response.output_text`.
    `reasoning_summary="auto"` does **not** fix this — that only guards the
    streaming branch — so `_parse_provider_response` is overridden to recover the
    real text, and to drop the echo when thinking is off.
  - **agno drops DeepSeek's streamed reasoning entirely.** DeepSeek streams CoT as
    `response.reasoning_text.delta` (measured: 177 deltas on one `effort="max"`
    turn); agno has a branch only for `response.reasoning_summary_text.delta`.
    `_parse_provider_response_delta` is overridden to map it.
  - **Native `web_search` works** (`DEEPSEEK_WEB_SEARCH_TOOL`, strategy
    `native_deepseek`), executed server-side, with automatic context caching
    (measured: 15,488 cached tokens on one search turn). But it returns **no
    `url_citation` annotations**, so `provider_capabilities` keeps
    `supports_native_citations=False`.
- **DeepSeek's `json_schema` validator is not OpenAI's, and `json_object` was the
  root cause of `UnparsedAgentOutput` on DeepSeek.** On Chat Completions the
  DeepSeek class declared `supports_native_structured_outputs=False`, so
  `use_json_mode_for` sent `response_format={"type": "json_object"}` — which
  constrains "the output must be JSON" but **not** "one well-formed,
  schema-conforming document and nothing else". Live failures showed all three
  leaks on `status=COMPLETED`, `reasoning=0` runs: malformed JSON (`{{`, a stray
  `,`), a second document, and a literal `<｜｜DSML｜｜tool_calls>` block written into
  the content channel instead of the tool channel. agno's three JSON parsers then
  left `content` a raw `str` and call sites raised `Expected <Schema> …, got str`
  — which is what drove the Evidence planner to its deterministic fallback. On
  Responses the schema rides `text.format`, so DeepSeek keeps native structured
  outputs — sent as **`strict_output = False`, with the schema unmodified**.
- **DeepSeek's `strict` validates the request schema; it does not constrain
  generation.** This is the opposite of OpenAI, where a strict schema compiles
  into a grammar that makes a stray key or a wrong-typed field impossible to
  emit. Measured against instructions that deliberately violate the schema,
  `strict=True` still returned a wrong-typed field **6/6** and leaked an
  undeclared key **5/6** (`strict=False`: 6/6 and 6/6). It enforces nothing.
  What it *does* do is reject a bare `anyOf` with `400 Invalid json schema:
  field `anyOf`: missing field `type``— the shape pydantic emits for every
  `Optional` field, so `FitScore` (four of them) 400'd on every call. Satisfying
  that needs a sibling `type`, which must be a **single scalar** (a list is
  rejected, and so is `object`), so a nullable *object* field could only be
  annotated with the false value `null`. Measured across `FitScore` and
  `JobCriteriaExtract` at n=10 per arm, that rewrite was indistinguishable from
  sending the raw schema — 10/10 valid and 10/10 populated on every
  nullable-object field either way — so it bought nothing, and the one future in
  which it would start mattering is the bad one: if DeepSeek ever implements
  real constrained decoding, `type: "null"` becomes a real constraint and
  silently nulls `seniority`, `employment_type`, `salary_range` and
  `FitScore.location`. A normalizer also carries a latent 400: a union of two
  models with no `null` member yields no legal scalar sibling. So DeepSeek gets
  the same schema OpenAI gets, and `expect_schema` + pydantic remain the real
  gate — which is where enforcement actually lives for this provider.
- **An unparsed structured response is retried, in `AgentRunner`.** agno does not
  raise when it cannot coerce a response into `output_schema` — it leaves
  `RunOutput.content` a raw `str` on a run the provider reports as a *success*, so
  nothing in the transient-error path could see it and one bad body went straight
  to the caller's fallback. `_unparsed_structured_output` detects it where the
  retry budget already lives. On exhaustion the **last response is returned, never
  raised**, so the call site's own `expect_schema` still owns the error and its
  model/status/token diagnostics. An agent with no `output_schema` is untouched —
  prose must never look like a failed parse.
- **A persona model may simply ignore the `---METADATA---` sentinel, and that is
  not a failure.** `sessions/turns.py::persona_output` splits prose from
  formatter input on that marker. Claude emits it; **DeepSeek v4 never does** —
  verified against the live coach prompt with thinking both on and off, the run
  completing normally (no truncation), so there is nothing to retry. Because the
  formatter is an LLM that extracts a turn from raw notes either way, a missing
  marker **degrades** (the whole response becomes both the visible reply and the
  formatter's notes) and logs a warning; it must never raise. Marker matching
  tolerates surrounding emphasis and padding but _requires_ the `METADATA`
  token — DeepSeek writes a bare `---` rule as a section break, so matching the
  rules alone would truncate a reply mid-turn. `ProseEmitter` withholds only a
  trailing prefix that can still complete into one of these boundaries; ordinary
  prose flushes with zero fixed character lag. The candidate scan is capped by
  `MARKER_MAX_LEN`.
- **Formatter payload is never displayable, sentinel or not.** Degrading on a
  missing sentinel is only safe when there is nothing to hide — true of DeepSeek
  (it emits no metadata at all), false for a model that writes the block and
  forgets the marker, which dumps `action:` / `topic_updates:` / `draft:` into
  the chat window. `_BOUNDARY` therefore cuts at the sentinel **or** at the
  metadata block's own opening key, and the degradation branch fires only when
  neither exists. The block guard is deliberately narrow — a bare lowercase
  schema key at the start of a line, preceded by a blank line and followed by a
  colon — because truncating a reply is worse than the leak it prevents: a coach
  writes `**Action:** …` and `the draft: …` mid-sentence and neither may cut the
  turn.
- **The NDJSON log is durability; a notifier is only the low-latency wakeup.**
  `RunStreamSink` keeps one append handle open, flushes every complete row, and
  wakes process-local SSE subscribers after the flush. Readers clear their event
  before draining the log, then await it with the existing poll timeout as a
  dropped-notification fallback. Reconnects still replay from their durable event
  offset; the notifier never owns stream truth.
- **`settled` means visible prose is complete, not that the run is terminal.** It
  is emitted only after streamed prose finishes and never belongs in
  `TERMINAL_TAGS`. The browser removes the caret and enables typing while keeping
  Send disabled until formatter validation and session persistence complete.
  The EventSource remains open for notices and exactly one `completed`/`failed`.
- **Conversational stream batching is 40 ms / 120 characters.** A deterministic
  120-delta harness (15 characters every 10 ms) produced 15 rows at 80/240, 30
  rows at 40/120, and 58 rows at 20/60. The middle setting halves median batch
  latency while holding event count to exactly 2x the legacy baseline; text and
  reasoning retain separate budgets.
- **Agno's `cache_system_prompt` caches the system block, not turn messages.**
  Persona and formatter builders enable it for providers that advertise prompt
  caching. Session overview/transcript/agenda remain user-message content; Agno
  does not expose user-message cache breakpoints through this flag. Do not move
  per-profile context into a global system prompt or assume it is cached.
- **Anthropic has the same "unset means provider decides" trap, and it is
  generation-specific.** Omitting `thinking` runs **adaptive** on Sonnet 5 and
  Opus 5, and runs **without** thinking on Opus 4.8/4.7 and older — so leaving
  it unset silently bought thinking on every non-reasoning agent using the
  default `mid_model`. Because `max_tokens` caps thinking **plus** response
  text, that truncated large structured outputs into the same unparsed-`str`
  symptom as the Gemini bug. `_anthropic_thinking` therefore sends
  `{"type": "disabled"}` for non-reasoning 4.6+ ids (omitting it on pre-4.6,
  where unset already means off, and on Fable/Mythos, which reject a disabled
  config), and `_anthropic_max_tokens` replaces agno's 8192 default — clamped
  to the SDK's per-model non-streaming ceiling so a custom Opus 4/4.1 id
  cannot raise `ValueError`.
- **Claude capability gates read the model generation, never a substring.**
  `anthropic_version` parses `claude-<family>-<major>[-<minor>]` into a
  comparable tuple; pre-4 ids (`claude-3-5-haiku-…`) put the version first and
  deliberately return `None`, which is correct because every gated capability
  arrived with 4.6. Both adaptive thinking + `output_config.effort`
  (`provider_capabilities`) and the `web_search_20260209` tool variant
  (`anthropic_web_search_tool`) gate on `>= (4, 6)`. The old `"haiku" in
model` heuristic was right only for the catalog and 400'd for any pre-4.6 id
  entered through the tier picker's custom field; agno cannot catch this
  because its `NON_THINKING_MODELS` covers only Haiku 3 and 3.5.
- **Model-tier defaults live only on `Settings`.** `ModelsConfigDoc`
  (`api/schemas/secrets.py`) and `WizardState` (`setup/state.py`) derive theirs
  via `Settings.model_fields[...].default` instead of restating literals —
  which is how the wizard silently fell a generation behind (`claude-sonnet-4-6`
  vs `claude-sonnet-5`) while a test _named_ for that invariant kept passing by
  restating the literals too.
- **A structured-output call that returns `str` is diagnosed, not guessed.**
  agno leaves `RunOutput.content` as the raw `str` whenever it cannot parse a
  response into `output_schema`, which collapses truncation, refusal and a
  rejected request into one indistinguishable symptom. `expect_schema` in
  `llm_runner.py` is the single seam that raises `UnparsedAgentOutput` carrying
  model, provider, run status, token counts (including `reasoning`) and a head
  **and tail** preview — the tail is what shows a response was cut off. Use it
  at every `output_schema` call site instead of a bare `isinstance` check.
  Every such call site now does — cover letters, discovery (extract/fit/
  relevance), scraper recipes, URL ingest, profile extraction/inference/
  synthesis/projects, both scouts, and `sessions/turns.py` (so the coach and
  interview stacks inherit it) — so a bare `isinstance` guard on agent output
  is a regression. `UnparsedAgentOutput` subclasses `TypeError`, so adopting it
  never changes what a caller catches.
- **A truncated response is a provider _success_, and agno throws away the one
  field that says otherwise.** OpenAI returns `status="incomplete"` +
  `incomplete_details.reason="max_output_tokens"` with HTTP 200 when generation
  stops at the ceiling. agno logs that under the misleading headline
  `Background response … completed with status 'incomplete'` — the check sits
  **outside** the `if self.background:` branch, so it fires on every
  non-streaming call and says nothing about background mode — and then drops
  it: `_parse_provider_response` receives the whole `Response` but copies
  neither field onto `ModelResponse`. The truncated body then fails all three
  JSON parsers and lands in `expect_schema` as a bare `str`, where "got str" is
  equally true of a refusal or a rejected schema. `CompatibleOpenAIResponses`
  therefore records `{reason, ceiling}` under `INCOMPLETE_KEY` on agno's own
  `provider_data`, which `agent/_response.py` copies to
  `RunOutput.model_provider_data`; `_describe_unparsed` names it in both
  `expect_*` failures. **Recorded, not raised** — agno's `invoke` rewraps any
  exception as `ModelProviderError`, losing the type _and_ escaping call sites
  that deliberately degrade on `UnparsedAgentOutput`
  (`h1b/service.py::_resolve_company_name`). This also closes a real hole in
  `expect_text`: half a JSON body parses as nothing, but half a _sentence_ is a
  non-empty `str` on a successful run, so truncated prose used to reach the
  caller as a whole answer. Streaming never calls `_parse_provider_response`,
  so a truncated **streamed** turn is still undetected.
- **`_openai_max_output_tokens` is deliberately not `_anthropic_max_tokens`.**
  Anthropic's ~16000 exists because the SDK enforces a per-model non-streaming
  ceiling (`MODEL_NONSTREAMING_TOKENS`) and raises above it. The Responses API
  has no equivalent, so copying that figure across rationed output the model
  was willing to produce and truncated large structured responses mid-string —
  and a body cut that way parses as nothing, so the call was paid for in full
  and yielded zero. The ceiling's job is to bound a runaway, not to budget
  legitimate output: 32000 non-reasoning, **64000** reasoning. The reasoning
  figure is the larger one because on OpenAI — unlike Anthropic, where
  `thinking` has its own budget — reasoning tokens are spent out of this same
  allowance, so the same visible answer needs more headroom.

To add a provider: extend `PROVIDERS`, add its key to `Settings`, and add a branch
to `build_model` with a lazy import. Nothing else changes.

---

## Deployment

- **Railway is a single-volume, single-owner deployment.** Session cookies and
  bearer tokens share the API guard; `/app/data` owns DB/config/output/secrets;
  browser-only sources return explicit degradation failures in cloud. Admin
  import validates and stages the archive, then uses rollback-safe child swaps
  because the mounted volume root itself cannot be renamed.
- **Runtime mode is explicit.** `resume-agent serve` defaults to auth-free local
  mode and one automatically activated workspace; non-loopback binds require
  `--mode hosted`. The container entrypoint always selects hosted mode, where
  login and per-request tenant selection remain mandatory.

---

## Cross-cutting infra notes

- **A run-constant document belongs in the system block, not the per-job
  message.** `cache_system_prompt` caches the system block only, so the
  `ProfileFacts` JSON that `compose_fit_input` put first in all N per-job
  messages was paid for N times at full price (measured: ~65,000 of a 20-job
  run's 65,420 prompt tokens). `fit.bind_profile` moves it into the agent's
  description once at the start of the scoring phase and **returns whether it
  took**; a caller that gets `False` keeps the profile in the message, so what
  the model is told never depends on whether the optimisation applied. Fact-lock
  is untouched — identical content, different message position.
  `llm_runner.prompt_cache_for(model_id)` is the one rule for whether to ask for
  caching (the `prompt_cache_enabled` switch crossed with provider capability)
  and every N-per-run builder uses it.
- **A run's agent calls are traceable.** `agent_trace.py` writes one NDJSON row
  per agent call under the run's own directory (`{run_id}.agents.ndjson`),
  scoped by a `ContextVar` that `RunManager.submit`'s worker installs.
  `UsageEvent` is a billing record and cannot say which agent family produced
  which artifact, how many retries it took, or whether the cache was hit.
  **Operational events only** — no prompt, completion, or reasoning content,
  the same rule `_map_stream_event` enforces. Deliberately minimal: one file per
  run, no schema, no API surface.
- **File SQLite runs WAL.** `make_engine` sets `journal_mode=WAL`, `busy_timeout=30000`,
  and `synchronous=NORMAL` on every file-backed connection so the API's writer threads wait
  instead of failing immediately with `database is locked`.
