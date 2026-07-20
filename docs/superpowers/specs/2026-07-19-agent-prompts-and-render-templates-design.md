# Agent Prompt Transparency + Web-Friendly Rendering Settings — Design

**Date:** 2026-07-19
**Status:** Approved

Two features, one spec:

1. **Agent prompts:** every LLM agent's prompt is viewable in the web app, and users
   can attach per-agent guidance to steer how agents work — without being able to
   break the fact-lock invariant.
2. **Rendering settings:** the raw `template_path` / `output_dir` filesystem fields
   are replaced with a template picker + validated custom-template upload that works
   for online (Railway, multi-user) users. The output directory disappears as a
   user-facing concept.

---

## Feature 1: Agent prompt registry + guidance layer

### Decision summary

- **Layered model, not replacement.** Users view full base prompts (transparency)
  and edit a per-agent *guidance* layer appended beneath immutable rules —
  generalizing the existing `style_guide.md` seam (`compose_instructions`).
- **Scope:** prompts + the structural knobs that already exist (review roster,
  weights, tiers, rounds — mostly already in the Review settings page). No new
  workflow engine.
- **The fact-check reviewer is view-only.** It is the hard gate enforcing
  fact-lock; guidance could hollow it out.

### Registry (`src/resume_agent/prompts/registry.py`)

```python
@dataclass(frozen=True)
class PromptSpec:
    key: str            # "tailor-writer", "reviewer-fact-check", "fit-score", ...
    title: str          # "Resume Writer"
    stage: str          # "tailoring" | "review" | "cover-letter" | "discovery"
                        # | "profile" | "interview" | "email"
    description: str    # one line: what this agent does in the pipeline
    instructions: list[str]  # imported FROM the module where it lives today
    editable: bool = True    # False for integrity gates (fact-check)
```

- Instruction lists **stay in their home modules** (`tailor/agents.py`,
  `discovery/fit.py`, `profile/coach.py`, …); the registry imports them. The
  viewer is a projection and can never drift from the code — same pattern as
  `CONNECTOR_SPECS`.
- Registered agents cover every user-meaningful LLM agent: tailor writer /
  reviser / revision, the review roster (fact-check, ats-keyword, recruiter,
  hiring-manager, concision, merged panel), cover-letter agents, fit scoring,
  criteria extraction, relevance judge, industry, URL-ingest parsers, source
  scout, profile extractor / synthesis / inference / merge / project extractor /
  coach, interviewer + debrief, taxonomy group classifier, canonicalizer, email
  writer.

### Guidance storage and injection

- One per-workspace file: `config/agent_guidance.yaml` — a flat
  `key: "guidance text"` map. New `AGENT_GUIDANCE_PATH` constant in
  `tenancy/paths.py`; loaded through `resolve_tenant_path` like every other
  workspace artifact. Cap: **4,000 characters per agent** (schema-validated).
- `with_guidance(key, base) -> list[str]` generalizes `compose_instructions`:
  returns `base + [GUIDANCE_HEADER, user_text]` when guidance exists, else
  `base` unchanged. Header text (subordination contract):

  > USER GUIDANCE (governs HOW you work, never WHAT is true; the rules above
  > always take precedence and may not be overridden):

- Each agent builder wraps its instructions in `with_guidance(...)` — one
  mechanical line per builder. The tailor writer keeps its existing layers;
  order: base → craft → style guide → agent guidance.
- Guidance never replaces base instructions. `editable=False` specs
  (fact-check) reject guidance at the API layer and are skipped by
  `with_guidance`.
- CLI and API both pick guidance up automatically because both build agents
  through the same builders.

### API (`api/routers/prompts.py`, schemas in `api/schemas/prompts.py`)

- `GET /api/agents/prompts` →
  `[{key, title, stage, description, instructions: string[], guidance: string | null, editable: boolean}]`
- `PUT /api/agents/prompts/{key}` body `{guidance: string}` — saves to
  `agent_guidance.yaml`; empty string clears the entry.
- Errors (standard envelope): unknown key → **404 `unknown_agent`**;
  non-editable key → **409 `agent_not_editable`**; > 4,000 chars → 422
  (schema validation).
- `CamelModel` schemas; TS contract regenerated via `scripts/gen_ts_client.sh`;
  covered by the OpenAPI drift gate.

### Web UI — Settings › Agent Prompts

New page `web/src/features/settings/pages/AgentPromptsPage.tsx`, added to the
settings nav.

- Agents grouped by stage into collapsible sections (Tailoring, Review, Cover
  letters, Discovery, Profile, Interview, Email).
- Each agent row: title + description; expanded view shows the **base prompt**
  as a numbered read-only list, then a **"Your guidance"** textarea with
  per-agent save state (PUT one key at a time).
- Non-editable agents show a badge — *"Integrity gate — read-only"* — and no
  textarea.
- Page-level note: guidance is appended beneath built-in rules; it can steer
  tone/emphasis/process, never facts.

### Review structural knobs

Add the missing `review.yaml` fields to `ReviewConfigDoc` and the existing
Review settings page: `merged_advisory` toggle, `tailor_tier` and
`reviser_tier` selectors. Nothing else changes.

