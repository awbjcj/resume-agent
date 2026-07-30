# OpenAI Responses API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every OpenAI agno agent through `/v1/responses` instead of `/v1/chat/completions`, so reasoning effort and function tools can be used together and the configured effort reaches the wire verbatim.

**Architecture:** One new private seam, `_build_openai_responses()`, holds every OpenAI request-shaping rule (effort, output cap, `store`, schema compatibility). Both `build_model()` and `build_search_equipped()` call it, so no other OpenAI construction site remains. Three workaround helpers written to route around chat/completions limitations are deleted.

**Tech Stack:** Python 3.12, agno 2.6.x, openai SDK, pydantic v2, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-07-30-openai-responses-migration-design.md`

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline; no API key, no network).
- Lint command: `ruff check` — must be clean before every commit.
- Only `src/resume_agent/llm_runner.py` changes in `src/`. No other module is touched.
- The public signatures of `build_model()` and `build_search_equipped()` do not change. The ~24 modules that call them are not modified.
- Anthropic, Gemini, and DeepSeek branches are not modified.
- No new user-facing setting. The migration is unconditional.
- Effort is passed as `reasoning={"effort": ...}`, never `reasoning_effort=...` — agno types the latter as `Literal["minimal","low","medium","high"]`, which would fail pyright for `"none"`, `"xhigh"`, and `"max"`.
- `store=False` must be passed explicitly. Verified: with `store` unset, agno sends `store=True` for any `gpt-5*` id.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/resume_agent/llm_runner.py` | The single provider-construction seam | Modified — OpenAI branch only |
| `tests/test_llm_runner_build_model.py` | `build_model` per-provider construction | Modified — 5 existing tests rewritten, 4 added |
| `tests/test_llm_runner_search_equipped.py` | Search-equipped construction | Modified — 2 existing tests rewritten, 1 added |
| `tests/test_agent_json_mode.py` | Structured-output mode per provider | Unchanged — verified still passing |
| `CLAUDE.md` | Developer reference | Modified — LLM providers section |

**Why no new source file:** `llm_runner.py` is deliberately the only module that knows about provider SDKs (a stated CLAUDE.md invariant). Splitting the OpenAI branch into its own module would break that single-seam property for a net reduction in code. The file shrinks in this change.

---

## Current-state reference

Read once before starting. Line numbers are from the pre-change file.

| Symbol | Line | Fate |
|---|---|---|
| `OpenAIResponsesReasoningEffort` (Literal) | 301 | Delete (Task 4) |
| `catalog_entry()` | 396 | Unchanged — exact-id lookup, returns `None` for custom ids |
| `provider_capabilities()` openai branch | 535 | Unchanged — `supports_reasoning` is true only for `gpt-5*`/`o1`/`o3`/`o4` |
| `_without_ref_siblings()` | 636 | Unchanged — reused by the new shim; Gemini also uses it |
| `_compatible_openai_chat_class()` | 648 | Delete (Task 3) |
| `use_json_mode_for()` | 724 | Unchanged |
| `_anthropic_max_tokens()` | 775 | Unchanged — the pattern `_openai_max_output_tokens` mirrors |
| `_reasoning_effort_for()` | 806 | Unchanged — reused by `_openai_effort` |
| `_openai_responses_reasoning_effort_for()` | 814 | Delete (Task 4) |
| `_openai_disabled_effort()` | 832 | Delete (Task 3) |
| `build_model()` openai branch | 885-894 | Rewrite (Task 3) |
| `build_search_equipped()` `native_openai` branch | 963-978 | Rewrite (Task 4) |

`MODEL_CATALOG["openai"]` entries and their declared efforts (line 326):

| id | `reasoning_efforts` |
|---|---|
| `openai:gpt-5.6-luna` | none, low, medium, high, xhigh, max |
| `openai:gpt-5.6-terra` | none, low, medium, high, xhigh, max |
| `openai:gpt-5.6-sol` | none, low, medium, high, xhigh, max |
| `openai:gpt-5.5-pro` | medium, high, xhigh |
| `openai:gpt-5.5` | none, low, medium, high, xhigh |
| `openai:gpt-5.4-mini` | none, low, medium, high, xhigh |

