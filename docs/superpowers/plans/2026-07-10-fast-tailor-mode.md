# Fast Tailor Mode + Selective Tailoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fast tailoring (2 LLM reviewers, 2 rounds max, Sonnet writers) the default, keep today's deep panel behind a `--deep`/`deep: true` switch, and let the web user tailor a selected subset of approved jobs from a launch dialog.

**Architecture:** Fast mode is entirely configuration: `ReviewConfig` gains `merged_advisory`, `tailor_tier`, `reviser_tier`; `config/review.yaml` becomes the fast roster and `config/review_deep.yaml` keeps today's roster. The merged advisory reviewer is one LLM call that returns per-dimension `ReviewCritique`s, split back into the same 4 named rows so `aggregate()`, persistence, and the UI are identical between modes. The loop in `workflow.py` only gains timing capture.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic / agno (backend), React + TanStack Query + shadcn/vitest (web).

**Spec:** `docs/superpowers/specs/2026-07-10-fast-tailor-mode-design.md`

## Global Constraints

- All Python tests run offline: `.venv/Scripts/python.exe -m pytest` (agents are faked; never construct a real model in tests).
- Lint: `ruff check` must stay clean.
- Web tests: `npx vitest run <file>` from `D:\Fun\resume-agent\web`.
- Wire format is camelCase (`CamelModel`); Python stays snake_case.
- Fact-lock invariant untouched: fact-check stays a blocking gate at `model_tier: premium` in BOTH modes; the deterministic provenance gate still short-circuits the panel.
- Back-compat: existing flat `review.yaml` files (no new keys) must load and behave exactly as before. All new `ReviewConfig` fields have defaults preserving current behavior.
- After changing any API schema: regenerate contracts with `bash scripts/gen_ts_client.sh` and keep `tests/api/test_openapi_contract.py` green.
- Commit after every task (small, focused commits).

## Correctness Amendments (authoritative)

These amendments override conflicting snippets below. They were added after
checking the plan against the 2026-07-10 design and the current repository.

1. **Validate new model tiers at the config boundary.** `tailor_tier` and
   `reviser_tier` are `Literal["cheap", "mid", "premium"]`, not unconstrained
   strings. Add a regression test that an unknown tier is rejected rather than
   silently falling through `model_for_tier()` to the mid model.
