# Agent Prompt Registry + Web-Friendly Rendering Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every LLM agent's prompt is viewable in the web app with a per-agent user-guidance layer (fact-lock preserved), and the Rendering settings become a template picker + validated custom-template upload with no filesystem paths in the contract.

**Architecture:** A declarative `PromptSpec` registry projects instruction lists that stay defined in their home modules; a per-workspace `config/agent_guidance.yaml` is layered beneath immutable rules by a `with_guidance` helper wired into every agent builder. Rendering swaps `template_path`/`output_dir` for a template id + `fit_one_page` flag: bundled templates come from a manifest, custom `.typ` uploads are validation-compiled with Typst's `root` pinned to their own directory, and legacy `render.yaml` keys keep loading for CLI users.

**Tech Stack:** FastAPI + Pydantic (`CamelModel` camelCase wire), agno agents, typst (Python wheel, offline), React + TanStack Query + shadcn (web), pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-07-19-agent-prompts-and-render-templates-design.md`

## Global Constraints

- Tests are offline: no API key, no network. `typst.compile` is a local wheel and IS allowed in tests.
- Wire format is camelCase via `CamelModel` (`api/schemas/base.py`); Python stays snake_case.
- Every error uses the `{ "error": { code, message, details? } }` envelope via `ApiException` (`api/errors.py`).
- Error codes (exact strings): `unknown_agent` (404), `agent_not_editable` (409), `template_not_found` (422), `template_invalid` (422).
- Guidance cap: **4000 characters** per agent. Custom template cap: **200 KB**, extension `.typ` only.
- Only `reviewer-fact-check` is non-editable.
- After any schema/router change, regenerate contracts: `bash scripts/gen_ts_client.sh` (writes `contracts/openapi.json`, `contracts/ts/api.ts`, copies to `web/src/lib/api/schema.ts`). The drift gate is `tests/api/test_openapi_contract.py`.
- Workspace-relative paths always go through `resolve_tenant_path` (`tenancy/paths.py`); constants for new artifacts live in `tenancy/paths.py`.
- Backend test command: `.venv/Scripts/python.exe -m pytest <file> -q`. Lint: `ruff check`. Web tests: `cd web && npx vitest run <file>`.
- Import-cycle rule: `prompts/guidance.py` must NOT import `prompts/registry.py` (registry imports every agent module; those modules import guidance). Editability lives in `guidance.NON_EDITABLE_KEYS`; registry derives `editable` from it.

---

### Task 1: Prompt registry (`prompts/registry.py`)

**Files:**
- Create: `src/resume_agent/prompts/__init__.py` (empty)
- Create: `src/resume_agent/prompts/registry.py`
- Modify: `src/resume_agent/interview/agent.py` (extract `_PERSONA_CORE` from `persona_instructions`)
- Test: `tests/test_prompt_registry.py`

**Interfaces:**
- Consumes: instruction constants from existing agent modules (see table in Step 3).
- Produces: `PromptSpec` (frozen dataclass: `key: str`, `title: str`, `stage: str`, `description: str`, `instructions: tuple[str, ...]`, `editable: bool`), `PROMPT_SPECS: tuple[PromptSpec, ...]`, `SPECS_BY_KEY: dict[str, PromptSpec]`, `spec_for(key: str) -> PromptSpec | None`. Also `interview.agent._PERSONA_CORE: list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_registry.py
"""Registry is a projection of real agent instruction lists — never a copy."""

from resume_agent.prompts.registry import PROMPT_SPECS, SPECS_BY_KEY, spec_for

VALID_STAGES = {"tailoring", "review", "cover-letter", "discovery", "profile", "interview", "email"}


def test_keys_unique_and_lookup_matches():
    keys = [s.key for s in PROMPT_SPECS]
    assert len(keys) == len(set(keys))
    assert set(SPECS_BY_KEY) == set(keys)
    assert spec_for("tailor-writer") is SPECS_BY_KEY["tailor-writer"]
    assert spec_for("nope") is None


def test_every_spec_is_complete():
    for spec in PROMPT_SPECS:
        assert spec.stage in VALID_STAGES, spec.key
        assert spec.title and spec.description, spec.key
        assert len(spec.instructions) > 0, spec.key
        assert all(isinstance(line, str) and line for line in spec.instructions), spec.key


def test_fact_check_is_the_only_locked_agent():
    locked = {s.key for s in PROMPT_SPECS if not s.editable}
    assert locked == {"reviewer-fact-check"}


def test_registry_projects_the_real_instruction_objects():
    """Identity (not equality): the registry must import the module constant, not copy text."""
    from resume_agent.discovery import fit
    from resume_agent.tailor import agents as tailor_agents

    assert SPECS_BY_KEY["fit-score"].instructions == tuple(fit._INSTRUCTIONS)
    assert SPECS_BY_KEY["reviewer-fact-check"].instructions == tuple(
        tailor_agents.REVIEWER_INSTRUCTIONS["fact-check"]
    )


def test_interviewer_registers_the_persona_core():
    from resume_agent.interview.agent import _PERSONA_CORE

    assert SPECS_BY_KEY["interviewer"].instructions == tuple(_PERSONA_CORE)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.prompts'`

- [ ] **Step 3: Extract `_PERSONA_CORE` in `interview/agent.py`**