---

### Task 1: Effort resolution

Pure functions, no agno involvement. A reviewer can accept or reject the effort policy here without reading any construction code.

**Files:**
- Modify: `src/resume_agent/llm_runner.py` (add after `_reasoning_effort_for`, line 811)
- Test: `tests/test_llm_runner_build_model.py`

**Interfaces:**
- Consumes: `catalog_entry(model_id) -> ModelCatalogEntry | None`, `_reasoning_effort_for(model_id, provider) -> str`, both existing.
- Produces: `_EFFORT_ORDER: tuple[str, ...]` and `_openai_effort(model_id: str, *, reasoning: bool) -> str | None`. Task 3 calls `_openai_effort`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_runner_build_model.py`:

```python
def test_openai_effort_floor_is_the_lowest_effort_the_model_declares():
    # A non-reasoning agent must not leave effort unset: on Responses an unset
    # effort means "provider decides", and the point of the floor is that spend
    # is chosen here rather than by the provider.
    assert llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=False) == "none"
    assert llm_runner._openai_effort("openai:gpt-5.4-mini", reasoning=False) == "none"
    # gpt-5.5-pro declares only medium/high/xhigh, so its floor is medium. On
    # chat/completions this model could not use function tools at all, because
    # there was no effort value both it and the endpoint accepted.
    assert llm_runner._openai_effort("openai:gpt-5.5-pro", reasoning=False) == "medium"


def test_openai_effort_is_unset_for_an_uncatalogued_model():
    # A custom id from the tier picker's escape hatch has no known effort
    # vocabulary, so guessing one risks a 400. Unset is safe on Responses in a
    # way it was not on chat/completions, where it broke function tools.
    assert llm_runner._openai_effort("openai:gpt-5.9-experimental", reasoning=False) is None
    assert llm_runner._openai_effort("openai:gpt-5.9-experimental", reasoning=True) is None


def test_openai_reasoning_effort_defaults_to_high_within_the_catalog(monkeypatch):
    # Pin settings: get_settings() reads the environment, so a developer with
    # PREMIUM_MODEL=openai:... in their .env would otherwise see tier tuning
    # override the default and fail this test for the wrong reason.
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model=None,
        premium_reasoning_effort=None,
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)
    assert llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=True) == "high"
    assert llm_runner._openai_effort("openai:gpt-5.5-pro", reasoning=True) == "high"


def test_openai_reasoning_effort_honours_configured_tier_tuning(monkeypatch):
    # The catalog declares max for gpt-5.6-terra, so it must survive verbatim.
    # The old chat/completions path mapped xhigh and max down to high.
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model="openai:gpt-5.6-terra",
        premium_reasoning_effort="max",
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)
    assert llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=True) == "max"