2. **Test the real setup interface.** The current tuple is private
   `resume_agent.setup.preflight._EXAMPLES`; Task 2 must assert against that
   name (and update `atomic_write_all`'s "five config files" docstring to six).
3. **Keep one source of truth for config paths.** CLI and API code import
   `DEFAULT_REVIEW` / `DEFAULT_REVIEW_DEEP` from
   `services.tailoring`; do not redeclare the strings in `cli.py`.
4. **The launch dialog must load the complete approved set.** The pipeline is
   paginated, so deriving launch jobs from `PipelineContainer.rows` silently
   omits approved jobs on unloaded pages. Add an enabled-on-open query/hook that
   fetches every `/api/pipeline?status=approved` page (page size 200), expose its
   loading/error state in the dialog, and disable submit until loading finishes.
   `LaunchJob.title` is nullable because `PipelineItem.title` is nullable.
5. **Do not close on a failed launch.** `LaunchDialog.onLaunch` returns
   `Promise<boolean>` (matching `useBulkRun`); show a composed `Spinner`, disable
   controls while pending, and close only when it resolves `true`. Tests cover
   success, false-return retention, loading, empty, and rejected/error states.
6. **Use the installed Base UI shadcn composition.** Forms use
   `FieldGroup`/`Field`; related job checkboxes use
   `FieldSet`/`FieldLegend`; dialogs include `DialogDescription`; empty content
   uses `Empty`; button icons use `data-icon` with no sizing override; layout
   uses `gap-*`, not `space-y-*`.

---

### Task 1: ReviewConfig gains `merged_advisory`, `tailor_tier`, `reviser_tier`

**Files:**

- Modify: `src/resume_agent/tailor/review_config.py`
- Test: `tests/test_tailor_review_config.py`

**Interfaces:**

- Produces: `ReviewConfig.merged_advisory: bool` (default `False`), `ReviewConfig.tailor_tier: str` (default `"premium"`), `ReviewConfig.reviser_tier: str` (default `"premium"`). Later tasks read these via `config.<field>`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tailor_review_config.py`:

```python
def test_new_fields_default_to_current_behavior():
    cfg = ReviewConfig()
    assert cfg.merged_advisory is False
    assert cfg.tailor_tier == "premium"
    assert cfg.reviser_tier == "premium"


def test_new_fields_load_from_yaml(tmp_path):
    f = tmp_path / "review.yaml"
    f.write_text(
        "merged_advisory: true\ntailor_tier: mid\nreviser_tier: mid\n",
        encoding="utf-8",
    )
    cfg = load_review_config(f)
    assert cfg.merged_advisory is True
    assert cfg.tailor_tier == "mid"
    assert cfg.reviser_tier == "mid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_review_config.py -v`
Expected: FAIL — `AttributeError` / assertion on missing fields.

- [ ] **Step 3: Implement** — in `src/resume_agent/tailor/review_config.py`, add to `ReviewConfig` (after `match_plan_enabled`):

```python
    merged_advisory: bool = False
    tailor_tier: str = "premium"   # cheap | mid | premium — writer (draft) model
    reviser_tier: str = "premium"  # cheap | mid | premium — reviser model
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_review_config.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/review_config.py tests/test_tailor_review_config.py
git commit -m "feat(tailor): add merged_advisory and writer tier knobs to ReviewConfig"
```

---

### Task 2: Fast/deep config files + setup wizard registration

**Files:**

- Modify: `config/review.yaml`, `config/review.yaml.example`
- Create: `config/review_deep.yaml`, `config/review_deep.yaml.example`
- Modify: `src/resume_agent/setup/preflight.py:5-13` (EXAMPLES tuple), `src/resume_agent/setup/writer.py:48-53` (targets map), `src/resume_agent/setup/screens.py:534-540` (file listing)
- Test: `tests/test_shipped_review_configs.py` (new)

**Interfaces:**

- Produces: `config/review.yaml` = fast roster (`merged_advisory: true`, `max_rounds: 2`, Sonnet writers); `config/review_deep.yaml` = today's roster. Task 7/8 reference the deep path string `"config/review_deep.yaml"`.

- [ ] **Step 1: Write the failing test** — create `tests/test_shipped_review_configs.py`:

```python
from resume_agent.tailor.review_config import load_review_config


def test_shipped_fast_config_shape():
    cfg = load_review_config("config/review.yaml")
    assert cfg.merged_advisory is True
    assert cfg.max_rounds == 2
    assert cfg.early_stop_on_regression is True
    assert cfg.tailor_tier == "mid"
    assert cfg.reviser_tier == "mid"
    gates = [r for r in cfg.reviewers if r.gate]
    assert [g.name for g in gates] == ["fact-check"]
    assert gates[0].model_tier == "premium"  # fact-lock keeps the strongest model
    assert [r.name for r in cfg.reviewers if not r.gate] == [
        "ats-keyword", "recruiter", "hiring-manager", "concision",
    ]


def test_shipped_deep_config_matches_legacy_roster():
    cfg = load_review_config("config/review_deep.yaml")
    assert cfg.merged_advisory is False
    assert cfg.max_rounds == 3
    assert cfg.tailor_tier == "premium"
    assert cfg.reviser_tier == "premium"
    assert len(cfg.reviewers) == 5


def test_deep_example_registered_with_setup():
    from resume_agent.setup.preflight import EXAMPLES

    assert "review_deep.yaml.example" in EXAMPLES
```

(If the tuple in `preflight.py` has a different name than `EXAMPLES`, read the file and use the actual name in the test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_shipped_review_configs.py -v`
Expected: FAIL — `review.yaml` lacks `merged_advisory`, `review_deep.yaml` missing.

- [ ] **Step 3: Write the config files.** Replace `config/review.yaml` (and mirror into `config/review.yaml.example`) with:

```yaml
# Fast review roster (default): fact-check gate + one merged advisory call.
# For the full multi-round panel use --deep / review_deep.yaml.
max_rounds: 2
early_stop_on_regression: true
score_threshold: 85
merged_advisory: true
tailor_tier: mid
reviser_tier: mid
reviewers:
  - name: fact-check
    gate: true # blocking: any unsupported claim fails the round
    weight: 0
    model_tier: premium
  - name: ats-keyword
    gate: false
    weight: 1
    model_tier: mid
  - name: recruiter
    gate: false
    weight: 1
    model_tier: mid
  - name: hiring-manager
    gate: false
    weight: 1
    model_tier: mid
  - name: concision
    gate: false
    weight: 1
    model_tier: mid

length_budget:
  max_experiences: 4
  max_bullets_per_role: 5
  target_total_bullets: 20
```

Create `config/review_deep.yaml` (and `.example`) with the pre-change roster — copy today's `config/review.yaml` content verbatim (max_rounds 3, five separate reviewers, hiring-manager premium, no new keys).

- [ ] **Step 4: Register with setup.** In `preflight.py` add `"review_deep.yaml.example"` to the examples tuple. In `writer.py` targets map add:

```python
        root / "config" / "review_deep.yaml": lambda: render_from_example(root / "config" / "review_deep.yaml.example"),
```

In `screens.py` file listing add `("config/review_deep.yaml", "deep review roster (from example)"),`.

- [ ] **Step 5: Run the new test, then the whole suite** (config content changes can ripple into setup tests):

Run: `.venv/Scripts/python.exe -m pytest tests/test_shipped_review_configs.py tests/test_setup_yaml_gen.py -v` then `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. If a setup test asserts the exact example-file list, update it to include the new file.

- [ ] **Step 6: Commit**

```bash
git add config/review.yaml config/review.yaml.example config/review_deep.yaml config/review_deep.yaml.example src/resume_agent/setup tests/test_shipped_review_configs.py
git commit -m "feat(config): fast review roster by default, deep roster split out"
```

---

### Task 3: Writer tier plumbing in `build_tailor_bundle`

**Files:**

- Modify: `src/resume_agent/services/agents.py:69-88`
- Modify: `tests/test_services_agents.py` (existing lambdas must accept the new kwarg)

**Interfaces:**

- Consumes: `ReviewConfig.tailor_tier` / `reviser_tier` (Task 1); `build_tailor_agent(model_id=None, style_guide=None)` / `build_reviser_agent(model_id=None, style_guide=None)` (already exist in `tailor/agents.py`).
- Produces: `build_tailor_bundle(config, style_guide)` now passes `model_id=model_for_tier(config.tailor_tier)` to the tailor agent and `model_id=model_for_tier(config.reviser_tier)` to the reviser agent.

- [ ] **Step 1: Write the failing test** — append to `tests/test_services_agents.py`:

```python
def test_tailor_bundle_threads_writer_tiers(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agents, "build_tailor_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("tailor", model_id),
    )
    monkeypatch.setattr(
        agents, "build_reviser_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("reviser", model_id),
    )
    monkeypatch.setattr(agents, "build_revision_agent", lambda style_guide=None: "revision")
    monkeypatch.setattr(
        agents, "build_reviewer_agent",
        lambda name, model, style_guide=None, score_bands=False: f"rev:{name}",
    )
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: f"model:{tier}")

    cfg = ReviewConfig(tailor_tier="mid", reviser_tier="cheap", reviewers=[ReviewerSpec(name="a")])
    agents.build_tailor_bundle(cfg, style_guide=None)
    assert seen["tailor"] == "model:mid"
    assert seen["reviser"] == "model:cheap"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py -v`
Expected: the new test FAILS (`seen["tailor"] is None`); pre-existing tests still pass.

- [ ] **Step 3: Implement** — in `build_tailor_bundle`, replace the `tailor=`/`reviser=` lines:

```python
    return TailorBundle(
        tailor=build_tailor_agent(
            model_id=model_for_tier(getattr(config, "tailor_tier", "premium")),
            style_guide=style_guide,
        ),
        reviser=build_reviser_agent(
            model_id=model_for_tier(getattr(config, "reviser_tier", "premium")),
            style_guide=style_guide,
        ),
        reviewers=reviewers,
        revision=build_revision_agent(style_guide=style_guide),
        match_plan=(
            build_match_plan_agent(style_guide=style_guide)
            if getattr(config, "match_plan_enabled", False)
            else None
        ),
    )
```

(`getattr` with a default matches the existing `getattr(config, "match_plan_enabled", False)` duck-typing pattern used by tests that pass bare `Config` classes.)

- [ ] **Step 4: Fix ripple in existing tests.** In `tests/test_services_agents.py`, the pre-existing monkeypatched lambdas `lambda style_guide=None: ...` for `build_tailor_agent`/`build_reviser_agent` will now receive `model_id=` — change them to `lambda model_id=None, style_guide=None: ...` (keep their bodies).

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_agents.py tests/test_services_tailoring.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/services/agents.py tests/test_services_agents.py
git commit -m "feat(tailor): route configured writer tiers into tailor/reviser agents"
```

---

### Task 4: `MergedPanelReview` schema, merged agent builder, splitter

**Files:**

- Modify: `src/resume_agent/models/review.py`
- Modify: `src/resume_agent/tailor/agents.py`
- Modify: `src/resume_agent/tailor/panel.py`
- Test: `tests/test_tailor_panel.py`

**Interfaces:**

- Produces:
  - `MergedPanelReview(ExtensibleModel)` with `critiques: list[ReviewCritique]` (in `models/review.py`).
  - `build_merged_advisory_agent(names: list[str], model_id: str | None = None, style_guide: str | None = None, *, score_bands: bool = False) -> Runner` (in `tailor/agents.py`), output schema `MergedPanelReview`.
  - `split_merged_critiques(review: MergedPanelReview, expected: list[str]) -> list[ReviewCritique]` (in `tailor/panel.py`) — validates exact name coverage, returns critiques in `expected` order, raises `ValueError` on missing/extra/duplicate names.
  - Constant `MERGED_ADVISORY = "advisory-panel"` (in `tailor/panel.py`) — the `reviewer_agents` mapping key for the merged agent.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tailor_panel.py`:

```python
def test_split_merged_critiques_returns_expected_order():
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import split_merged_critiques

    review = MergedPanelReview(
        critiques=[
            ReviewCritique(reviewer="recruiter", score=88, passed=True),
            ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
        ]
    )
    out = split_merged_critiques(review, ["ats-keyword", "recruiter"])
    assert [c.reviewer for c in out] == ["ats-keyword", "recruiter"]


@pytest.mark.parametrize(
    "names",
    [
        ["ats-keyword"],                                # missing "recruiter"
        ["ats-keyword", "recruiter", "extra"],          # extra name
        ["ats-keyword", "ats-keyword", "recruiter"],    # duplicate
    ],
)
def test_split_merged_critiques_rejects_wrong_coverage(names):
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import split_merged_critiques

    review = MergedPanelReview(
        critiques=[ReviewCritique(reviewer=n, score=80, passed=True) for n in names]
    )
    with pytest.raises(ValueError):
        split_merged_critiques(review, ["ats-keyword", "recruiter"])


def test_merged_advisory_instructions_cover_each_rubric():
    from resume_agent.tailor.agents import _merged_advisory_instructions

    text = " ".join(_merged_advisory_instructions(["ats-keyword", "concision"]))
    assert "'ats-keyword'" in text
    assert "'concision'" in text
    assert "keyword" in text.lower()   # ats rubric present
    assert "concision" in text.lower()  # concision rubric present
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py -v -k "merged"`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement.**

`src/resume_agent/models/review.py` — append:

```python
class MergedPanelReview(ExtensibleModel):
    """One combined advisory call's output: a critique per configured dimension."""

    critiques: list[ReviewCritique] = Field(default_factory=list)
```

`src/resume_agent/tailor/agents.py` — append (import `MergedPanelReview` from `resume_agent.models.review`):

```python
def _merged_advisory_instructions(
    names: list[str], *, score_bands: bool = False
) -> list[str]:
    listed = ", ".join(repr(n) for n in names)
    header = [
        "You are a combined advisory review panel. Return one MergedPanelReview whose "
        f"critiques list contains exactly one ReviewCritique per reviewer name, in this order: {listed}. "
        "Set each critique's reviewer field to exactly its assigned name.",
        "Judge each dimension independently against its own rubric below; do not let one "
        "dimension's score bleed into another.",
        *_COMMON_REVIEWER_INSTRUCTIONS,
        *([_SCORE_BAND_INSTRUCTION] if score_bands else []),
    ]
    for name in names:
        rubric = [
            *REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS),
            *CRAFT_REVIEWERS.get(name, []),
        ]
        header.append(f"Rubric for {name!r}: " + " ".join(rubric))
    return header


def build_merged_advisory_agent(
    names: list[str],
    model_id: str | None = None,
    style_guide: str | None = None,
    *,
    score_bands: bool = False,
) -> Runner:
    model = build_model(
        model_id or model_for_tier("mid"),
        cache_system_prompt=_prompt_cache(),
    )
    return AgentRunner(
        Agent(
            model=model,
            description="Produce every advisory review dimension for a tailored resume in one pass.",
            instructions=compose_instructions(
                _merged_advisory_instructions(names, score_bands=score_bands), style_guide
            ),
            output_schema=MergedPanelReview,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
```

`src/resume_agent/tailor/panel.py` — add near the top (import `MergedPanelReview`):

```python
MERGED_ADVISORY = "advisory-panel"


def split_merged_critiques(
    review: MergedPanelReview, expected: list[str]
) -> list[ReviewCritique]:
    """Validate the merged call covered exactly the configured advisory names."""
    got = [c.reviewer for c in review.critiques]
    if sorted(got) != sorted(expected):
        raise ValueError(
            f"Merged advisory review must cover exactly {expected!r}, got {got!r}"
        )
    by_name = {c.reviewer: c for c in review.critiques}
    return [by_name[name] for name in expected]
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/review.py src/resume_agent/tailor/agents.py src/resume_agent/tailor/panel.py tests/test_tailor_panel.py
git commit -m "feat(tailor): merged advisory reviewer schema, agent builder, splitter"
```

---

### Task 5: Merged dispatch in `run_panel`/`arun_panel` + bundle wiring

**Files:**

- Modify: `src/resume_agent/tailor/panel.py:49-118`
- Modify: `src/resume_agent/services/agents.py:69-77`
- Test: `tests/test_tailor_panel.py`, `tests/test_services_agents.py`

**Interfaces:**

- Consumes: `MERGED_ADVISORY`, `split_merged_critiques`, `build_merged_advisory_agent` (Task 4); `config.merged_advisory` (Task 1).
- Produces: when `config.merged_advisory` is true, `run_panel`/`arun_panel` issue one lean-input call to `reviewer_agents[MERGED_ADVISORY]` for all non-gate reviewers and return gates-then-advisory critiques (each group in config order). `build_tailor_bundle` builds that agent under the `MERGED_ADVISORY` key. `workflow.py` is NOT modified.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tailor_panel.py`:

```python
def _merged_config() -> ReviewConfig:
    return ReviewConfig(
        merged_advisory=True,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
            ReviewerSpec(name="recruiter", weight=1),
        ],
    )


def test_run_panel_merged_makes_one_advisory_call():
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import MERGED_ADVISORY

    merged_agent = _Agent(
        MergedPanelReview(
            critiques=[
                ReviewCritique(reviewer="recruiter", score=88, passed=True),
                ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
            ]
        )
    )
    agents = {
        "fact-check": _Agent(ReviewCritique(reviewer="fact-check", score=100, passed=True)),
        MERGED_ADVISORY: merged_agent,
    }
    critiques = run_panel(_content(), _facts(), "Backend role", _merged_config(), agents)

    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword", "recruiter"]
    assert "SUPPORTING FACTS" in agents["fact-check"].received
    assert "RESUME STATS" in merged_agent.received
    assert "SecretRust" not in merged_agent.received  # advisory gets lean input


def test_run_panel_merged_raises_on_bad_coverage():
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import MERGED_ADVISORY

    agents = {
        "fact-check": _Agent(ReviewCritique(reviewer="fact-check", score=100, passed=True)),
        MERGED_ADVISORY: _Agent(
            MergedPanelReview(
                critiques=[ReviewCritique(reviewer="ats-keyword", score=80, passed=True)]
            )
        ),
    }
    with pytest.raises(ValueError):
        run_panel(_content(), _facts(), "jd", _merged_config(), agents)


def test_arun_panel_merged_matches_sync():
    import asyncio

    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import MERGED_ADVISORY, arun_panel

    agents = {
        "fact-check": _Agent(ReviewCritique(reviewer="fact-check", score=100, passed=True)),
        MERGED_ADVISORY: _Agent(
            MergedPanelReview(
                critiques=[
                    ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
                    ReviewCritique(reviewer="recruiter", score=88, passed=True),
                ]
            )
        ),
    }

    async def go():
        return await arun_panel(
            _content(), _facts(), "jd", _merged_config(), agents, sem=asyncio.Semaphore(8)
        )

    critiques = asyncio.run(go())
    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword", "recruiter"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py -v -k "merged"`
Expected: new tests FAIL (`KeyError` — `_panel_inputs` looks up non-gate names in `reviewer_agents`).

- [ ] **Step 3: Implement in `panel.py`.** Replace `run_panel` and `arun_panel` bodies to branch on `config.merged_advisory`:

```python
def _advisory_names(config: ReviewConfig) -> list[str]:
    return [spec.name for spec in config.reviewers if not spec.gate]


def _merged_review(result_content: Any, expected: list[str]) -> list[ReviewCritique]:
    if not isinstance(result_content, MergedPanelReview):
        raise TypeError(
            f"Expected MergedPanelReview from merged advisory, got {type(result_content).__name__}"
        )
    return split_merged_critiques(result_content, expected)


def run_panel(content, profile_facts, jd_text, config, reviewer_agents):
    """Run configured reviewers with the smallest sufficient input per role."""
    if not config.merged_advisory:
        return [
            review_one(text, reviewer_agents[name])
            for name, text in _panel_inputs(content, profile_facts, jd_text, config)
        ]
    evidence = resolve_evidence(content, profile_facts)
    critiques = [
        review_one(
            compose_evidence_review_input(content, jd_text, evidence),
            reviewer_agents[spec.name],
        )
        for spec in config.reviewers
        if spec.gate
    ]
    names = _advisory_names(config)
    if names:
        lean = compose_lean_review_input(content, jd_text, resume_stats(content))
        result = reviewer_agents[MERGED_ADVISORY].run(lean)
        critiques.extend(_merged_review(result.content, names))
    return critiques
```

`arun_panel` — same branch; the merged call runs concurrently with the gate calls, settle-then-raise like the existing path (keep the non-merged path byte-identical):

```python
async def arun_panel(content, profile_facts, jd_text, config, reviewer_agents, *, sem):
    """Run configured reviewers concurrently; results stay in reviewer order."""
    if not config.merged_advisory:
        # ... existing body, unchanged ...
        pass
    evidence = resolve_evidence(content, profile_facts)
    gate_specs = [spec for spec in config.reviewers if spec.gate]
    names = _advisory_names(config)
    coros = [
        areview_one(
            compose_evidence_review_input(content, jd_text, evidence),
            reviewer_agents[spec.name],
            sem=sem,
        )
        for spec in gate_specs
    ]
    if names:
        lean = compose_lean_review_input(content, jd_text, resume_stats(content))
        coros.append(acall(reviewer_agents[MERGED_ADVISORY], lean, sem=sem))
    outputs = await asyncio.gather(*coros, return_exceptions=True)
    first_error: BaseException | None = None
    critiques: list[ReviewCritique] = []
    for i, output in enumerate(outputs):
        if isinstance(output, BaseException):
            first_error = first_error or output
        elif names and i == len(gate_specs):  # the merged advisory result
            try:
                critiques.extend(_merged_review(output.content, names))
            except (TypeError, ValueError) as exc:
                first_error = first_error or exc
        else:
            critiques.append(output)
    if first_error is not None:
        raise first_error
    return critiques
```

- [ ] **Step 4: Wire the bundle.** In `services/agents.py` `build_tailor_bundle`, replace the reviewers loop:

```python
    from resume_agent.tailor.panel import MERGED_ADVISORY  # top-of-file import

    reviewers = {}
    merged = bool(getattr(config, "merged_advisory", False))
    for spec in config.reviewers:
        if merged and not spec.gate:
            continue
        reviewers[spec.name] = build_reviewer_agent(
            spec.name,
            model_for_tier(spec.model_tier),
            style_guide=style_guide,
            score_bands=bool(getattr(spec, "score_bands", False)),
        )
    if merged:
        non_gate = [s for s in config.reviewers if not s.gate]
        if non_gate:
            reviewers[MERGED_ADVISORY] = build_merged_advisory_agent(
                [s.name for s in non_gate],
                model_for_tier("mid"),
                style_guide=style_guide,
                score_bands=any(bool(getattr(s, "score_bands", False)) for s in non_gate),
            )
```

Add a bundle test to `tests/test_services_agents.py` (monkeypatch `build_merged_advisory_agent` like the others; assert `set(bundle.reviewers) == {"fact-check", MERGED_ADVISORY}` for a merged config with one gate + two advisory specs).

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py tests/test_services_agents.py tests/test_tailor_workflow.py -v`
Expected: PASS (workflow tests confirm the loop is untouched).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tailor/panel.py src/resume_agent/services/agents.py tests/test_tailor_panel.py tests/test_services_agents.py
git commit -m "feat(tailor): one merged advisory call replaces per-reviewer fan-out in fast mode"
```

---

### Task 6: Per-stage timing on `TailorRound`

**Files:**

- Modify: `src/resume_agent/tailor/workflow.py`
- Test: `tests/test_tailor_workflow.py`

**Interfaces:**

- Produces: `TailorRound.stage_seconds: dict[str, float]` (default `{}`). Keys: `"match_plan"`/`"draft"` on round 1, `"panel"` on every round that ran the panel, `"revise"` on the round _following_ a revision (the revise that produced that round's content). `ExtensibleModel` keeps previously persisted rounds loadable.

- [ ] **Step 1: Write the failing test** — append to `tests/test_tailor_workflow.py`. The file already defines `_ContentAgent` (tailor/reviser fake), `_FactCheck` (fails round 1, passes round 2), and `_Good(name)` — reuse them:

```python
def test_rounds_carry_stage_seconds():
    config = ReviewConfig(
        max_rounds=3,
        score_threshold=80,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )
    reviewer_agents = {"fact-check": _FactCheck(), "ats-keyword": _Good("ats-keyword")}

    rounds = run_tailor_review(
        jd_text="Backend role",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents=reviewer_agents,
        reviser_agent=_ContentAgent(),
    )

    assert len(rounds) == 2  # fails round 1 (gate), passes round 2
    assert rounds[0].stage_seconds.keys() >= {"draft", "panel"}
    assert rounds[1].stage_seconds.keys() >= {"revise", "panel"}
    assert all(v >= 0 for r in rounds for v in r.stage_seconds.values())
```

Note: `_FactCheck` fails with a blocking issue, so `provenance` passes but the gate fails — the panel still runs each round, which is what makes `"panel"` present on both rounds.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_workflow.py -v -k stage_seconds`
Expected: FAIL — `stage_seconds` missing.

- [ ] **Step 3: Implement.** In `workflow.py`:

```python
import time

class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict
    stage_seconds: dict[str, float] = Field(default_factory=dict)
```

In BOTH `run_tailor_review` and `arun_tailor_review`, wrap each stage with `time.monotonic()` and carry a `pending: dict[str, float]` into the round being built:

- around the match-plan call: `pending["match_plan"] = elapsed`
- around the draft (`tailor`/`atailor`): `pending["draft"] = elapsed`
- inside the loop, around the panel (`run_panel`/`arun_panel`): `panel_s`
- construct the round with `stage_seconds={**pending, "panel": panel_s}` when the panel ran (else just `pending`), then reset `pending = {}`
- around the revise call at the loop bottom: `pending["revise"] = elapsed` (lands on the next round)

- [ ] **Step 4: Log per-job totals** so live runs are measurable without a DB migration. In `src/resume_agent/tailor/service.py`, add `import logging` + `logger = logging.getLogger(__name__)` at module level, and inside `_persist_rounds` (which both `tailor_job` and `tailor_jobs` share), after the loop over rounds:

```python
    total = sum(sum(r.stage_seconds.values()) for r in rounds)
    logger.info(
        "tailor job=%s rounds=%s total_llm_seconds=%.1f stages=%s",
        job.id,
        len(rounds),
        total,
        [r.stage_seconds for r in rounds],
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_workflow.py tests/test_services_tailoring.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tailor/workflow.py src/resume_agent/tailor/service.py tests/test_tailor_workflow.py
git commit -m "feat(tailor): record per-stage wall-clock on each review round"
```

---

### Task 7: CLI `--deep` flag

**Files:**

- Modify: `src/resume_agent/services/tailoring.py:22` (add constant), `src/resume_agent/cli.py:599-651`
- Test: `tests/test_cli_tailor_deep.py` (new)

**Interfaces:**

- Consumes: `config/review_deep.yaml` (Task 2).
- Produces: `DEFAULT_REVIEW_DEEP = "config/review_deep.yaml"` in `services/tailoring.py`; `tailor --deep` passes that path as `review_path` (an explicit `--review <path>` still wins).

- [ ] **Step 1: Write the failing test** — create `tests/test_cli_tailor_deep.py` (pattern copied from `tests/test_cli_cover_letter.py`):

```python
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import JobStatus

runner = CliRunner()


def _seed(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        assert job is not None
        job.status = JobStatus.approved.value
        save_job(s, job)
    return db_url


def test_tailor_deep_flag_swaps_review_path(tmp_path, monkeypatch):
    db_url = _seed(tmp_path)
    captured = {}

    def fake_tailor(session, *, review_path, **kw):
        captured["review_path"] = review_path
        return {}

    monkeypatch.setattr(cli, "tailor", fake_tailor)
    result = runner.invoke(cli.app, ["tailor", "--approved", "--deep", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert captured["review_path"] == "config/review_deep.yaml"


def test_tailor_explicit_review_beats_deep(tmp_path, monkeypatch):
    db_url = _seed(tmp_path)
    captured = {}

    def fake_tailor(session, *, review_path, **kw):
        captured["review_path"] = review_path
        return {}

    monkeypatch.setattr(cli, "tailor", fake_tailor)
    result = runner.invoke(
        cli.app,
        ["tailor", "--approved", "--deep", "--review", "custom.yaml", "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert captured["review_path"] == "custom.yaml"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_tailor_deep.py -v`
Expected: FAIL — `No such option: --deep`.

- [ ] **Step 3: Implement.** In `services/tailoring.py` under `DEFAULT_REVIEW` add:

```python
DEFAULT_REVIEW_DEEP = "config/review_deep.yaml"
```

In `cli.py`, next to `DEFAULT_REVIEW` add `DEFAULT_REVIEW_DEEP = "config/review_deep.yaml"`, then in `tailor_cmd` add the option and resolution:

```python
    deep: bool = typer.Option(
        False, "--deep", help="Use the full multi-round review roster (config/review_deep.yaml)."
    ),
```

and before calling `tailor(...)`:

```python
        if deep and review == DEFAULT_REVIEW:
            review = DEFAULT_REVIEW_DEEP
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_tailor_deep.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/tailoring.py src/resume_agent/cli.py tests/test_cli_tailor_deep.py
git commit -m "feat(cli): tailor --deep swaps in the deep review roster"
```

---

### Task 8: API `deep` param + contract regeneration

**Files:**

- Modify: `src/resume_agent/api/schemas/runs.py:53-56`, `src/resume_agent/api/routers/runs.py:148-177`
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` (whichever `gen_ts_client.sh` writes)
- Test: `tests/api/test_runs_launch.py`

**Interfaces:**

- Consumes: `DEFAULT_REVIEW`, `DEFAULT_REVIEW_DEEP` (Task 7).
- Produces: `TailorParams.deep: bool = False` (wire: `"deep"`); `POST /api/tailor` with `{"deep": true}` runs against `config/review_deep.yaml`. Task 9's web client sees `deep` in the generated schema.

- [ ] **Step 1: Write the failing test** — append to `tests/api/test_runs_launch.py`:

```python
def test_tailor_launch_maps_deep_to_review_path(monkeypatch, tmp_path):
    captured = {}

    def fake_tailor(session, *, reporter=None, **kw):
        captured["review_path"] = kw.get("review_path")
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {}

    monkeypatch.setattr(runs_router, "tailor", fake_tailor)
    client = _client(tmp_path)
    with client:
        client.post("/api/tailor", json={"approved": True, "deep": True})
    assert captured["review_path"] == "config/review_deep.yaml"

    with client:
        client.post("/api/tailor", json={"approved": True})
    assert captured["review_path"] == "config/review.yaml"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v -k deep`
Expected: FAIL — `review_path` is `None` (router doesn't pass it).

- [ ] **Step 3: Implement.** `schemas/runs.py`:

```python
class TailorParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False
    deep: bool = False
```

`routers/runs.py` — import the constants and pass the path:

```python
from resume_agent.services.tailoring import DEFAULT_REVIEW, DEFAULT_REVIEW_DEEP

# inside launch_tailor's work():
            results = tailor(
                session,
                job_ids=params.job_ids,
                approved=params.approved,
                review_path=DEFAULT_REVIEW_DEEP if params.deep else DEFAULT_REVIEW,
                reporter=reporter,
                fail_on_partial=True,
            )
```

(Adjust the import to match how the router currently imports `tailor` — extend that import line.)

- [ ] **Step 4: Regenerate contracts**

Run: `bash scripts/gen_ts_client.sh`
Expected: `contracts/openapi.json` + TS output updated; `git diff` shows `deep` added to the tailor request schema.

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api -v`
Expected: PASS, including `test_openapi_contract.py`.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api tests/api contracts web/src/lib/api
git commit -m "feat(api): deep flag on tailor launch selects the deep review roster"
```

---

### Task 9: Web launchers for selected jobs

**Files:**

- Modify: `web/src/features/runs/use-bulk-run.ts`
- Test: `web/src/features/runs/use-bulk-run.test.tsx`

**Interfaces:**

- Consumes: regenerated API schema with `deep` + `jobIds` (Task 8).
- Produces: `useBulkRun()` additionally returns `tailorSelected(jobIds: number[], deep: boolean)` and `coverLettersSelected(jobIds: number[])`, both returning `Promise<boolean>` like the existing launchers. Task 10's dialog calls these.

- [ ] **Step 1: Write the failing test** — extend `use-bulk-run.test.tsx`:

```tsx
it("exposes selected-job launchers", () => {
  const { result } = renderHook(() => useBulkRun(), { wrapper });
  expect(typeof result.current.tailorSelected).toBe("function");
  expect(typeof result.current.coverLettersSelected).toBe("function");
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `web/`): `npx vitest run src/features/runs/use-bulk-run.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement** — in `use-bulk-run.ts` add to the returned object:

```ts
    tailorSelected: (jobIds: number[], deep: boolean) =>
      launch("tailor", () =>
        unwrap(api.POST("/api/tailor", { body: { jobIds, deep } })),
      ),
    coverLettersSelected: (jobIds: number[]) =>
      launch("coverLetter", () =>
        unwrap(api.POST("/api/cover-letters", { body: { jobIds } })),
      ),
```

- [ ] **Step 4: Run tests**

Run (from `web/`): `npx vitest run src/features/runs/use-bulk-run.test.tsx`
Expected: PASS (TypeScript compiles — proves the regenerated schema carries `deep`).

- [ ] **Step 5: Commit**

```bash
git add web/src/features/runs/use-bulk-run.ts web/src/features/runs/use-bulk-run.test.tsx
git commit -m "feat(web): launchers for tailoring/cover-lettering selected jobs"
```

---

### Task 10: Tailor launch dialog + Pipeline wiring

**Files:**

- Create: `web/src/features/runs/LaunchDialog.tsx`
- Test: `web/src/features/runs/LaunchDialog.test.tsx` (new)
- Modify: `web/src/features/pipeline/PipelineContainer.tsx:107-119`, `web/src/features/pipeline/PipelineContainer.test.tsx`

**Interfaces:**

- Consumes: `tailorSelected`/`coverLettersSelected` (Task 9); shadcn `Dialog`, `Checkbox`, `Switch`, `Button` from `web/src/components/ui/`.
- Produces:

```tsx
export interface LaunchJob {
  jobId: number;
  company: string | null;
  title: string;
}
export function LaunchDialog(props: {
  mode: "tailor" | "coverLetter";
  jobs: LaunchJob[]; // approved jobs currently loaded
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLaunch: (jobIds: number[], deep: boolean) => void;
}): JSX.Element;
```

- [ ] **Step 1: Write the failing test** — `LaunchDialog.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LaunchDialog } from "./LaunchDialog";

const jobs = [
  { jobId: 1, company: "Acme", title: "Senior Backend Engineer" },
  { jobId: 2, company: "Globex", title: "Platform Engineer" },
];

describe("LaunchDialog", () => {
  it("pre-checks all jobs and launches the selected subset with the deep flag", () => {
    const onLaunch = vi.fn();
    render(
      <LaunchDialog
        mode="tailor"
        jobs={jobs}
        open
        onOpenChange={() => {}}
        onLaunch={onLaunch}
      />,
    );
    // Uncheck job 2, flip deep on
    fireEvent.click(screen.getByRole("checkbox", { name: /Globex/ }));
    fireEvent.click(screen.getByRole("switch", { name: /deep review/i }));
    fireEvent.click(screen.getByRole("button", { name: /tailor 1 job/i }));
    expect(onLaunch).toHaveBeenCalledWith([1], true);
  });

  it("hides the deep switch in coverLetter mode", () => {
    render(
      <LaunchDialog
        mode="coverLetter"
        jobs={jobs}
        open
        onOpenChange={() => {}}
        onLaunch={vi.fn()}
      />,
    );
    expect(screen.queryByRole("switch")).toBeNull();
    expect(
      screen.getByRole("button", { name: /write 2 cover letters/i }),
    ).toBeEnabled();
  });

  it("disables submit when nothing is selected", () => {
    render(
      <LaunchDialog
        mode="tailor"
        jobs={[jobs[0]]}
        open
        onOpenChange={() => {}}
        onLaunch={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /Acme/ }));
    expect(screen.getByRole("button", { name: /tailor/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `web/`): `npx vitest run src/features/runs/LaunchDialog.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `LaunchDialog.tsx`.** Follow the repo's existing dialog usage (see another feature's `Dialog` consumer for idiom). Skeleton:

```tsx
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export interface LaunchJob {
  jobId: number;
  company: string | null;
  title: string;
}

const COPY = {
  tailor: { title: "Tailor resumes", verb: "Tailor", noun: "job" },
  coverLetter: {
    title: "Write cover letters",
    verb: "Write",
    noun: "cover letter",
  },
} as const;

export function LaunchDialog({
  mode,
  jobs,
  open,
  onOpenChange,
  onLaunch,
}: {
  mode: "tailor" | "coverLetter";
  jobs: LaunchJob[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLaunch: (jobIds: number[], deep: boolean) => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deep, setDeep] = useState(false);
  useEffect(() => {
    if (open) {
      setSelected(new Set(jobs.map((j) => j.jobId)));
      setDeep(false);
    }
  }, [open, jobs]);

  const copy = COPY[mode];
  const count = selected.size;
  const submitLabel =
    mode === "tailor"
      ? `Tailor ${count} job${count === 1 ? "" : "s"}`
      : `Write ${count} cover letter${count === 1 ? "" : "s"}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
        </DialogHeader>
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {jobs.map((job) => {
            const label = `${job.company ?? "?"} — ${job.title}`;
            return (
              <label
                key={job.jobId}
                className="flex items-center gap-2 text-sm"
              >
                <Checkbox
                  aria-label={label}
                  checked={selected.has(job.jobId)}
                  onCheckedChange={(checked) => {
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (checked) next.add(job.jobId);
                      else next.delete(job.jobId);
                      return next;
                    });
                  }}
                />
                {label}
              </label>
            );
          })}
          {jobs.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No approved jobs to process.
            </p>
          )}
        </div>
        {mode === "tailor" && (
          <div className="flex items-center gap-2">
            <Switch
              id="deep-review"
              aria-label="Deep review"
              checked={deep}
              onCheckedChange={setDeep}
            />
            <Label htmlFor="deep-review">
              Deep review (full panel, ~3-6x slower)
            </Label>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={count === 0}
            onClick={() => {
              onLaunch([...selected], deep);
              onOpenChange(false);
            }}
          >
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

Verify the exact shadcn export names against `web/src/components/ui/dialog.tsx` / `checkbox.tsx` / `switch.tsx` and adjust.

- [ ] **Step 4: Run the dialog tests**

Run (from `web/`): `npx vitest run src/features/runs/LaunchDialog.test.tsx`
Expected: PASS.

- [ ] **Step 5: Wire into `PipelineContainer.tsx`.** The container already has `rows` (all pipeline items) and `runs = useBulkRun()`. Add state and derive approved jobs (check the `PipelineItem` field name for stage/status in `web/src/lib/api/schema.ts` — use the real one):

```tsx
const [launchMode, setLaunchMode] = useState<"tailor" | "coverLetter" | null>(
  null,
);
const approvedJobs = useMemo(
  () =>
    rows
      .filter((row) => row.status === "approved")
      .map((row) => ({
        jobId: row.jobId,
        company: row.company,
        title: row.title,
      })),
  [rows],
);
```

Replace the two buttons (lines ~113-118):

```tsx
        <Button variant="outline" size="sm" onClick={() => setLaunchMode("tailor")}>
          Tailor approved…
        </Button>
        <Button variant="outline" size="sm" onClick={() => setLaunchMode("coverLetter")}>
          Cover letters…
        </Button>
```

and render the dialog:

```tsx
<LaunchDialog
  mode={launchMode ?? "tailor"}
  jobs={approvedJobs}
  open={launchMode !== null}
  onOpenChange={(open) => {
    if (!open) setLaunchMode(null);
  }}
  onLaunch={(jobIds, deep) =>
    launchMode === "coverLetter"
      ? runs.coverLettersSelected(jobIds)
      : runs.tailorSelected(jobIds, deep)
  }
/>
```

Add a `PipelineContainer.test.tsx` case: clicking "Tailor approved…" renders the dialog title "Tailor resumes" (follow that file's existing render/mock setup).

- [ ] **Step 6: Run the web suite**

Run (from `web/`): `npx vitest run`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/runs/LaunchDialog.tsx web/src/features/runs/LaunchDialog.test.tsx web/src/features/pipeline
git commit -m "feat(web): launch dialog for selective tailoring with deep-review toggle"
```

---

### Task 11: Docs + live acceptance evidence

**Files:**

- Modify: `CLAUDE.md` (Known design notes)
- No new tests (manual evidence step).

- [ ] **Step 1: Document.** Add one bullet to CLAUDE.md's "Known design notes":

```markdown
- **Tailoring is fast-by-default.** `config/review.yaml` is the fast roster: 2 rounds max,
  Sonnet writers (`tailor_tier`/`reviser_tier: mid`), and `merged_advisory: true` (one LLM
  call returns all non-gate critiques via `MergedPanelReview`, split back into the named
  per-dimension rows — `aggregate()` and persistence are identical to deep mode). The
  fact-check gate stays premium in both modes. Deep mode = `config/review_deep.yaml` via
  CLI `tailor --deep` or API `{"deep": true}`. Each `TailorRound` records
  `stage_seconds` (draft/panel/revise wall-clock).
```

- [ ] **Step 2: Full offline verification**

Run: `.venv/Scripts/python.exe -m pytest -q` and `ruff check` and (from `web/`) `npx vitest run`
Expected: all green.

- [ ] **Step 3: Live acceptance (requires API key; run with the user).** Pick 2-3 approved jobs, then:

```bash
.venv/Scripts/python.exe -m resume_agent.cli tailor --job-id <ID>          # fast
.venv/Scripts/python.exe -m resume_agent.cli tailor --job-id <ID2> --deep  # deep
```

Read the `tailor job=… total_llm_seconds=…` log lines emitted by `tailor/service.py` (Task 6). **Pass criteria (from spec):** fast median ≤ 90 s per passing job AND ≤ ~50 % of the deep wall-clock; manually eyeball both resumes for quality parity. Record the numbers in the PR/commit message.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: fast-by-default tailoring notes + acceptance evidence"
```

- [ ] **Step 2: Full offline verification**

Run: `.venv/Scripts/python.exe -m pytest -q` and `ruff check` and (from `web/`) `npx vitest run`
Expected: all green.

- [ ] **Step 3: Live acceptance (requires API key; run with the user).** Pick 2-3 approved jobs, then:

```bash
.venv/Scripts/python.exe -m resume_agent.cli tailor --job-id <ID>          # fast
.venv/Scripts/python.exe -m resume_agent.cli tailor --job-id <ID2> --deep  # deep
```

Read the `tailor job=… total_llm_seconds=…` log lines emitted by `tailor/service.py` (Task 6). **Pass criteria (from spec):** fast median ≤ 90 s per passing job AND ≤ ~50 % of the deep wall-clock; manually eyeball both resumes for quality parity. Record the numbers in the PR/commit message.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: fast-by-default tailoring notes + acceptance evidence"
```