`persona_instructions(style)` (line ~256) currently builds one inline list: four dynamic lines (stage sentence, `_STAGE_LINES[...]`, `_DEMEANOR_LINES[...]`, difficulty sentence) followed by static lines ("Ground questions in the JOB description…", the competency-mix line, the STAR line, and any remaining static literals up to the function's return). Move the static lines verbatim into a module-level constant directly above the function, and rebuild:

```python
_PERSONA_CORE = [
    # ... the static string literals moved verbatim from persona_instructions ...
]


def persona_instructions(style: InterviewStyle) -> list[str]:
    return [
        f"You are conducting a realistic mock {style.stage} interview.",
        _STAGE_LINES[style.stage],
        _DEMEANOR_LINES[style.demeanor],
        f"Difficulty: {style.difficulty}. Calibrate question depth accordingly.",
        *_PERSONA_CORE,
    ]
```

Only lines containing f-string interpolation stay inline; everything else moves. Run the interview tests to prove no behavior change: `.venv/Scripts/python.exe -m pytest tests/ -q -k interview` — expected PASS.

- [ ] **Step 4: Write the registry**

```python
# src/resume_agent/prompts/registry.py
"""Declarative projection of every LLM agent's base prompt.

Instruction lists stay defined in their home modules; this registry imports
them, so the viewer can never drift from the code (same pattern as
CONNECTOR_SPECS). ``editable`` derives from guidance.NON_EDITABLE_KEYS —
guidance.py must never import this module (see CLAUDE.md import-cycle rule).
"""

from __future__ import annotations

from dataclasses import dataclass

from resume_agent.cover_letter import agents as cover_letter_agents
from resume_agent.discovery import extract, fit, industry, relevance, source_scout
from resume_agent.discovery.scraper import learn
from resume_agent.discovery.url_ingest import llm as url_ingest_llm
from resume_agent.interview import agent as interview_agent
from resume_agent.profile import (
    coach,
    extractor,
    inference,
    merge,
    project_extractor,
    synthesis,
)
from resume_agent.prompts.guidance import NON_EDITABLE_KEYS
from resume_agent.services import email_writer
from resume_agent.suggestions import agents as suggestions_agents
from resume_agent.tailor import agents as tailor_agents
from resume_agent.tailor import match_plan
from resume_agent.taxonomy import groups
from resume_agent.tracking import canonicalize


@dataclass(frozen=True)
class PromptSpec:
    key: str
    title: str
    stage: str  # tailoring | review | cover-letter | discovery | profile | interview | email
    description: str
    instructions: tuple[str, ...]
    editable: bool = True


def _spec(key: str, title: str, stage: str, description: str, instructions) -> PromptSpec:
    return PromptSpec(
        key=key,
        title=title,
        stage=stage,
        description=description,
        instructions=tuple(instructions),
        editable=key not in NON_EDITABLE_KEYS,
    )


PROMPT_SPECS: tuple[PromptSpec, ...] = (
    # --- tailoring ---
    _spec("tailor-writer", "Resume writer", "tailoring",
          "Writes the targeted resume from profile facts under the fact-lock.",
          tailor_agents._TAILOR_INSTRUCTIONS),
    _spec("tailor-reviser", "Resume reviser", "tailoring",
          "Repairs a reviewed resume while preserving the fact-lock.",
          tailor_agents._REVISER_INSTRUCTIONS),
    _spec("tailor-revision", "Manual revision editor", "tailoring",
          "Applies one user-requested edit without weakening the fact-lock.",
          tailor_agents._REVISION_INSTRUCTIONS),
    _spec("match-plan", "Match planner", "tailoring",
          "Plans which profile facts to emphasize for a job, by fact id only.",
          match_plan._MATCH_PLAN_INSTRUCTIONS),
    _spec("suggestions-research", "Match-gap advisor (research)", "tailoring",
          "Researches actionable suggestions for skill and evidence gaps.",
          suggestions_agents._SEARCH_INSTRUCTIONS),
    _spec("suggestions-format", "Match-gap advisor (formatter)", "tailoring",
          "Formats advisor research into structured suggestions.",
          suggestions_agents._FORMAT_INSTRUCTIONS),
    # --- review ---
    _spec("reviewer-fact-check", "Fact-check gate", "review",
          "Hard gate: verifies every resume claim against cited profile facts.",
          tailor_agents.REVIEWER_INSTRUCTIONS["fact-check"]),
    _spec("reviewer-ats-keyword", "ATS keyword reviewer", "review",
          "Checks visible coverage of the job's important terms and skills.",
          tailor_agents.REVIEWER_INSTRUCTIONS["ats-keyword"]),
    _spec("reviewer-recruiter", "Recruiter reviewer", "review",
          "Fast first-scan review: clarity, ordering, credible impact.",
          tailor_agents.REVIEWER_INSTRUCTIONS["recruiter"]),
    _spec("reviewer-hiring-manager", "Hiring-manager reviewer", "review",
          "Technical credibility against the job's core responsibilities.",
          tailor_agents.REVIEWER_INSTRUCTIONS["hiring-manager"]),
    _spec("reviewer-concision", "Concision reviewer", "review",
          "Prioritization, repetition, bullet length, one-page density.",
          tailor_agents.REVIEWER_INSTRUCTIONS["concision"]),
    # --- cover-letter ---
    _spec("cover-letter-draft", "Cover letter writer", "cover-letter",
          "Drafts a cover letter grounded in profile facts.",
          cover_letter_agents._DRAFT_INSTRUCTIONS),
    _spec("cover-letter-revise", "Cover letter reviser", "cover-letter",
          "Revises a cover letter from reviewer feedback.",
          cover_letter_agents._REVISE_INSTRUCTIONS),
    _spec("cover-letter-revision", "Cover letter revision editor", "cover-letter",
          "Applies one user-requested cover-letter edit.",
          cover_letter_agents._REVISION_INSTRUCTIONS),
    # --- discovery ---
    _spec("extract-criteria", "Job criteria extractor", "discovery",
          "Extracts structured criteria from a job description.",
          extract._INSTRUCTIONS),
    _spec("fit-score", "Fit scorer", "discovery",
          "Scores how well the profile fits a job.",
          fit._INSTRUCTIONS),
    _spec("relevance-judge", "Relevance judge", "discovery",
          "Judges whether a discovered job matches the configured search.",
          relevance._INSTRUCTIONS),
    _spec("industry-classifier", "Industry classifier", "discovery",
          "Normalizes a job's company industry.",
          industry._INSTRUCTIONS),
    _spec("url-ingest", "URL job parser", "discovery",
          "Parses a job posting from a pasted URL's page content.",
          url_ingest_llm._INSTRUCTIONS),
    _spec("scraper-learn", "Scraper recipe learner", "discovery",
          "Learns a reusable browser recipe for a careers dashboard.",
          learn._INSTRUCTIONS),
    _spec("source-scout-research", "Source scout (research)", "discovery",
          "Researches new job sources for the configured search.",
          source_scout._RESEARCH_INSTRUCTIONS),
    _spec("source-scout-format", "Source scout (formatter)", "discovery",
          "Formats scout research into structured source proposals.",
          source_scout._FORMAT_INSTRUCTIONS),
    # --- profile ---
    _spec("profile-extractor", "Profile fact extractor", "profile",
          "Extracts structured facts from an uploaded document.",
          extractor._INSTRUCTIONS),
    _spec("profile-synthesis", "Synthesis writer", "profile",
          "Synthesizes excerpt-backed facts from supporting decks.",
          synthesis._SYNTHESIS_INSTRUCTIONS),
    _spec("profile-entailment", "Synthesis verifier", "profile",
          "Verifies each synthesized fact is entailed by its excerpts.",
          synthesis._ENTAILMENT_INSTRUCTIONS),
    _spec("project-extractor", "Project extractor", "profile",
          "Extracts exactly one Project (plus skills) from a project source.",
          project_extractor._INSTRUCTIONS),
    _spec("skill-inference", "Skill inferrer", "profile",
          "Derives evidence-pointer inferred skills from literal facts.",
          inference._INSTRUCTIONS),
    _spec("profile-dedup", "Fact deduplicator", "profile",
          "Merges duplicate facts across profile sources.",
          merge._DEDUP_INSTRUCTIONS),
    _spec("coach", "Profile coach", "profile",
          "Runs the evidence-locked profile coaching conversation.",
          coach._COACH_INSTRUCTIONS),
    _spec("coach-formatter", "Coach formatter", "profile",
          "Formats a coach turn into the structured turn schema.",
          coach._FORMAT_INSTRUCTIONS),
    _spec("skill-groups", "Skill-group classifier", "profile",
          "Assigns matrix skill tokens to the fixed group vocabulary.",
          groups._GROUP_INSTRUCTIONS),
    _spec("taxonomy-clusters", "Taxonomy clusterer", "profile",
          "Clusters skill tokens into domains for the constellation.",
          canonicalize._INSTRUCTIONS),
    _spec("taxonomy-themes", "Taxonomy themes (legacy)", "profile",
          "Legacy theme pass over clustered skills.",
          canonicalize._THEME_INSTRUCTIONS),
    _spec("taxonomy-clusters-incremental", "Taxonomy incremental clusterer", "profile",
          "Classifies new tokens into existing clusters.",
          canonicalize._INCREMENTAL_INSTRUCTIONS),
    _spec("taxonomy-domains-incremental", "Taxonomy incremental domains", "profile",
          "Assigns new clusters to existing domains.",
          canonicalize._INCREMENTAL_DOMAIN_INSTRUCTIONS),
    # --- interview ---
    _spec("interviewer", "Mock interviewer", "interview",
          "In-character interviewer core (stage/difficulty lines are added per session).",
          interview_agent._PERSONA_CORE),
    _spec("interview-debrief", "Interview debrief", "interview",
          "Scores the interview and writes the debrief.",
          interview_agent._DEBRIEF_INSTRUCTIONS),
    _spec("interview-format", "Interview formatter", "interview",
          "Formats interviewer turns into the structured schema.",
          interview_agent._FORMAT_INSTRUCTIONS),
    # --- email ---
    _spec("email-writer", "Email writer", "email",
          "Drafts outreach/follow-up emails grounded in facts.json only.",
          email_writer._WRITER_INSTRUCTIONS),
)

SPECS_BY_KEY: dict[str, PromptSpec] = {s.key: s for s in PROMPT_SPECS}


def spec_for(key: str) -> PromptSpec | None:
    return SPECS_BY_KEY.get(key)
```

Note: this file imports `NON_EDITABLE_KEYS` from `prompts/guidance.py`, which Task 2 creates. For this task, create a minimal `src/resume_agent/prompts/guidance.py` containing only:

```python
# src/resume_agent/prompts/guidance.py
NON_EDITABLE_KEYS = frozenset({"reviewer-fact-check"})
```

Task 2 fills in the rest of that file. If any `_INSTRUCTIONS` constant name above does not match the module (verify with `grep -n "_INSTRUCTIONS" <file>`), use the module's actual module-level constant that the builder passes to `Agent(instructions=...)` — never paste text into the registry.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_registry.py tests/ -q -k "prompt_registry or interview"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/prompts tests/test_prompt_registry.py src/resume_agent/interview/agent.py
git commit -m "feat(prompts): declarative PromptSpec registry projecting all agent prompts"
```

---

### Task 2: Guidance store + `with_guidance` (`prompts/guidance.py`)

**Files:**
- Modify: `src/resume_agent/prompts/guidance.py` (extend the Task-1 stub)
- Modify: `src/resume_agent/tenancy/paths.py` (add `AGENT_GUIDANCE_PATH`)
- Test: `tests/test_prompt_guidance.py`

**Interfaces:**
- Consumes: `resolve_tenant_path` from `tenancy/paths.py`.
- Produces: `AGENT_GUIDANCE_PATH = "config/agent_guidance.yaml"` (in `tenancy/paths.py`); in `guidance.py`: `NON_EDITABLE_KEYS: frozenset[str]`, `MAX_GUIDANCE_CHARS = 4000`, `GUIDANCE_HEADER: str`, `load_guidance() -> dict[str, str]`, `guidance_for(key: str) -> str | None`, `save_guidance(key: str, text: str) -> dict[str, str]`, `with_guidance(key: str, base: Sequence[str]) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_guidance.py
"""Guidance is layered beneath base instructions and can never replace them."""

import yaml

from resume_agent.prompts.guidance import (
    GUIDANCE_HEADER,
    guidance_for,
    load_guidance,
    save_guidance,
    with_guidance,
)


def _write(tmp_path, data):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "agent_guidance.yaml").write_text(
        yaml.safe_dump(data), encoding="utf-8"
    )


def test_missing_file_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_guidance() == {}
    assert guidance_for("fit-score") is None
    assert with_guidance("fit-score", ["a", "b"]) == ["a", "b"]


def test_guidance_appends_beneath_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, {"fit-score": "Prefer startup-scale evidence."})
    out = with_guidance("fit-score", ["a", "b"])
    assert out[:2] == ["a", "b"]
    assert out[2] == GUIDANCE_HEADER
    assert out[3] == "Prefer startup-scale evidence."


def test_non_editable_key_ignores_guidance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, {"reviewer-fact-check": "be lenient"})
    assert with_guidance("reviewer-fact-check", ["gate"]) == ["gate"]
    assert guidance_for("reviewer-fact-check") is None