def test_openai_effort_ordering_covers_every_catalogued_value():
    # _openai_effort orders by _EFFORT_ORDER.index, which raises ValueError for
    # an unlisted value. A new catalog effort must be added to the table too.
    for entry in llm_runner.MODEL_CATALOG["openai"]:
        for effort in entry.reasoning_efforts:
            assert effort in llm_runner._EFFORT_ORDER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -k openai_effort -v`

Expected: FAIL — `AttributeError: module 'resume_agent.llm_runner' has no attribute '_openai_effort'`

- [ ] **Step 3: Write the implementation**

Insert into `src/resume_agent/llm_runner.py` immediately after `_reasoning_effort_for` (which ends at line 811):

```python
# Reasoning efforts in ascending order of spend. OpenAI's Responses API accepts
# all of these (model-dependent); `_openai_effort` orders a model's declared
# subset by index here, so any new effort added to MODEL_CATALOG must be added
# to this tuple as well or the lookup raises ValueError.
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _openai_effort(model_id: str, *, reasoning: bool) -> str | None:
    """Resolve the reasoning effort to send for an OpenAI id, or ``None``.

    ``None`` means send no ``reasoning`` parameter at all. That is reserved for
    an id with no catalog entry -- a custom model typed into the tier picker's
    escape hatch, whose accepted effort vocabulary is unknown, so any value we
    invent risks a 400. Leaving it unset is safe on Responses in a way it was
    not on chat/completions, where a provider-chosen effort broke function
    tools outright.

    For a catalogued id the effort is always explicit, including when reasoning
    is off: an unset effort means "provider decides", which is the same trap
    ``_anthropic_thinking`` and the Gemini branch already guard. A non-reasoning
    agent therefore gets the model's lowest declared effort -- ``none`` where it
    is offered, and ``medium`` for gpt-5.5-pro, which declares no ``none`` and
    for that reason could not use function tools on chat/completions at all.
    """
    entry = catalog_entry(model_id)
    if entry is None or not entry.reasoning_efforts:
        return None
    if not reasoning:
        return min(entry.reasoning_efforts, key=_EFFORT_ORDER.index)
    configured = _reasoning_effort_for(model_id, "openai")
    if configured in entry.reasoning_efforts:
        return configured
    # `_reasoning_effort_for` falls back to "high", which every current OpenAI
    # entry declares. Clamp anyway so a future entry without it cannot send an
    # effort the model rejects.
    return max(entry.reasoning_efforts, key=_EFFORT_ORDER.index)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -k openai_effort -v`

Expected: PASS (5 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/llm_runner.py tests/test_llm_runner_build_model.py
git commit -m "feat: resolve OpenAI reasoning effort from the model catalog

A non-reasoning agent gets the model's lowest declared effort rather than
an unset one, so spend is chosen here instead of by the provider. An
uncatalogued custom id stays unset because its vocabulary is unknown."
```

---

### Task 2: Responses compatibility shim

Independently reviewable: it is a pure request-param transform, testable by calling `get_request_params` directly with no network and no builder.

**Files:**
- Modify: `src/resume_agent/llm_runner.py` (add after `_compatible_openai_chat_class`, line 674)
- Test: `tests/test_llm_runner_build_model.py`

**Interfaces:**
- Consumes: `_without_ref_siblings(schema: dict) -> dict`, existing at line 636.
- Produces: `_compatible_openai_responses_class() -> type` — an `lru_cache`d factory returning a `CompatibleOpenAIResponses` subclass. Task 3 instantiates it.

**Background — the two defects this fixes.** Both were confirmed by running agno directly:

1. agno's `sanitize_response_schema` sets `additionalProperties`, fills `required`, and drops null defaults, but does **not** remove keywords sitting beside `$ref`. Pydantic emits exactly that for a nested model with a description: `{"$ref": "#/$defs/Inner", "description": "the inner thing"}`. The existing `CompatibleOpenAIChat` fixed this at `response_format.json_schema.schema`; Responses flattens the same schema to `text.format.schema`.

2. `_set_reasoning_request_param` runs `base_params["reasoning"] = self.reasoning or {}`, and the later filter only drops `None`. So `{}` survives and **every** Responses request carries `reasoning: {}`. Confirmed: `OpenAIResponses(id='gpt-5.6-terra').get_request_params(messages=[])` returns `{'reasoning': {}, 'store': True}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_runner_build_model.py`:

```python
def test_responses_shim_strips_ref_siblings_from_the_output_schema():
    # Pydantic emits {"$ref": ..., "description": ...} for a described nested
    # model, and OpenAI rejects keywords beside $ref. agno's own schema
    # sanitizer does not remove them; it only handles additionalProperties,
    # required, and null defaults.
    from pydantic import BaseModel, Field

    class Inner(BaseModel):
        a: str

    class Outer(BaseModel):
        inner: Inner = Field(description="the inner thing")

    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k"
    )
    params = model.get_request_params(messages=[], response_format=Outer)

    node = params["text"]["format"]["schema"]["properties"]["inner"]
    assert "$ref" in node
    assert "description" not in node


def test_responses_shim_drops_an_empty_reasoning_object():
    # agno assigns `reasoning = self.reasoning or {}` unconditionally and the
    # request filter only removes None, so an unconfigured model would send
    # `reasoning: {}` to a model that may not support reasoning at all.
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k"
    )
    assert "reasoning" not in model.get_request_params(messages=[])


def test_responses_shim_keeps_a_populated_reasoning_object():
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k", reasoning={"effort": "xhigh"}
    )
    params = model.get_request_params(messages=[])
    assert params["reasoning"] == {"effort": "xhigh"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -k responses_shim -v`