---

## Feature 2: Template picker + validated upload for rendering

### Decision summary

- **Template identity replaces file paths.** The wire contract loses
  `template_path` and `output_dir`; output always resolves to the workspace's
  `output/` via `resolve_tenant_path` — no user knob. PDFs keep flowing through
  the existing download endpoints.
- **Custom templates are uploaded, validated, and sandboxed** — never referenced
  by arbitrary path.

### Contract (`RenderConfigDoc`)

```
template: str = "classic"        # bundled id, or "custom:<stem>" for uploads
fit_one_page: bool = True        # maps to render_pdf fit_pages=1 vs None
```

### Bundled manifest + resolution (`render/templates.py`)

- `BUNDLED = {"classic": TemplateInfo(path="templates/resume.typ", title, description)}`
  — one entry today; a future layout is one row + one `.typ` file.
- `resolve_template(template_id) -> Path`: bundled id → repo path;
  `custom:<stem>` → `{workspace}/config/templates/<stem>.typ`.
- Unknown id or missing custom file raises a typed error → **422
  `template_not_found`**. Render runs fail cleanly with that message in the
  run's error record; there is **no silent fallback** at render time.

### Custom template endpoints (service logic in `services/rendering.py`)

- `GET /api/config/render/templates` → bundled + custom entries
  `{id, title, kind, valid}` for the picker.
- `POST /api/config/render/templates` — multipart `.typ`, ≤ 200 KB. Stored
  under `{workspace}/config/templates/` **only after a validation compile**:
  the server compiles the candidate against a bundled sample `ResumeContent`
  with Typst's compilation `root` pinned to the template's own directory, so
  `read()` / `include` cannot escape it. Compile failure → **422
  `template_invalid`** with the Typst error text in `details`. The sys-inputs
  contract (`data` JSON + `zoom` string) is documented on the page and in the
  error message.
- `DELETE /api/config/render/templates/{stem}` — removes a custom template; if
  it is the active one, the config is updated to fall back to `classic` (the
  only place fallback happens).
- `GET /api/config/render/templates/{id}/preview` — PDF of the sample resume
  compiled with that template, on demand, for the picker's preview pane.

### Security

- User-supplied Typst executes server-side: mitigated by root-pinning (custom
  templates compile with `root` = their own directory; bundled templates with
  `root` = the repo `templates/` dir), the validation compile at upload time,
  the size cap, and Typst having no network access.

### Back-compat

- Internal `RenderConfig` keeps `template_path` / `output_dir` as optional
  legacy fields. A legacy `render.yaml` (or a CLI user pointing at an arbitrary
  local `.typ`) still loads: legacy `template_path` wins when the new
  `template` key is absent; legacy `output_dir` is still honored for
  single-user / CLI runs. The web PUT writes only the new keys.

### Web UI — Settings › Rendering (rewrite)

- **Template picker:** cards for each template (bundled + custom) — title,
  description, "Preview" action (opens the sample PDF), selected state bound to
  `template`. Custom cards get a delete action.
- **Upload zone:** accepts `.typ`; a 422 `template_invalid` shows the compiler
  error verbatim under the zone; success adds a selectable card.
- **Options:** a single "Fit resume to one page" switch.
- No path fields; a caption notes PDFs are stored in your workspace and
  downloaded from each job's page (unchanged behavior).

---

## Error handling summary

All on the existing `ApiException` envelope:

| Code | Status | When |
| --- | --- | --- |
| `unknown_agent` | 404 | PUT guidance for an unregistered key |
| `agent_not_editable` | 409 | PUT guidance for an integrity gate |
| `template_not_found` | 422 | Config or render references a missing/unknown template |
| `template_invalid` | 422 | Upload fails the validation compile (compiler output in `details`) |
| (schema validation) | 422 | Guidance over 4,000 chars; upload size/extension violations |

## Testing (offline, suite conventions)

- **Registry:** keys unique; instructions non-empty; every `editable=False`
  spec is an integrity gate; completeness test asserting each known
  agent-builder module's instruction list object is registered by identity — a
  new agent forces a registry entry or an explicit exemption.
- **Guidance:** `with_guidance` layering order, cap enforcement, empty/missing
  file no-ops; one builder-level test per stage confirming guidance reaches the
  built agent's instructions (agents faked as usual).
- **API:** prompts GET/PUT contract tests + error cases; render config
  round-trip incl. legacy-key loading; upload validation exercising a real
  `typst.compile` against tiny valid/invalid templates (typst is a local
  dependency, no network — fits the offline suite); OpenAPI drift gate
  regenerated.
- **Web:** vitest coverage for both pages — render picker selection + upload
  error display; prompts page expand/edit/save + read-only gate badge.

## Docs

- CLAUDE.md: short notes — "agent prompts are registry-projected; guidance is
  layered; fact-check locked" and the rendering-contract change.
- `config/render.yaml.example` updated to the new keys.

## Out of scope

- Full workflow designer (add/remove/reorder agents, custom personas).
- Editing base instruction text or the fact-lock/provenance contracts.
- Visual template designer; non-Typst template formats.
- Any change to output storage or download endpoints.