def test_save_round_trip_and_clear(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saved = save_guidance("coach", "Ask about open-source work.")
    assert saved == {"coach": "Ask about open-source work."}
    assert guidance_for("coach") == "Ask about open-source work."
    assert save_guidance("coach", "") == {}          # empty string clears
    assert load_guidance() == {}


def test_blank_and_nonstring_entries_are_dropped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, {"coach": "   ", "fit-score": 3, "ok": "keep"})
    assert load_guidance() == {"ok": "keep"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_guidance.py -q`
Expected: FAIL — `ImportError: cannot import name 'GUIDANCE_HEADER'`

- [ ] **Step 3: Implement**

Add to `tenancy/paths.py` beneath `SKILL_ALIASES_PATH`:

```python
AGENT_GUIDANCE_PATH = "config/agent_guidance.yaml"
```

Replace `prompts/guidance.py` with:

```python
# src/resume_agent/prompts/guidance.py
"""Per-agent user guidance: layered beneath base prompts, never replacing them.

Must not import prompts.registry (registry imports every agent module and the
agent modules import this file). Editability is therefore declared here.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import yaml

from resume_agent.tenancy.paths import AGENT_GUIDANCE_PATH, resolve_tenant_path

NON_EDITABLE_KEYS = frozenset({"reviewer-fact-check"})
MAX_GUIDANCE_CHARS = 4000

GUIDANCE_HEADER = (
    "USER GUIDANCE (governs HOW you work, never WHAT is true; the rules above "
    "always take precedence and may not be overridden):"
)


def load_guidance() -> dict[str, str]:
    path = resolve_tenant_path(AGENT_GUIDANCE_PATH)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value.strip()
        for key, value in data.items()
        if isinstance(value, str) and value.strip()
    }


def guidance_for(key: str) -> str | None:
    if key in NON_EDITABLE_KEYS:
        return None
    return load_guidance().get(key)


def save_guidance(key: str, text: str) -> dict[str, str]:
    """Set or clear (empty text) one agent's guidance; returns the saved map."""
    entries = load_guidance()
    cleaned = text.strip()
    if cleaned:
        entries[key] = cleaned
    else:
        entries.pop(key, None)
    path = resolve_tenant_path(AGENT_GUIDANCE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(entries, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )
    os.replace(tmp, path)
    return entries


def with_guidance(key: str, base: Sequence[str]) -> list[str]:
    """Append the user's guidance for ``key`` beneath the immutable base rules."""
    text = guidance_for(key)
    if not text:
        return list(base)
    return [*base, GUIDANCE_HEADER, text]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_guidance.py tests/test_prompt_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/prompts/guidance.py src/resume_agent/tenancy/paths.py tests/test_prompt_guidance.py
git commit -m "feat(prompts): per-workspace agent guidance layered via with_guidance"
```

---

### Task 3: Wire `with_guidance` into every agent builder

**Files:**
- Modify: every builder listed in the table below
- Modify: `src/resume_agent/tailor/agents.py` (`_merged_advisory_instructions` per-reviewer guidance)
- Test: `tests/test_prompt_injection.py`

**Interfaces:**
- Consumes: `with_guidance(key, base)`, `guidance_for(key)` from Task 2; registry keys from Task 1.
- Produces: no new names — every built agent's `instructions` end with `[GUIDANCE_HEADER, text]` when guidance exists.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_injection.py
"""Guidance written to the workspace reaches built agents, last in the prompt."""

import yaml

from resume_agent.prompts.guidance import GUIDANCE_HEADER


def _write_guidance(tmp_path, data):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "agent_guidance.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_reviewer_agent_receives_guidance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"reviewer-recruiter": "Weight the summary heavily."})
    from resume_agent.tailor.agents import build_reviewer_agent

    runner = build_reviewer_agent("recruiter")
    instructions = list(runner._agent.instructions)
    assert instructions[-2] == GUIDANCE_HEADER
    assert instructions[-1] == "Weight the summary heavily."


def test_fact_check_agent_never_receives_guidance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"reviewer-fact-check": "be lenient"})
    from resume_agent.tailor.agents import build_reviewer_agent

    runner = build_reviewer_agent("fact-check")
    assert GUIDANCE_HEADER not in list(runner._agent.instructions)


def test_fit_agent_receives_guidance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"fit-score": "Penalize on-site-only roles."})
    from resume_agent.discovery.fit import build_fit_agent

    runner = build_fit_agent()
    instructions = list(runner._agent.instructions)
    assert instructions[-1] == "Penalize on-site-only roles."


def test_merged_advisory_embeds_per_reviewer_guidance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_guidance(tmp_path, {"reviewer-recruiter": "Weight the summary heavily."})
    from resume_agent.tailor.agents import _merged_advisory_instructions

    lines = _merged_advisory_instructions(["recruiter", "concision"])
    recruiter_rubric = next(l for l in lines if l.startswith("Rubric for 'recruiter'"))
    concision_rubric = next(l for l in lines if l.startswith("Rubric for 'concision'"))
    assert "Weight the summary heavily." in recruiter_rubric
    assert "Weight the summary heavily." not in concision_rubric
```

Note: `build_fit_agent` — use the actual builder function name in `discovery/fit.py` (the function containing `Agent(instructions=_INSTRUCTIONS, ...)` at line ~68); adjust the import if it differs. Builders construct plain agno objects — no key or network needed. Guidance loading happens at **build time**, which is per-call in this codebase (builders are invoked per run), so no caching concerns.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_injection.py -q`
Expected: FAIL — guidance text absent from instructions.

- [ ] **Step 3: Wire the sites**

The transformation is identical everywhere: wrap the final composed instruction list in `with_guidance("<key>", ...)`, importing `from resume_agent.prompts.guidance import with_guidance` at each module top. Exact key ↔ site map:

| File | Site | Wrap |
| --- | --- | --- |
| `tailor/agents.py` | `build_tailor_agent` | `with_guidance("tailor-writer", compose_instructions(_writer_instructions(_TAILOR_INSTRUCTIONS), style_guide))` |
| `tailor/agents.py` | `build_reviser_agent` | `with_guidance("tailor-reviser", compose_instructions(...))` |
| `tailor/agents.py` | `build_revision_agent` | `with_guidance("tailor-revision", compose_instructions(...))` |
| `tailor/agents.py` | `build_reviewer_agent` | `with_guidance(f"reviewer-{name}", compose_instructions(...))` |
| `tailor/match_plan.py` | `build_match_plan_agent` | `with_guidance("match-plan", compose_instructions(...))` |
| `cover_letter/agents.py` | draft / revise / revision builders | `"cover-letter-draft"` / `"cover-letter-revise"` / `"cover-letter-revision"` |
| `discovery/extract.py:60` | criteria builder | `"extract-criteria"` |
| `discovery/fit.py:68` | fit builder | `"fit-score"` |
| `discovery/relevance.py:49` | relevance builder | `"relevance-judge"` |
| `discovery/industry.py:158` | industry builder | `"industry-classifier"` |
| `discovery/url_ingest/llm.py:35` | URL parser builder | `"url-ingest"` |
| `discovery/scraper/learn.py:53` | recipe learner | `"scraper-learn"` |
| `discovery/source_scout.py:104,118` | research / format | `"source-scout-research"` / `"source-scout-format"` |
| `suggestions/agents.py:94,107` | research / format | `"suggestions-research"` / `"suggestions-format"` |
| `profile/extractor.py:43` | extractor | `"profile-extractor"` |
| `profile/synthesis.py:126,152` | synthesis / entailment | `"profile-synthesis"` / `"profile-entailment"` |
| `profile/project_extractor.py:47` | project extractor | `"project-extractor"` |
| `profile/inference.py:56` | inferrer | `"skill-inference"` |
| `profile/merge.py:140` | dedup | `"profile-dedup"` |
| `profile/coach.py:406,420` | coach / formatter | `"coach"` / `with_guidance("coach-formatter", _formatter_instructions(schema))` |
| `taxonomy/groups.py:117` | group classifier | `"skill-groups"` |
| `tracking/canonicalize.py:180,194,236,252` | four builders | `"taxonomy-clusters"` / `"taxonomy-themes"` / `"taxonomy-clusters-incremental"` / `"taxonomy-domains-incremental"` |
| `interview/agent.py:297,309,322` | persona / debrief / format | `with_guidance("interviewer", persona_instructions(style))` / `"interview-debrief"` / `"interview-format"` |
| `services/email_writer.py:88` | email writer | `with_guidance("email-writer", list(_WRITER_INSTRUCTIONS))` |

For the merged advisory panel, edit `_merged_advisory_instructions` in `tailor/agents.py` — after building `rubric` for each name, append that reviewer's guidance into its rubric line:

```python
from resume_agent.prompts.guidance import guidance_for, with_guidance  # module top

    for name in names:
        rubric = [
            *([_SCORE_BAND_INSTRUCTION] if bands.get(name, False) else []),
            *REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS),
            *CRAFT_REVIEWERS.get(name, []),
        ]
        guidance = guidance_for(f"reviewer-{name}")
        if guidance:
            rubric.append(
                f"User guidance for {name!r} (governs HOW, never WHAT is true): {guidance}"
            )
        instructions.append(f"Rubric for {name!r}: " + " ".join(rubric))
```

(`guidance_for` already returns `None` for `reviewer-fact-check`, and fact-check never appears in advisory rosters.)

- [ ] **Step 4: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (existing agent tests unaffected — guidance file absent means `with_guidance` is identity). Then `ruff check` — clean.

- [ ] **Step 5: Commit**

```bash
git add -A src tests/test_prompt_injection.py
git commit -m "feat(prompts): layer user guidance into every agent builder"
```

---

### Task 4: Prompts API (`GET /api/agents/prompts`, `PUT /api/agents/prompts/{key}`)

**Files:**
- Create: `src/resume_agent/api/schemas/prompts.py`
- Create: `src/resume_agent/api/routers/prompts.py`
- Modify: `src/resume_agent/api/app.py` (include router, guarded)
- Modify: `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` (regenerated)
- Test: `tests/api/test_prompts_api.py`

**Interfaces:**
- Consumes: `PROMPT_SPECS`, `spec_for` (Task 1); `guidance_for` raw map via `load_guidance`, `save_guidance`, `MAX_GUIDANCE_CHARS` (Task 2); `ApiException` (`api/errors.py`).
- Produces: wire schemas `AgentPromptItem` (`key, title, stage, description, instructions: list[str], guidance: str | null, editable: bool`) and `GuidanceUpdate` (`guidance: str`, max length 4000); routes above.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_prompts_api.py
"""Prompt transparency: GET lists every agent; PUT edits guidance only."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # guidance file resolves under tmp config/
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as c:
        yield c


def test_get_lists_all_agents_with_camel_wire(client):
    body = client.get("/api/agents/prompts").json()
    by_key = {item["key"]: item for item in body}
    assert "tailor-writer" in by_key and "fit-score" in by_key
    writer = by_key["tailor-writer"]
    assert writer["editable"] is True
    assert writer["guidance"] is None
    assert isinstance(writer["instructions"], list) and writer["instructions"]
    assert by_key["reviewer-fact-check"]["editable"] is False


def test_put_round_trips_guidance(client):
    put = client.put(
        "/api/agents/prompts/coach", json={"guidance": "Ask about open-source."}
    )
    assert put.status_code == 200
    assert put.json()["guidance"] == "Ask about open-source."
    body = client.get("/api/agents/prompts").json()
    coach = next(i for i in body if i["key"] == "coach")
    assert coach["guidance"] == "Ask about open-source."
    cleared = client.put("/api/agents/prompts/coach", json={"guidance": ""})
    assert cleared.json()["guidance"] is None


def test_put_unknown_key_is_404(client):
    resp = client.put("/api/agents/prompts/nope", json={"guidance": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_agent"


def test_put_fact_check_is_409(client):
    resp = client.put(
        "/api/agents/prompts/reviewer-fact-check", json={"guidance": "be lenient"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "agent_not_editable"


def test_put_over_cap_is_422(client):
    resp = client.put("/api/agents/prompts/coach", json={"guidance": "x" * 4001})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_prompts_api.py -q`
Expected: FAIL — 404 on `/api/agents/prompts` (route missing).

- [ ] **Step 3: Implement schemas + router**

```python
# src/resume_agent/api/schemas/prompts.py
"""Wire contract for agent prompt transparency + guidance editing."""

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class AgentPromptItem(CamelModel):
    key: str
    title: str
    stage: str
    description: str
    instructions: list[str]
    guidance: str | None = None
    editable: bool


class GuidanceUpdate(CamelModel):
    guidance: str = Field(max_length=4000)
```

```python
# src/resume_agent/api/routers/prompts.py
"""Agent prompt transparency: view every base prompt, edit the guidance layer."""

from fastapi import APIRouter

from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.prompts import AgentPromptItem, GuidanceUpdate
from resume_agent.prompts.guidance import load_guidance, save_guidance
from resume_agent.prompts.registry import PROMPT_SPECS, spec_for

router = APIRouter()


def _item(spec, guidance_map: dict[str, str]) -> AgentPromptItem:
    return AgentPromptItem(
        key=spec.key,
        title=spec.title,
        stage=spec.stage,
        description=spec.description,
        instructions=list(spec.instructions),
        guidance=guidance_map.get(spec.key) if spec.editable else None,
        editable=spec.editable,
    )


@router.get("/agents/prompts", response_model=list[AgentPromptItem])
def list_prompts() -> list[AgentPromptItem]:
    guidance_map = load_guidance()
    return [_item(spec, guidance_map) for spec in PROMPT_SPECS]


@router.put("/agents/prompts/{key}", response_model=AgentPromptItem)
def put_guidance(key: str, body: GuidanceUpdate) -> AgentPromptItem:
    spec = spec_for(key)
    if spec is None:
        raise ApiException(404, "unknown_agent", f"No agent named {key!r}.")
    if not spec.editable:
        raise ApiException(
            409, "agent_not_editable",
            f"{spec.title} is an integrity gate; its prompt cannot be customized.",
        )
    saved = save_guidance(key, body.guidance)
    return _item(spec, saved)
```

In `api/app.py`, import the router alongside the others (`from resume_agent.api.routers import prompts as prompts_router`) and include it next to the config router (line ~290):

```python
app.include_router(prompts_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run tests, regenerate contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_prompts_api.py -q` — expected PASS.
Run: `bash scripts/gen_ts_client.sh` then `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q` — expected PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api tests/api/test_prompts_api.py contracts web/src/lib/api/schema.ts
git commit -m "feat(api): agent prompt transparency + guidance endpoints"
```

---

### Task 5: Review structural knobs (`merged_advisory`, writer tiers) in contract + web

**Files:**
- Modify: `src/resume_agent/api/schemas/config.py` (`ReviewConfigDoc`)
- Modify: `web/src/features/settings/pages/ReviewSettingsPage.tsx`
- Modify: `contracts/*`, `web/src/lib/api/schema.ts` (regenerated)
- Test: `tests/api/test_config_router.py` (extend), `web/src/features/settings/pages/ReviewSettingsPage.test.tsx` (create if absent)

**Interfaces:**
- Consumes: existing `ReviewConfigDoc`, `useConfig`/`useSaveConfig`.
- Produces: `ReviewConfigDoc.merged_advisory: bool = False`, `tailor_tier: Literal["cheap","mid","premium"] = "premium"`, `reviser_tier: Literal["cheap","mid","premium"] = "premium"` (wire: `mergedAdvisory`, `tailorTier`, `reviserTier`). These names mirror `tailor/review_config.py:31-33`, which already reads them from `review.yaml` — the Doc addition makes the web PUT stop silently dropping them.

- [ ] **Step 1: Write the failing backend test** — append to `tests/api/test_config_router.py`:

```python
def test_review_structural_knobs_round_trip(client):
    body = client.get("/api/config/review").json()
    assert body["mergedAdvisory"] is False
    assert body["tailorTier"] == "premium"
    put = client.put("/api/config/review", json={
        **body, "mergedAdvisory": True, "tailorTier": "mid", "reviserTier": "mid",
    })
    assert put.status_code == 200
    saved = client.get("/api/config/review").json()
    assert saved["mergedAdvisory"] is True and saved["reviserTier"] == "mid"
```

- [ ] **Step 2: Run to verify it fails** — `.venv/Scripts/python.exe -m pytest tests/api/test_config_router.py -q` → FAIL (`KeyError: 'mergedAdvisory'`).

- [ ] **Step 3: Implement** — in `api/schemas/config.py` add to `ReviewConfigDoc` (import `Literal` from `typing`):

```python
class ReviewConfigDoc(CamelModel):
    max_rounds: int = 3
    score_threshold: int = 85
    merged_advisory: bool = False
    tailor_tier: Literal["cheap", "mid", "premium"] = "premium"
    reviser_tier: Literal["cheap", "mid", "premium"] = "premium"
    reviewers: list[ReviewerEntry] = Field(default_factory=_default_reviewers)
    length_budget: LengthBudget | None = None
```

Run the test → PASS. Regenerate contracts: `bash scripts/gen_ts_client.sh`; run `tests/api/test_openapi_contract.py` → PASS.

- [ ] **Step 4: Web — extend `ReviewSettingsPage.tsx`**

Below the Max rounds / threshold fields, add a "Pipeline" `FieldGroup` with:
- a `Switch` bound to `draft.mergedAdvisory` labeled "Merge advisory reviews into one call" with description "Faster and cheaper; turn off to run each advisory reviewer separately."
- two `ToggleGroup`s (same component pattern the page already uses for `modelTier`, line ~94) bound to `draft.tailorTier` and `draft.reviserTier`, labeled "Writer model tier" and "Reviser model tier", options cheap/mid/premium.

Write `ReviewSettingsPage.test.tsx` following the pattern of `web/src/features/settings/pages/PruningSettingsPage.test.tsx` (mock `use-config` hooks, render, assert the switch and both toggle groups appear and that toggling marks the draft dirty).

- [ ] **Step 5: Run web tests** — `cd web && npx vitest run src/features/settings/pages/ReviewSettingsPage.test.tsx` → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/schemas/config.py tests/api/test_config_router.py contracts web
git commit -m "feat(review): expose merged-advisory + writer tiers in contract and settings UI"
```

---

### Task 6: Web — Agent Prompts settings page

**Files:**
- Create: `web/src/features/settings/use-prompts.ts`
- Create: `web/src/features/settings/pages/AgentPromptsPage.tsx`
- Create: `web/src/features/settings/pages/AgentPromptsPage.test.tsx`
- Modify: `web/src/app/router.tsx` (lazy route `agent-prompts`), `web/src/features/settings/SettingsLayout.tsx` (`SETTINGS_NAV` entry)

**Interfaces:**
- Consumes: `/api/agents/prompts` GET/PUT from the regenerated `schema.ts`; `api`, `unwrap` from `@/lib/api/client`.
- Produces: `usePrompts(): UseQueryResult<AgentPromptItem[]>`, `useSaveGuidance(): UseMutationResult` (mutate `{key, guidance}`); route `/settings/agent-prompts`.

- [ ] **Step 1: Write the failing component test**

```tsx
// web/src/features/settings/pages/AgentPromptsPage.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentPromptsPage } from "./AgentPromptsPage";

const items = [
  {
    key: "tailor-writer", title: "Resume writer", stage: "tailoring",
    description: "Writes the targeted resume.", instructions: ["Rule one.", "Rule two."],
    guidance: null, editable: true,
  },
  {
    key: "reviewer-fact-check", title: "Fact-check gate", stage: "review",
    description: "Hard gate.", instructions: ["Verify claims."],
    guidance: null, editable: false,
  },
];
const save = vi.fn();

vi.mock("../use-prompts", () => ({
  usePrompts: () => ({ data: items, isLoading: false }),
  useSaveGuidance: () => ({ mutate: save, isPending: false }),
}));

describe("AgentPromptsPage", () => {
  it("groups agents by stage and shows base prompts read-only", async () => {
    render(<AgentPromptsPage />);
    expect(screen.getByText("Resume writer")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Resume writer"));
    expect(screen.getByText("Rule one.")).toBeInTheDocument();
  });

  it("locks integrity gates", async () => {
    render(<AgentPromptsPage />);
    await userEvent.click(screen.getByText("Fact-check gate"));
    expect(screen.getByText(/integrity gate/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/your guidance/i)).not.toBeInTheDocument();
  });

  it("saves guidance for editable agents", async () => {
    render(<AgentPromptsPage />);
    await userEvent.click(screen.getByText("Resume writer"));
    await userEvent.type(screen.getByLabelText(/your guidance/i), "Punchy verbs.");
    await userEvent.click(screen.getByRole("button", { name: /save guidance/i }));
    expect(save).toHaveBeenCalledWith({ key: "tailor-writer", guidance: "Punchy verbs." });
  });
});
```

Run: `cd web && npx vitest run src/features/settings/pages/AgentPromptsPage.test.tsx` — expected FAIL (module missing).

- [ ] **Step 2: Implement hooks**

```ts
// web/src/features/settings/use-prompts.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type AgentPromptItem =
  paths["/api/agents/prompts"]["get"]["responses"][200]["content"]["application/json"][number];

export function usePrompts() {
  return useQuery({
    queryKey: ["agent-prompts"],
    queryFn: () => unwrap(api.GET("/api/agents/prompts")) as Promise<AgentPromptItem[]>,
  });
}

export function useSaveGuidance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, guidance }: { key: string; guidance: string }) =>
      unwrap(
        api.PUT("/api/agents/prompts/{key}", {
          params: { path: { key } },
          body: { guidance },
        } as never),
      ) as Promise<AgentPromptItem>,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-prompts"] });
      toast.success("Guidance saved");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
```

- [ ] **Step 3: Implement the page**

`AgentPromptsPage.tsx` structure (use existing shadcn components: `Accordion`/`Collapsible` if present in `web/src/components/ui/`, else `<details>`-style Cards — follow whatever disclosure component other pages use):

- Header: title "Agent prompts", subtitle "Read every agent's built-in prompt and add your own guidance. Guidance is appended beneath the built-in rules — it can steer tone, emphasis, and process, never facts."
- Group `usePrompts().data` by `stage` in fixed order `["tailoring", "review", "cover-letter", "discovery", "profile", "interview", "email"]` with headings (Tailoring, Review, Cover letters, Discovery, Profile, Interview, Email).
- Each agent: a disclosure row (trigger shows `title` + `description`; content shows `instructions` as an `<ol>` of read-only items in `text-sm text-muted-foreground font-mono`).
- If `editable`: a `Textarea` (`aria-label`/`FieldLabel` "Your guidance", `maxLength={4000}`) initialized from `guidance ?? ""`, local state per row, and a "Save guidance" `Button` calling `useSaveGuidance().mutate({ key, guidance })`, disabled while pending or when unchanged.
- If not `editable`: a `Badge` reading "Integrity gate — read-only" and no textarea.

- [ ] **Step 4: Register route + nav**

`router.tsx`: add a lazy import in the style of the existing ones and route `{ path: "agent-prompts", element: page(<AgentPromptsPage />) }` inside the settings children (line ~140). `SettingsLayout.tsx`: add `{ to: "/settings/agent-prompts", label: "Agent prompts", icon: Bot }` to `SETTINGS_NAV` after the "Review panel" entry (`import { Bot } from "lucide-react"`).

- [ ] **Step 5: Run web tests** — `cd web && npx vitest run src/features/settings` → PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat(web): Agent Prompts settings page — view prompts, edit guidance"
```

---

### Task 7: Render template manifest + sample content (`render/templates.py`)

**Files:**
- Create: `src/resume_agent/render/templates.py`
- Create: `src/resume_agent/render/sample_content.py`
- Test: `tests/test_render_templates.py`

**Interfaces:**
- Consumes: `resolve_tenant_path`; `RenderConfig` (current shape; Task 8 extends it).
- Produces:
  - `TemplateInfo` frozen dataclass: `id: str`, `title: str`, `description: str`, `kind: str` (`"bundled" | "custom"`), `path: Path`
  - `BUNDLED: dict[str, TemplateInfo]` (one entry, id `"classic"`, path `templates/resume.typ`)
  - `CUSTOM_TEMPLATES_DIR = "config/templates"` (workspace-relative)
  - `class TemplateNotFoundError(Exception)`
  - `resolve_template(template_id: str) -> TemplateInfo` (raises `TemplateNotFoundError`)
  - `list_templates() -> list[TemplateInfo]` (bundled first, then custom `*.typ` sorted by stem)
  - `sample_resume_content() -> ResumeContent` (in `sample_content.py`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_render_templates.py
"""Template ids resolve to bundled or workspace files; unknown ids raise."""

import pytest

from resume_agent.render.templates import (
    BUNDLED,
    TemplateNotFoundError,
    list_templates,
    resolve_template,
)


def test_classic_is_bundled():
    info = resolve_template("classic")
    assert info.kind == "bundled"
    assert info.path.name == "resume.typ"
    assert BUNDLED["classic"].title


def test_unknown_id_raises():
    with pytest.raises(TemplateNotFoundError):
        resolve_template("art-deco")


def test_custom_resolves_into_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "config" / "templates"
    custom.mkdir(parents=True)
    (custom / "mine.typ").write_text("#set page(margin: 1cm)", encoding="utf-8")
    info = resolve_template("custom:mine")
    assert info.kind == "custom" and info.id == "custom:mine"
    assert info.path == custom / "mine.typ"


def test_missing_custom_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(TemplateNotFoundError):
        resolve_template("custom:ghost")


def test_list_templates_bundled_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "config" / "templates"
    custom.mkdir(parents=True)
    (custom / "b.typ").write_text("x", encoding="utf-8")
    (custom / "a.typ").write_text("x", encoding="utf-8")
    ids = [t.id for t in list_templates()]
    assert ids == ["classic", "custom:a", "custom:b"]


def test_sample_content_is_valid_and_small():
    from resume_agent.render.sample_content import sample_resume_content

    content = sample_resume_content()
    assert content.contact.name
    assert content.experience and content.experience[0].bullets
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python.exe -m pytest tests/test_render_templates.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/resume_agent/render/templates.py
"""Template identity: bundled manifest + workspace custom templates.

Users select templates by id ("classic", "custom:<stem>"), never by path;
resolution is the only place ids become filesystem locations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from resume_agent.tenancy.paths import resolve_tenant_path

CUSTOM_TEMPLATES_DIR = "config/templates"


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    title: str
    description: str
    kind: str  # "bundled" | "custom"
    path: Path


BUNDLED: dict[str, TemplateInfo] = {
    "classic": TemplateInfo(
        id="classic",
        title="Classic",
        description="Single-column layout with compact section headers; fits one page.",
        kind="bundled",
        path=Path("templates/resume.typ"),
    ),
}


class TemplateNotFoundError(Exception):
    pass


def _custom_dir() -> Path:
    return resolve_tenant_path(CUSTOM_TEMPLATES_DIR)


def _custom_info(stem: str, path: Path) -> TemplateInfo:
    return TemplateInfo(
        id=f"custom:{stem}", title=stem, description="Uploaded template",
        kind="custom", path=path,
    )


def resolve_template(template_id: str) -> TemplateInfo:
    if template_id in BUNDLED:
        return BUNDLED[template_id]
    if template_id.startswith("custom:"):
        stem = template_id.removeprefix("custom:")
        path = _custom_dir() / f"{stem}.typ"
        if path.exists():
            return _custom_info(stem, path)
    raise TemplateNotFoundError(
        f"Template {template_id!r} does not exist. Pick a bundled template or "
        "re-upload the custom file."
    )


def list_templates() -> list[TemplateInfo]:
    custom_dir = _custom_dir()
    customs = (
        sorted(custom_dir.glob("*.typ"), key=lambda p: p.stem)
        if custom_dir.exists()
        else []
    )
    return [*BUNDLED.values(), *(_custom_info(p.stem, p) for p in customs)]
```

```python
# src/resume_agent/render/sample_content.py
"""Deterministic sample resume used for template validation and previews."""

from resume_agent.models.profile import Contact, Education
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)


def sample_resume_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(
            name="Alex Sample",
            headline="Software Engineer",
            email="alex@example.com",
            location="Remote",
        ),
        summary="Engineer with 6 years building data-heavy web services.",
        experience=[
            TailoredExperience(
                company="Acme Corp",
                title="Senior Engineer",
                start="2021",
                end="Present",
                provenance="sample-exp-1",
                bullets=[
                    TailoredBullet(
                        text="Cut p95 latency 40% by rewriting the query planner.",
                        provenance="sample-bullet-1",
                    ),
                    TailoredBullet(
                        text="Led a 4-person team shipping the billing service.",
                        provenance="sample-bullet-2",
                    ),
                ],
            )
        ],
        skills={
            "Hard skills": [
                TailoredSkill(name="Python", provenance="sample-skill-1"),
                TailoredSkill(name="PostgreSQL", provenance="sample-skill-2"),
            ]
        },
        education=[Education(school="State University", degree="BSc Computer Science")],
    )
```

If `Education` field names differ (check `models/profile.py`), use its actual required fields.

- [ ] **Step 4: Run tests** — `.venv/Scripts/python.exe -m pytest tests/test_render_templates.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/render/templates.py src/resume_agent/render/sample_content.py tests/test_render_templates.py
git commit -m "feat(render): template manifest, id resolution, sample content"
```

---

### Task 8: `RenderConfig` new keys + root-pinned `render_pdf` + service wiring

**Files:**
- Modify: `src/resume_agent/render/render_config.py`
- Modify: `src/resume_agent/render/renderer.py` (`render_pdf` gains `root`)
- Modify: `src/resume_agent/render/service.py` (`render_version` resolves template + fit)
- Modify: `src/resume_agent/render/templates.py` (add `template_path_for`)
- Test: `tests/test_render_config.py` (create; move/extend any existing render-config assertions), existing render service tests (update fakes)

**Interfaces:**
- Consumes: `resolve_template`, `TemplateNotFoundError` (Task 7).
- Produces:
  - `RenderConfig`: `template: str | None = None`, `fit_one_page: bool = True`, `template_path: str | None = None` (legacy), `output_dir: str = "output"` (legacy/CLI, unchanged semantics)
  - `template_path_for(config: RenderConfig) -> Path` in `render/templates.py`: `template` set → `resolve_template(...)`; else `template_path` set → `Path(template_path)` (legacy escape hatch); else classic.
  - `render_pdf(..., root: str | Path | None = None)` — when `None`, root defaults to the template file's parent directory (root-pinning always on).
  - `render/service.py` calls `render_fn(content, out_path, template, fit_pages=1 if config.fit_one_page else None)`; `RenderFn = Callable[..., Path]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_render_config.py
"""New template id keys; legacy render.yaml keys keep loading."""

from pathlib import Path

import yaml

from resume_agent.render.render_config import RenderConfig, load_render_config
from resume_agent.render.templates import template_path_for


def test_defaults_use_classic_template():
    config = RenderConfig()
    assert config.template is None and config.template_path is None
    assert template_path_for(config) == Path("templates/resume.typ")
    assert config.fit_one_page is True


def test_new_keys_load(tmp_path):
    path = tmp_path / "render.yaml"
    path.write_text(yaml.safe_dump({"template": "classic", "fit_one_page": False}))
    config = load_render_config(path)
    assert config.template == "classic" and config.fit_one_page is False


def test_legacy_template_path_wins_when_template_absent(tmp_path):
    path = tmp_path / "render.yaml"
    path.write_text(
        yaml.safe_dump({"template_path": "my/local.typ", "output_dir": "out"})
    )
    config = load_render_config(path)
    assert template_path_for(config) == Path("my/local.typ")
    assert config.output_dir == "out"


def test_template_key_beats_legacy_path(tmp_path):
    path = tmp_path / "render.yaml"
    path.write_text(
        yaml.safe_dump({"template": "classic", "template_path": "my/local.typ"})
    )
    assert template_path_for(load_render_config(path)) == Path("templates/resume.typ")
```

Also update the render service test file (find it: `grep -rl "render_version" tests/`) — its fake `render_fn` must accept the new call shape; change fakes to `def fake_render(content, out_path, template_path, *, fit_pages=None): ...` and add one assertion that `fit_pages == 1` by default and `None` when the config says `fit_one_page=False`.

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python.exe -m pytest tests/test_render_config.py -q` → FAIL (`template` attribute missing).

- [ ] **Step 3: Implement**

`render/render_config.py`:

```python
class RenderConfig(ExtensibleModel):
    template: str | None = None       # "classic" | "custom:<stem>"; None → legacy/default
    fit_one_page: bool = True
    template_path: str | None = None  # legacy escape hatch (CLI, pre-migration yaml)
    output_dir: str = "output"        # legacy/CLI; web output is workspace-resolved
```

Add to `render/templates.py`:

```python
def template_path_for(config) -> Path:
    """Template id wins; legacy template_path is the CLI escape hatch."""
    if config.template:
        return resolve_template(config.template).path
    if config.template_path:
        return Path(config.template_path)
    return resolve_template("classic").path
```

`render/renderer.py` — `render_pdf` gains `root: str | Path | None = None` after `zoom_step`; before the compile loop:

```python
    resolved_root = Path(root) if root is not None else Path(template_path).resolve().parent
```

and the compile call becomes:

```python
        typst.compile(
            str(template_path),
            output=str(out),
            root=str(resolved_root),
            sys_inputs={"data": data, "zoom": f"{zoom:.4f}"},
        )
```

Note: with `root` set, Typst resolves the input path against the root when relative — pass `str(Path(template_path).resolve())` as the input to keep absolute/relative templates working; verify with the bundled template test below.

`render/service.py`:

```python
from resume_agent.render.templates import template_path_for

RenderFn = Callable[..., Path]

    # inside render_version, replacing the render_fn(...) call:
    template = template_path_for(config)
    render_fn(
        content, out_path, template,
        fit_pages=1 if config.fit_one_page else None,
    )
```

- [ ] **Step 4: Prove a real compile still works** — add to `tests/test_render_config.py`:

```python
def test_classic_template_compiles_with_pinned_root(tmp_path):
    from resume_agent.render.renderer import render_pdf
    from resume_agent.render.sample_content import sample_resume_content

    out = render_pdf(
        sample_resume_content(), tmp_path / "sample.pdf",
        "templates/resume.typ", fit_pages=None,
    )
    assert out.exists() and out.stat().st_size > 0
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_config.py -q` and the full suite `.venv/Scripts/python.exe -m pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/render tests
git commit -m "feat(render): template-id config keys, root-pinned compile, fit toggle"
```

---

### Task 9: `RenderConfigDoc` contract swap + PUT validation + example file

**Files:**
- Modify: `src/resume_agent/api/schemas/config.py` (`RenderConfigDoc`)
- Modify: `src/resume_agent/api/routers/config.py` (`put_render` validates the template id)
- Modify: `config/render.yaml.example` (create if absent — check first)
- Modify: `contracts/*`, `web/src/lib/api/schema.ts` (regenerated)
- Test: `tests/api/test_config_router.py` (extend)

**Interfaces:**
- Consumes: `resolve_template`, `TemplateNotFoundError` (Task 7).
- Produces: `RenderConfigDoc(template: str = "classic", fit_one_page: bool = True)` — wire `{template, fitOnePage}`; `template_path`/`output_dir` leave the wire contract. PUT with a nonexistent template → 422 `template_not_found`.

- [ ] **Step 1: Write the failing tests** — append to `tests/api/test_config_router.py`:

```python
def test_render_contract_is_template_id_only(client):
    body = client.get("/api/config/render").json()
    assert body == {"template": "classic", "fitOnePage": True}


def test_put_render_rejects_unknown_template(client):
    resp = client.put(
        "/api/config/render", json={"template": "custom:ghost", "fitOnePage": True}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "template_not_found"


def test_put_render_round_trip(client):
    put = client.put(
        "/api/config/render", json={"template": "classic", "fitOnePage": False}
    )
    assert put.status_code == 200
    assert client.get("/api/config/render").json()["fitOnePage"] is False
```

Run → FAIL (old keys in GET body).

- [ ] **Step 2: Implement**

`api/schemas/config.py`:

```python
class RenderConfigDoc(CamelModel):
    template: str = "classic"
    fit_one_page: bool = True
```

`api/routers/config.py` — replace `put_render`:

```python
from resume_agent.api.errors import ApiException
from resume_agent.render.templates import TemplateNotFoundError, resolve_template

@router.put("/config/render", response_model=RenderConfigDoc)
def put_render(body: RenderConfigDoc, request: Request):
    try:
        resolve_template(body.template)
    except TemplateNotFoundError as exc:
        raise ApiException(422, "template_not_found", str(exc))
    return _store(request).put("render", body)
```

Because `RenderConfig` (Task 8) still accepts `template`/`fit_one_page` alongside legacy keys, the yaml written by `ConfigStore.put` loads cleanly in `services/rendering._load_config`. A legacy `render.yaml` served through GET now validates through the new Doc — legacy keys are simply not projected (ExtensibleModel/`model_validate` ignores or carries extras; assert GET on a legacy file returns defaults in a quick test if `CamelModel` forbids extras, adjust with `model_config = ConfigDict(extra="ignore")` on `RenderConfigDoc` only if validation errors).

Update `config/render.yaml.example` (or create):

```yaml
# Rendering: pick a template by id and whether to shrink-to-fit one page.
# Bundled: classic. Uploaded templates are custom:<name>.
# Legacy keys template_path / output_dir still load for CLI setups.
template: classic
fit_one_page: true
```

- [ ] **Step 3: Run tests + regenerate** — `.venv/Scripts/python.exe -m pytest tests/api/test_config_router.py -q` → PASS. `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` → PASS. Note: `RenderingSettingsPage.tsx` now fails typecheck (old field names) — that is expected until Task 11; if `npx tsc`/vitest runs in CI for this commit, update the page minimally in this task by replacing the two fields with a placeholder reading `draft.template` (Task 11 rewrites it fully).

- [ ] **Step 4: Commit**

```bash
git add src/resume_agent/api config/render.yaml.example tests contracts web/src
git commit -m "feat(api)!: render config contract is template id + fitOnePage"
```

---

### Task 10: Template management endpoints (list / upload / delete / preview)

**Files:**
- Create: `src/resume_agent/services/render_templates.py`
- Create: `src/resume_agent/api/routers/render_templates.py`
- Create: `src/resume_agent/api/schemas/render_templates.py`
- Modify: `src/resume_agent/api/app.py` (include router, guarded)
- Modify: `contracts/*`, `web/src/lib/api/schema.ts` (regenerated)
- Test: `tests/api/test_render_templates_api.py`

**Interfaces:**
- Consumes: `list_templates`, `resolve_template`, `TemplateNotFoundError`, `CUSTOM_TEMPLATES_DIR` (Task 7); `render_pdf` (Task 8); `sample_resume_content`; `read_upload`/`UploadTooLargeError` (`api/uploads.py`); `ConfigStore` via `get_config_store` (`api/deps.py`).
- Produces:
  - `services/render_templates.py`: `class TemplateValidationError(Exception)` (message = Typst error text), `validate_template(path: Path) -> None`, `save_custom_template(filename: str, data: bytes) -> TemplateInfo`, `delete_custom_template(stem: str, store) -> bool`, `render_preview(template_id: str) -> bytes`
  - Routes: `GET /api/config/render/templates` → `list[TemplateListItem]` (`{id, title, description, kind}`); `POST /api/config/render/templates` (multipart `file`) → `TemplateListItem`; `DELETE /api/config/render/templates/{stem}` → 204; `GET /api/config/render/templates/{template_id}/preview` → `application/pdf` bytes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_render_templates_api.py
"""Custom templates: validated on upload, sandboxed, previewable, deletable."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app

VALID_TYP = """
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let zoom = float(sys.inputs.at("zoom", default: "1.0"))
= #payload.at("contact").at("name")
#payload.at("summary", default: "")
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as c:
        yield c


def _upload(client, name="mine.typ", body: bytes = VALID_TYP.encode()):
    return client.post(
        "/api/config/render/templates",
        files={"file": (name, body, "text/plain")},
    )


def test_list_starts_with_bundled(client):
    body = client.get("/api/config/render/templates").json()
    assert body[0] == {
        "id": "classic",
        "title": "Classic",
        "description": body[0]["description"],
        "kind": "bundled",
    }


def test_upload_validates_and_lists(client):
    resp = _upload(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "custom:mine"
    ids = [t["id"] for t in client.get("/api/config/render/templates").json()]
    assert "custom:mine" in ids


def test_invalid_typst_is_422_with_compiler_error(client):
    resp = _upload(client, body=b"#broken(")
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "template_invalid"
    assert err["details"]  # compiler output surfaced


def test_bad_extension_is_422(client):
    resp = _upload(client, name="mine.txt")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "template_invalid"


def test_preview_returns_pdf(client):
    assert _upload(client).status_code == 200
    resp = client.get("/api/config/render/templates/custom:mine/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_preview_unknown_is_422(client):
    resp = client.get("/api/config/render/templates/custom:ghost/preview")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "template_not_found"


def test_delete_falls_back_active_template_to_classic(client):
    _upload(client)
    put = client.put(
        "/api/config/render", json={"template": "custom:mine", "fitOnePage": True}
    )
    assert put.status_code == 200
    resp = client.delete("/api/config/render/templates/mine")
    assert resp.status_code == 204
    assert client.get("/api/config/render").json()["template"] == "classic"
    ids = [t["id"] for t in client.get("/api/config/render/templates").json()]
    assert "custom:mine" not in ids
```

Run → FAIL (routes missing).

- [ ] **Step 2: Implement the service**

```python
# src/resume_agent/services/render_templates.py
"""Custom template lifecycle: validate-on-upload, preview, delete-with-fallback.

The validation compile is both the UX (typst errors surface at upload time)
and the sandbox check (root pinned to the template's own directory)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from resume_agent.render.renderer import render_pdf
from resume_agent.render.sample_content import sample_resume_content
from resume_agent.render.templates import (
    CUSTOM_TEMPLATES_DIR,
    TemplateInfo,
    resolve_template,
)
from resume_agent.tenancy.paths import resolve_tenant_path

MAX_TEMPLATE_BYTES = 200 * 1024
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.typ")


class TemplateValidationError(Exception):
    """Message is user-facing; carries the Typst compiler output when present."""


def validate_template(path: Path) -> None:
    """Compile the sample resume with root pinned to the template's directory."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            render_pdf(
                sample_resume_content(),
                Path(tmp) / "probe.pdf",
                path,
                fit_pages=None,
                root=path.parent,
            )
    except Exception as exc:  # typst raises RuntimeError with compiler output
        raise TemplateValidationError(str(exc)) from exc


def save_custom_template(filename: str, data: bytes) -> TemplateInfo:
    if not _FILENAME.fullmatch(filename or ""):
        raise TemplateValidationError(
            "Upload a .typ file (letters, digits, dot, dash, underscore). The "
            "template must read sys.inputs 'data' (resume JSON) and 'zoom'."
        )
    if len(data) > MAX_TEMPLATE_BYTES:
        raise TemplateValidationError("Template exceeds the 200 KB limit.")
    target_dir = resolve_tenant_path(CUSTOM_TEMPLATES_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    target.write_bytes(data)
    try:
        validate_template(target)
    except TemplateValidationError:
        target.unlink(missing_ok=True)
        raise
    return resolve_template(f"custom:{target.stem}")


def delete_custom_template(stem: str, store) -> bool:
    """Remove the file; if it was the active template, fall back to classic."""
    path = resolve_tenant_path(CUSTOM_TEMPLATES_DIR) / f"{stem}.typ"
    if not path.exists():
        return False
    path.unlink()
    render_doc = store.get("render")
    if getattr(render_doc, "template", None) == f"custom:{stem}":
        store.put("render", render_doc.model_copy(update={"template": "classic"}))
    return True


def render_preview(template_id: str) -> bytes:
    info = resolve_template(template_id)  # raises TemplateNotFoundError
    with tempfile.TemporaryDirectory() as tmp:
        out = render_pdf(
            sample_resume_content(), Path(tmp) / "preview.pdf", info.path,
            fit_pages=None,
        )
        return out.read_bytes()
```

- [ ] **Step 3: Implement schemas + router**

```python
# src/resume_agent/api/schemas/render_templates.py
from resume_agent.api.schemas.base import CamelModel


class TemplateListItem(CamelModel):
    id: str
    title: str
    description: str
    kind: str
```

```python
# src/resume_agent/api/routers/render_templates.py
"""Template management for rendering: list, upload (validated), delete, preview."""

from fastapi import APIRouter, Request, Response, UploadFile

from resume_agent.api.deps import get_config_store
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.render_templates import TemplateListItem
from resume_agent.api.uploads import UploadTooLargeError, read_upload
from resume_agent.render.templates import TemplateNotFoundError, list_templates
from resume_agent.services.render_templates import (
    MAX_TEMPLATE_BYTES,
    TemplateValidationError,
    delete_custom_template,
    render_preview,
    save_custom_template,
)

router = APIRouter()


def _item(info) -> TemplateListItem:
    return TemplateListItem(
        id=info.id, title=info.title, description=info.description, kind=info.kind
    )


@router.get("/config/render/templates", response_model=list[TemplateListItem])
def get_templates() -> list[TemplateListItem]:
    return [_item(info) for info in list_templates()]


@router.post("/config/render/templates", response_model=TemplateListItem)
def upload_template(file: UploadFile) -> TemplateListItem:
    try:
        data = read_upload(file, max_bytes=MAX_TEMPLATE_BYTES)
        info = save_custom_template(file.filename or "", data)
    except (TemplateValidationError, UploadTooLargeError) as exc:
        raise ApiException(
            422, "template_invalid",
            "Template failed validation. It must be a .typ file that compiles "
            "against the sample resume (sys.inputs: 'data' JSON, 'zoom').",
            details=str(exc),
        )
    return _item(info)


@router.delete("/config/render/templates/{stem}", status_code=204)
def delete_template(stem: str, request: Request) -> Response:
    if not delete_custom_template(stem, get_config_store(request)):
        raise ApiException(422, "template_not_found", f"No custom template {stem!r}.")
    return Response(status_code=204)


@router.get("/config/render/templates/{template_id}/preview")
def preview_template(template_id: str) -> Response:
    try:
        pdf = render_preview(template_id)
    except TemplateNotFoundError as exc:
        raise ApiException(422, "template_not_found", str(exc))
    except TemplateValidationError as exc:
        raise ApiException(422, "template_invalid", "Preview failed.", details=str(exc))
    return Response(content=pdf, media_type="application/pdf")
```

In `api/app.py`, include next to the config router: `app.include_router(render_templates_router.router, prefix="/api", dependencies=guarded)` — **before** `config_router` inclusion is not required (paths don't collide: `/config/render` vs `/config/render/templates` are distinct exact routes).

- [ ] **Step 4: Run tests + regenerate** — `.venv/Scripts/python.exe -m pytest tests/api/test_render_templates_api.py -q` → PASS. `bash scripts/gen_ts_client.sh`; drift gate → PASS. Full suite + `ruff check` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent tests/api/test_render_templates_api.py contracts web/src/lib/api/schema.ts
git commit -m "feat(api): render template list/upload/delete/preview with validation compile"
```

---

### Task 11: Web — Rendering settings rewrite (picker + upload + fit switch)

**Files:**
- Rewrite: `web/src/features/settings/pages/RenderingSettingsPage.tsx`
- Create: `web/src/features/settings/use-render-templates.ts`
- Create: `web/src/features/settings/pages/RenderingSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `/api/config/render` (new shape) via `useConfig`/`useSaveConfig`; `/api/config/render/templates` GET/POST/DELETE from `schema.ts`.
- Produces: `useRenderTemplates()`, `useUploadTemplate()` (mutate `File`), `useDeleteTemplate()` (mutate `stem: string`).

- [ ] **Step 1: Write the failing component test**

```tsx
// web/src/features/settings/pages/RenderingSettingsPage.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RenderingSettingsPage } from "./RenderingSettingsPage";

const saveMutate = vi.fn();
const uploadMutate = vi.fn();

vi.mock("../use-config", () => ({
  useConfig: () => ({ data: { template: "classic", fitOnePage: true } }),
  useSaveConfig: () => ({ mutate: saveMutate, isPending: false }),
}));
vi.mock("../use-render-templates", () => ({
  useRenderTemplates: () => ({
    data: [
      { id: "classic", title: "Classic", description: "Single column.", kind: "bundled" },
      { id: "custom:mine", title: "mine", description: "Uploaded template", kind: "custom" },
    ],
  }),
  useUploadTemplate: () => ({ mutate: uploadMutate, isPending: false, error: null }),
  useDeleteTemplate: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("RenderingSettingsPage", () => {
  it("shows template cards with no path inputs", () => {
    render(<RenderingSettingsPage />);
    expect(screen.getByText("Classic")).toBeInTheDocument();
    expect(screen.getByText("mine")).toBeInTheDocument();
    expect(screen.queryByLabelText(/path|directory/i)).not.toBeInTheDocument();
  });

  it("selecting a template marks the draft dirty and saves", async () => {
    render(<RenderingSettingsPage />);
    await userEvent.click(screen.getByRole("radio", { name: /mine/i }));
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));
    expect(saveMutate).toHaveBeenCalledWith({ template: "custom:mine", fitOnePage: true });
  });

  it("toggling one-page fit updates the draft", async () => {
    render(<RenderingSettingsPage />);
    await userEvent.click(screen.getByRole("switch", { name: /one page/i }));
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));
    expect(saveMutate).toHaveBeenCalledWith({ template: "classic", fitOnePage: false });
  });
});
```

Run: `cd web && npx vitest run src/features/settings/pages/RenderingSettingsPage.test.tsx` → FAIL.

- [ ] **Step 2: Implement hooks**

```ts
// web/src/features/settings/use-render-templates.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type TemplateListItem =
  paths["/api/config/render/templates"]["get"]["responses"][200]["content"]["application/json"][number];

const KEY = ["render-templates"];

export function useRenderTemplates() {
  return useQuery({
    queryKey: KEY,
    queryFn: () =>
      unwrap(api.GET("/api/config/render/templates")) as Promise<TemplateListItem[]>,
  });
}

export function useUploadTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const resp = await fetch("/api/config/render/templates", {
        method: "POST",
        body,
        credentials: "include",
      });
      const json = await resp.json();
      if (!resp.ok) {
        const detail = json?.error?.details || json?.error?.message || "Upload failed";
        throw new Error(String(detail));
      }
      return json as TemplateListItem;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      toast.success("Template uploaded");
    },
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stem: string) =>
      unwrap(
        api.DELETE("/api/config/render/templates/{stem}", {
          params: { path: { stem } },
        } as never),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: ["config", "/api/config/render"] });
      toast.success("Template deleted");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
```

(Raw `fetch` for the multipart POST — openapi-fetch multipart typing is awkward; the app's auth is a same-origin session cookie, so `credentials: "include"` suffices. If the api client exposes a bearer header helper, reuse it here the way `web/src/lib/api/client.ts` builds headers.)

- [ ] **Step 3: Rewrite the page**

Structure of the new `RenderingSettingsPage.tsx`:

- Keep `useConfig("/api/config/render")` + `useDraft` + `SaveBar` exactly as the old page did (draft type is now `{template, fitOnePage}`).
- **Templates**: a radiogroup of Cards (one per `useRenderTemplates().data` entry): title, description, `kind === "custom"` badge; clicking sets `setDraft({...draft, template: item.id})`; the selected card gets a ring. Each card has a "Preview" link-button: `onClick` fetches `/api/config/render/templates/${encodeURIComponent(item.id)}/preview` with `credentials: "include"`, turns the blob into `URL.createObjectURL`, and `window.open`s it. Custom cards also render a small delete icon-button wired to `useDeleteTemplate().mutate(item.id.replace(/^custom:/, ""))`.
- **Upload**: `<Input type="file" accept=".typ" />`; on change call `useUploadTemplate().mutate(file)`; render `upload.error.message` beneath in `text-destructive text-sm whitespace-pre-wrap` (this is the verbatim Typst compile error). A `FieldDescription` documents the contract: "Your template must be a Typst file that reads `sys.inputs.data` (resume JSON) and `sys.inputs.zoom`."
- **Options**: a `Switch` (`aria-label` "Fit resume to one page") bound to `draft.fitOnePage`.
- Caption at the bottom: "Rendered PDFs are stored in your workspace and downloaded from each job's page."

- [ ] **Step 4: Run web tests** — `cd web && npx vitest run src/features/settings` → PASS. Also run the full web suite `cd web && npx vitest run` → PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): rendering settings — template picker, validated upload, one-page fit"
```

---

### Task 12: Docs + full verification sweep

**Files:**
- Modify: `CLAUDE.md`
- Test: full suites

**Interfaces:** none new.

- [ ] **Step 1: CLAUDE.md updates**

Add to "Known design notes":

```markdown
- **Agent prompts are registry-projected; guidance is layered.** `prompts/registry.py`
  declares every agent's `PromptSpec` by importing the instruction lists from their
  home modules (never copying text). Per-agent user guidance lives in
  `config/agent_guidance.yaml` (constant `AGENT_GUIDANCE_PATH`), capped at 4000 chars,
  and is appended beneath base rules by `prompts/guidance.py:with_guidance` in every
  builder — it can steer tone/emphasis/process, never facts. `reviewer-fact-check` is
  the only non-editable key (`NON_EDITABLE_KEYS`); guidance.py must not import
  registry.py (registry imports the agent modules, which import guidance).
  API: `GET /api/agents/prompts`, `PUT /api/agents/prompts/{key}`.
- **Rendering is template-id based.** `RenderConfigDoc` is `{template, fitOnePage}`;
  `output_dir`/`template_path` are legacy yaml keys honored only for CLI setups
  (`render/templates.py:template_path_for`). Bundled templates live in the `BUNDLED`
  manifest; uploads land in `{workspace}/config/templates/` after a validation
  compile with Typst `root` pinned to the template's directory (`render_pdf` always
  pins root to the template's parent). Deleting the active custom template falls the
  config back to `classic` — the only fallback path; renders with a missing template
  fail with `template_not_found`.
```

Also update the hot-paths table only if a row references `render_config.py` semantics that changed (no row does today — skip otherwise).

- [ ] **Step 2: Full verification**

```
.venv/Scripts/python.exe -m pytest -q
ruff check
bash scripts/gen_ts_client.sh && git diff --exit-code contracts web/src/lib/api/schema.ts
cd web && npx vitest run
```

All green; the `git diff --exit-code` proves committed contracts match the code.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: agent prompt registry + template-id rendering in CLAUDE.md"
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** registry/guidance/injection (Tasks 1–3), prompts API + page (4, 6), review knobs (5), template manifest/resolution (7), config + root-pinning + fit (8), contract swap + example (9), upload/delete/preview endpoints (10), rendering page (11), docs + error codes + drift gates (throughout, 12). Merged-advisory guidance embedding — spec's "each configured named rows" advisory model — handled explicitly in Task 3.
- **Type consistency:** `with_guidance(key, base) -> list[str]`; `TemplateInfo.id` carries the full `custom:<stem>` id; delete takes the bare stem; `RenderFn` relaxed to `Callable[..., Path]` in the same task that changes its call shape.
- **Known judgment calls:** `template: str | None` internally vs `template: str = "classic"` on the wire (absence detection for legacy yaml); registry imports service/agent modules at import time (already true of the test suite); preview/upload web calls use raw `fetch` with same-origin credentials.