Expected: FAIL — `AttributeError: module 'resume_agent.llm_runner' has no attribute '_compatible_openai_responses_class'`

- [ ] **Step 3: Write the implementation**

Insert into `src/resume_agent/llm_runner.py` immediately after `_compatible_openai_chat_class` (which ends at line 674):

```python
@lru_cache(maxsize=1)
def _compatible_openai_responses_class():
    from agno.models.openai.responses import OpenAIResponses

    class CompatibleOpenAIResponses(OpenAIResponses):
        """Responses adapter: legal ``$ref`` nodes, and no empty reasoning object.

        Note the signature differs from ``OpenAIChat.get_request_params`` --
        Responses takes ``messages`` first -- and the output schema moves from
        ``response_format.json_schema.schema`` to ``text.format.schema``.
        """

        def get_request_params(
            self,
            messages=None,
            response_format=None,
            tools=None,
            tool_choice=None,
        ):
            params = super().get_request_params(
                messages=messages,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
            )
            text_format = params.get("text", {}).get("format", {})
            schema = text_format.get("schema")
            if isinstance(schema, dict):
                text_format["schema"] = _without_ref_siblings(schema)
            # agno assigns `reasoning = self.reasoning or {}` unconditionally and
            # its request filter drops only None, so an unconfigured model would
            # otherwise send `reasoning: {}` -- which is what makes "no catalog
            # entry means send no effort" actually send no effort.
            if not params.get("reasoning"):
                params.pop("reasoning", None)
            return params

    return CompatibleOpenAIResponses
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -k responses_shim -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/llm_runner.py tests/test_llm_runner_build_model.py
git commit -m "feat: add OpenAI Responses compatibility shim

Strips JSON Schema keywords beside \$ref at text.format.schema, which
agno's sanitizer leaves in place, and drops the empty reasoning object
agno emits unconditionally."
```

---

### Task 3: Route `build_model` through Responses

The migration proper. This is where the endpoint changes and the chat-era workarounds are deleted.

**Files:**
- Modify: `src/resume_agent/llm_runner.py` (add `_openai_max_output_tokens`; rewrite `build_model` openai branch at 885-894; delete `_openai_disabled_effort` at 832-850 and `_compatible_openai_chat_class` at 648-674)
- Test: `tests/test_llm_runner_build_model.py`

**Interfaces:**
- Consumes: `_openai_effort(model_id, *, reasoning)` (Task 1), `_compatible_openai_responses_class()` (Task 2), `split_provider(model_id) -> tuple[str, str]` (existing).
- Produces: `_build_openai_responses(model_id: str, *, api_key: str | None, reasoning: bool) -> Any`. Task 4 calls it.

**Existing tests this task invalidates.** These assert chat-era behaviour and must be *rewritten*, not merely supplemented:

| Test | Current assertion | Why it breaks |
|---|---|---|
| `test_reasoning_parameters_are_attached_for_capable_models` | `build_model("openai:gpt-5.6", reasoning=True).reasoning_effort == "high"` | `gpt-5.6` is not a catalog id (the catalog has `gpt-5.6-luna/terra/sol`), so it now resolves to unset; and effort moved to `.reasoning` |
| `test_selected_tier_tuning_is_forwarded_by_provider` | `openai.reasoning_effort == "xhigh"` | effort moved to `.reasoning` |
| `test_non_reasoning_openai_disables_effort_rather_than_omitting_it` | `terra.reasoning_effort == "none"` | effort moved to `.reasoning`; the docstring describes the deleted workaround |
| `test_openai_effort_stays_unset_when_none_is_not_a_selectable_effort` | `pro.reasoning_effort is None` | **inverts** — gpt-5.5-pro now gets its floor, `medium` |
| `test_openai_effort_stays_unset_for_uncatalogued_model` | `custom.reasoning_effort is None` | still unset, but must now assert no `reasoning` attribute value |

- [ ] **Step 1: Rewrite the invalidated tests and add the new ones**

In `tests/test_llm_runner_build_model.py`, replace the OpenAI assertion inside `test_reasoning_parameters_are_attached_for_capable_models`:

```python
    openai = build_model("openai:gpt-5.6-terra", api_key="k", reasoning=True)
    assert openai.reasoning == {"effort": "high"}
```

Replace the OpenAI assertion inside `test_selected_tier_tuning_is_forwarded_by_provider`:

```python
    assert openai.reasoning == {"effort": "xhigh"}
```

Delete `test_non_reasoning_openai_disables_effort_rather_than_omitting_it`,
`test_openai_effort_stays_unset_when_none_is_not_a_selectable_effort`, and
`test_openai_effort_stays_unset_for_uncatalogued_model` outright, and add in their place:

```python
def test_openai_agents_are_built_on_the_responses_endpoint():
    # chat/completions rejects function tools whenever the model picks its own
    # reasoning effort, which is why every tool-using OpenAI agent used to be
    # clamped to effort "none". /v1/responses has no such restriction.
    from agno.models.openai.responses import OpenAIResponses

    model = build_model("openai:gpt-5.6-terra", api_key="k")
    assert isinstance(model, OpenAIResponses)
    assert model.id == "gpt-5.6-terra"


def test_openai_reasoning_is_no_longer_clamped_off_for_tool_use(monkeypatch):
    # The regression this migration exists to prevent. gpt-5.5-pro declares no
    # "none" effort, so on chat/completions there was no value both it and the
    # endpoint accepted, and it could not run function tools at all.
    # Settings are pinned so local tier tuning cannot fail this for the wrong
    # reason -- this assertion is the point of the migration.
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model=None,
        premium_reasoning_effort=None,
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    pro = build_model("openai:gpt-5.5-pro", api_key="k", reasoning=True)
    assert pro.reasoning == {"effort": "high"}
    # A non-reasoning agent gets the catalog floor, not "none" and not unset.
    assert build_model("openai:gpt-5.5-pro", api_key="k").reasoning == {
        "effort": "medium"
    }
    # The chat-era clamp must not come back.
    assert not hasattr(llm_runner, "_openai_disabled_effort")


def test_openai_non_reasoning_model_still_sends_an_explicit_effort():
    terra = build_model("openai:gpt-5.6-terra", api_key="k")
    assert terra.reasoning == {"effort": "none"}


def test_openai_uncatalogued_model_sends_no_reasoning_at_all():
    # Unknown effort vocabulary: guessing risks a 400, and agno's empty-dict
    # default is popped by the shim so this really is absent from the request.
    custom = build_model("openai:gpt-5.9-experimental", api_key="k")
    assert custom.reasoning is None
    assert "reasoning" not in custom.get_request_params(messages=[])


def test_openai_never_stores_conversations_on_the_provider():
    # Verified against agno: with `store` unset it sends store=True for any
    # gpt-5* id, which would retain tenant resume and JD content on OpenAI.
    # store=False also makes agno replay encrypted reasoning across tool turns.
    model = build_model("openai:gpt-5.6-terra", api_key="k")
    assert model.store is False
    params = model.get_request_params(messages=[])
    assert params["store"] is False
    assert params["include"] == ["reasoning.encrypted_content"]


def test_openai_bounds_the_output_budget():
    # max_output_tokens caps reasoning PLUS visible output, the same trap
    # _anthropic_max_tokens guards: a reasoning budget eating the response text
    # truncates a large structured output into an unparsed str.
    assert build_model("openai:gpt-5.6-terra", api_key="k").max_output_tokens == 16000
    assert (
        build_model(
            "openai:gpt-5.6-terra", api_key="k", reasoning=True
        ).max_output_tokens
        == 32000
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py -v`

Expected: FAIL — the new OpenAI tests fail on `AttributeError: 'CompatibleOpenAIChat' object has no attribute 'reasoning'` and `isinstance(model, OpenAIResponses)` is `False`.

- [ ] **Step 3: Write the implementation**

Add `_openai_max_output_tokens` immediately after `_openai_effort` (from Task 1):

```python
def _openai_max_output_tokens(*, reasoning: bool) -> int:
    """Bound OpenAI's output budget the way ``_anthropic_max_tokens`` does.

    On Responses ``max_output_tokens`` caps reasoning PLUS visible output, so a
    reasoning budget can eat the response text and truncate a large structured
    output into an unparsed ``str`` rather than an HTTP error. Unlike Anthropic
    there is no per-model non-streaming ceiling to clamp against.
    """
    return 32000 if reasoning else 16000
```

Add the builder seam immediately after it:

```python
def _build_openai_responses(
    model_id: str, *, api_key: str | None, reasoning: bool
) -> Any:
    """Build an OpenAI agent on ``/v1/responses`` -- the only OpenAI seam.

    ``build_model`` and ``build_search_equipped`` both route here so the effort
    floor, output cap, and ``store`` policy cannot drift apart between the
    agent path and the research path.
    """
    OpenAIResponses = _compatible_openai_responses_class()
    effort = _openai_effort(model_id, reasoning=reasoning)
    return OpenAIResponses(
        id=split_provider(model_id)[1],
        api_key=api_key,
        # The untyped `reasoning` dict, not `reasoning_effort`: agno annotates
        # the latter as Literal["minimal","low","medium","high"], so "none",
        # "xhigh", and "max" would fail pyright despite being valid on the API.
        reasoning={"effort": effort} if effort is not None else None,
        max_output_tokens=_openai_max_output_tokens(reasoning=reasoning),
        # Explicit: with `store` unset agno sends store=True for any gpt-5* id,
        # which would retain tenant career data on OpenAI. False additionally
        # makes agno replay encrypted reasoning items across tool-call turns.
        store=False,
    )
```

Replace the `build_model` openai branch (lines 885-894) with:

```python
    if provider == "openai":
        return _build_openai_responses(model_id, api_key=key, reasoning=reasoning)
```

Delete `_openai_disabled_effort` (lines 832-850) and `_compatible_openai_chat_class` (lines 648-674) entirely.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_build_model.py tests/test_agent_json_mode.py -v`

Expected: PASS. `test_agent_json_mode.py` needs no change — `OpenAIResponses.supports_native_structured_outputs` is `True`, the same as `OpenAIChat`, so `use_json_mode_for("openai:gpt-4o-mini")` stays `False`. If it fails, that assumption was wrong; stop and report rather than editing the json-mode test.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/llm_runner.py tests/test_llm_runner_build_model.py
git commit -m "feat: build OpenAI agents on /v1/responses

Reasoning effort and function tools can now be used together. Deletes the
reasoning_effort='none' clamp and the chat compatibility subclass, and
adds an explicit output cap and store=False."
```

---

### Task 4: Collapse the search path onto the same seam

Without this, the research path keeps its own effort mapper and silently misses the new floor, cap, and `store` policy — the exact drift that produced the current divergence.

**Files:**
- Modify: `src/resume_agent/llm_runner.py` (rewrite `build_search_equipped` `native_openai` branch at 963-978; delete `_openai_responses_reasoning_effort_for` at 814-829 and `OpenAIResponsesReasoningEffort` at 301)
- Test: `tests/test_llm_runner_search_equipped.py`

**Interfaces:**
- Consumes: `_build_openai_responses(model_id, *, api_key, reasoning)` from Task 3.
- Produces: nothing new.

**Existing tests this task invalidates:**

| Test | Current assertion | Why it breaks |
|---|---|---|
| `test_native_search_forwards_safe_provider_options` | `build_search_equipped("openai:gpt-5.6", reasoning=True)` → `.reasoning_effort == "high"` | `gpt-5.6` is uncatalogued → unset; effort moved to `.reasoning` |
| `test_search_builder_gates_incapable_reasoning_request` | `build_search_equipped("openai:gpt-4o", reasoning=True).reasoning_effort is None` | effort moved to `.reasoning`; `gpt-4o` is both uncatalogued and `supports_reasoning=False` |

- [ ] **Step 1: Rewrite the invalidated tests and add the dedup pin**

In `tests/test_llm_runner_search_equipped.py`, replace the OpenAI block inside `test_native_search_forwards_safe_provider_options`:

```python
    openai, openai_tools = build_search_equipped(
        "openai:gpt-5.6-terra", mode="native", reasoning=True
    )
    assert openai.reasoning == {"effort": "high"}
    assert openai.store is False
    assert openai_tools == [{"type": "web_search"}]
```

Replace `test_search_builder_gates_incapable_reasoning_request` entirely:

```python
def test_search_builder_gates_incapable_reasoning_request():
    # gpt-4o is not a reasoning model (provider_capabilities gates on gpt-5*),
    # and it has no catalog entry, so no effort is sent at all.
    model, _ = build_search_equipped("openai:gpt-4o", mode="native", reasoning=True)
    assert model.reasoning is None
```

Append:

```python
def test_native_openai_search_reuses_the_shared_builder():
    # The research path used to construct OpenAIResponses itself with its own
    # effort mapper, so it silently missed rules added to the agent path. Pin
    # that both paths now produce the same construction.
    from resume_agent.llm_runner import build_model

    searched, tools = build_search_equipped(
        "openai:gpt-5.5-pro", mode="native", reasoning=True
    )
    direct = build_model("openai:gpt-5.5-pro", api_key=None, reasoning=True)

    assert type(searched) is type(direct)
    assert searched.id == direct.id
    assert searched.reasoning == direct.reasoning
    assert searched.max_output_tokens == direct.max_output_tokens
    assert searched.store == direct.store
    assert tools == [{"type": "web_search"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_search_equipped.py -v`

Expected: FAIL — `max_output_tokens` differs (the search branch sets none) and `.reasoning` is `None` on the search-built model because the old branch passes `reasoning_effort` instead.

- [ ] **Step 3: Write the implementation**

Replace the `native_openai` branch of `build_search_equipped` (lines 963-978) with:

```python
    if plan.strategy == "native_openai":
        return (
            _build_openai_responses(model_id, api_key=api_key, reasoning=reasoning),
            [OPENAI_WEB_SEARCH_TOOL],
        )
```

Delete `_openai_responses_reasoning_effort_for` (lines 814-829) and the
`OpenAIResponsesReasoningEffort` Literal alias (line 301) entirely.

`GeminiInteractionsThinkingLevel` (line 302) stays — the Gemini branch still uses it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner_search_equipped.py -v`

Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/llm_runner.py tests/test_llm_runner_search_equipped.py
git commit -m "refactor: build native OpenAI search on the shared seam

The research path had its own OpenAIResponses construction and effort
mapper, so rules added to the agent path did not reach it. Deletes the
lossy xhigh/max-to-high down-mapping."
```

---

### Task 5: Full verification and documentation

**Files:**
- Modify: `CLAUDE.md` (LLM providers section)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing.

- [ ] **Step 1: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`

Expected: PASS, with no more failures than were present on `main` before this branch. If any test outside `tests/test_llm_runner_*.py` fails, stop and report which — it means a call site depended on OpenAI construction details this plan assumed were private.

- [ ] **Step 2: Confirm the deletions actually happened**

Run:

```bash
grep -n "_openai_disabled_effort\|_openai_responses_reasoning_effort_for\|_compatible_openai_chat_class\|OpenAIResponsesReasoningEffort\|OpenAIChat" src/resume_agent/llm_runner.py
```

Expected: no output. Any hit is a leftover.

- [ ] **Step 3: Run lint**

Run: `ruff check`

Expected: `All checks passed!`

- [ ] **Step 4: Update CLAUDE.md**

In the `## LLM providers (llm_runner.py)` section, add these bullets after the "Lazy SDK imports" bullet:

```markdown
- **OpenAI agents run on `/v1/responses`, not `/v1/chat/completions`.**
  chat/completions rejects function tools whenever the model picks its own
  reasoning effort ("To use function tools, use /v1/responses or set
  reasoning_effort to 'none'"), so every tool-using OpenAI agent used to be
  clamped to effort `none` — and `gpt-5.5-pro`, whose catalog entry declares
  no `none`, could not use tools at all. `_build_openai_responses` is the only
  OpenAI construction site; both `build_model` and `build_search_equipped`
  route through it so the effort, cap, and storage rules cannot drift apart.
- **Effort rides `reasoning={"effort": …}`, never `reasoning_effort=…`.** agno
  annotates its `reasoning_effort` field as
  `Literal["minimal","low","medium","high"]`, which is narrower than the API —
  `none`, `xhigh`, and `max` are all valid on Responses and all fail pyright
  through that field. The untyped `reasoning` dict is both the legal and the
  more capable route, which is why the old down-mapping to `high` is gone.
- **A non-reasoning OpenAI agent still sends an explicit effort** — the lowest
  its `MODEL_CATALOG` entry declares (`none` for most ids, `medium` for
  `gpt-5.5-pro`). Same "unset means provider decides" rule as Anthropic's
  `thinking` and Gemini's `thinking_level`. Only an uncatalogued custom id
  sends no `reasoning` at all, because its vocabulary is unknown; the
  compatibility shim pops the empty dict agno would otherwise emit.
- **`store=False` is mandatory, not a preference.** With `store` unset agno
  sends `store=True` for any `gpt-5*` id, retaining tenant resume and JD
  content on OpenAI. `False` also makes agno replay encrypted reasoning items
  across tool-call turns, which preserves the model's chain through a tool call
  — at the cost of billing those replayed items as **input** tokens each turn,
  so multi-tool agents (coach, interviewer, scouts) legitimately report higher
  input token counts than they did on chat/completions.
```

- [ ] **Step 5: Commit**

```bash
ruff check
git add CLAUDE.md
git commit -m "docs: record the OpenAI Responses migration invariants"
```

---

## Post-merge manual verification

Not covered by the offline suite, which fakes every agent. Requires a real `OPENAI_API_KEY`. Run once per id in `MODEL_CATALOG["openai"]` and record the results.

- [ ] A structured-output call with no tools returns a parsed schema, not a `str`. (`gpt-5.5-pro` is the important one — it exercises the `medium` floor.)
- [ ] A tool-using agent completes a turn with reasoning enabled — the coach or the interviewer. This is a hard 400 on the current `main`.
- [ ] Reported `reasoning_tokens` is `0` for a non-reasoning agent whose floor is `none`, and non-zero for a reasoning agent.
- [ ] A large `ResumeContent` tailoring round at `max` effort completes without truncation. If it raises `UnparsedAgentOutput` with a cut-off tail preview, raise the `32000` in `_openai_max_output_tokens`.

---

## Self-review notes

**Spec coverage.** Every spec section maps to a task: architecture/seam → Task 3; deletions → Tasks 3 and 4; effort rule → Task 1; output cap → Task 3; statefulness → Task 3; compatibility shim (both jobs) → Task 2; error handling → no code change, verified in Task 5 Step 1; the 9-row test table → distributed across Tasks 1-4; post-merge checks → final section; documentation → Task 5.

**Test-table mapping.** Spec test 1 → `test_openai_agents_are_built_on_the_responses_endpoint`. 2 → `test_openai_reasoning_is_no_longer_clamped_off_for_tool_use`. 3 → `test_openai_effort_floor_is_the_lowest_effort_the_model_declares`. 4 → `test_openai_reasoning_effort_honours_configured_tier_tuning`. 5 → `test_openai_uncatalogued_model_sends_no_reasoning_at_all`. 6 → `test_openai_never_stores_conversations_on_the_provider`. 7 → `test_openai_bounds_the_output_budget`. 8 → `test_responses_shim_strips_ref_siblings_from_the_output_schema`. 9 → `test_native_openai_search_reuses_the_shared_builder`.

**Type consistency.** `_openai_effort(model_id, *, reasoning) -> str | None` is defined in Task 1 and called with those exact keywords in Task 3. `_compatible_openai_responses_class()` is defined in Task 2 and called in Tasks 2 and 3. `_build_openai_responses(model_id, *, api_key, reasoning)` is defined in Task 3 and called in Task 4 with those exact keywords.

**Deviation from the spec, deliberate.** The spec described the shim as replacing `_compatible_openai_chat_class`. The plan deletes the chat class in Task 3 rather than Task 2, so that Task 2 leaves the suite green — the chat class still has a caller until `build_model` is rewired.
