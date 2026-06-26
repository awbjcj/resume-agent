# Gap-Closing Advisor (Spec B)

**Date:** 2026-06-26
**Status:** Approved (design)
**Scope note:** This is **Spec B** of a two-spec split. Spec A
(`2026-06-26-match-gap-skill-intelligence-design.md`) builds the skill-demand
dashboard and produces the `{skill, jobs, theme}` shapes and the `SkillDrawer`
component that this spec consumes. Spec B adds **no new read path to the
dashboard** — it hangs a suggestion feature off Spec A's existing data and drawer.
Build Spec A first.

---

## 1. Problem

The dashboard shows *which* skills target jobs demand that the profile lacks. It
does not tell the user *how to close* a gap. Spec B adds an on-demand advisor: for
a single skill or a whole theme (skill-set), generate a grounded, cached
suggestion — real GitHub repos to learn from, courses/docs, a portfolio project to
build, and a profile-bridge framing ("you already know X, so Y is a short jump").
Suggestions are advisory only; they never become resume bullets, so **fact-lock
does not apply**.

### Decisions locked during brainstorming

| # | Decision |
|---|----------|
| 1 | **Search mechanism:** both a model-agnostic function-calling tool AND provider-native web search, behind one seam. |
| 2 | **Default `search_mode`:** `auto` — native where the provider supports it, tool fallback otherwise. |
| 3 | **Trigger & grain:** on-demand only, at **skill** level (drawer) and **theme** level (learning path). No batch precompute. |
| 4 | **Suggestion content:** GitHub repos, courses/docs/tutorials, a concrete project to build, and profile-bridge framing. |
| 5 | **Link trust:** verify GitHub repos via the GitHub API (existence + ★ enrichment, drop dead); other links shown as-is with citations. |
| 6 | **Persistence:** a `SkillSuggestion` DB table, fingerprint-based staleness. |
| 7 | **Synthesis:** two-stage — a search-equipped agent emits prose+citations, then a schema-only formatter parses it (decouples web search from structured output across providers). |

---

## 2. Search seam (extends `llm_runner.py`)

`llm_runner.py` is the only module that knows provider SDKs. Native web search
touches **both** the model constructor and the agent's `tools`, differently per
provider, so the whole strategy lives here.

### 2.1 Per-provider native mechanics (verified against agno docs)

| Provider | Native search | Where |
|---|---|---|
| Gemini | `Gemini(id=…, search=True)` | model constructor |
| Anthropic (default) | `tools=[{"type":"web_search_20250305","name":"web_search","max_uses":5}]` | agent tools |
| OpenAI | `OpenAIResponses(id=…)` (not `OpenAIChat`) + `tools=[{"type":"web_search_preview"}]` | model **and** tools |
| DeepSeek | none on the OpenAI-SDK path | → tool fallback |

Source: agno provider web-search docs (Gemini `search=True`; Anthropic
`web_search_20250305`; OpenAI Responses `web_search_preview`).

### 2.2 `search_mode` and the builder

New `Settings.search_mode: "auto" | "native" | "tool" | "off"` (default `auto`):

- **native** — use the provider's native search per the table; DeepSeek (no native)
  falls back to tool.
- **tool** — attach an agno function-calling search tool to any provider.
- **auto** (default) — native where supported, else tool. Anthropic being the
  default provider means native Claude web search works with zero config.

New seam function:

```
build_search_equipped(model_id: str, mode: str | None = None) -> tuple[model, list[tools]]
```

It resolves the provider via the existing `split_provider`, picks native vs tool
per `mode`, and returns the agno model (a Responses model for OpenAI native) plus
the `tools` list to spread into `Agent(...)`. SDK imports stay lazy per branch.

The agno tool itself is selected by `Settings.search_provider`
(`duckduckgo` default / `tavily` / `exa`), reading `Settings.tavily_api_key` /
`Settings.exa_api_key` when keyed. DuckDuckGo needs no key.

### 2.3 New Settings

- `search_mode: str = "auto"`
- `search_provider: str = "duckduckgo"`
- `tavily_api_key: str = ""`, `exa_api_key: str = ""`
- `github_token: str = ""` (raises GitHub API rate limits; optional)
- `advisor_model: str = ""` → falls back to `premium_model` when blank

---

## 3. Two-stage synthesis

Provider-native web-search tools combined with a strict `output_schema` can
conflict (server-tool use vs structured-output tool use; OpenAI's Responses path).
So generation is two LLM calls:

1. **Search agent** — `build_search_equipped` model+tools, **no** `output_schema`.
   Prompted with the skill/theme context (§4.2); returns prose + a citations list.
2. **Formatter agent** — schema-only (cheap tier, no tools), `output_schema =
   SuggestionDraft`. Parses stage-1 prose into the structured draft.

This one pipeline works identically for native and tool modes and every provider.

### 3.1 `SuggestionDraft` (ExtensibleModel, LLM-facing)

```
RepoRef       { name: str, url: str, why: str }
ResourceRef   { title: str, url: str, kind: str }     # "course" | "doc" | "tutorial"
ProjectIdea   { title: str, summary: str, skills_demonstrated: list[str] }
SuggestionDraft {
  repos: list[RepoRef]
  resources: list[ResourceRef]
  project: ProjectIdea | None
  bridge: str
  citations: list[str]
}
```

---

## 4. Generation service + Run

### 4.1 Service — `services/suggestions.py`

```
generate_suggestion(
  session, *, kind: "skill"|"theme", key: str,
  search_agent, formatter, github, facts, cluster_map, reporter=None,
) -> SkillSuggestion
```

Steps: assemble context (§4.2) → stage-1 search → stage-2 format → verify GitHub
repos via `github` → compute fingerprint (§5) → upsert the `SkillSuggestion` row.

### 4.2 Context assembly

- **skill**: the canonical skill, the profile-bridge inputs (covered/adjacent
  profile skills from `facts` + `cluster_map`), and the companies/titles demanding
  it (from the Spec A demand graph / `_target_jobs`).
- **theme**: the theme label + its member canonical skills + the jobs demanding any
  of them. The prompt asks for a learning *path* across the set.

### 4.3 Run endpoints (router: `api/routers/suggestions.py`)

- `POST /api/suggestions/generate` body `{ kind, key }` → `202` + `RunOut`.
  Worker opens its own session bound to `app.state.engine`, builds the two agents +
  GitHub client, calls `generate_suggestion`, returns `{kind, key}`. Run+SSE per the
  established pattern. `key` is in the **body**, not the path, so skill names with
  spaces/slashes need no encoding.
- `GET /api/suggestions?kind=&key=` → `SuggestionOut` + `stale: bool`, or
  `{ suggestion: null, stale: false }` when none cached.

---

## 5. Persistence — `SkillSuggestion` table

`tracking/tables.py` gains:

```
SkillSuggestion(SQLModel, table=True):
  id: int | None (pk)
  kind: str          # "skill" | "theme"
  key: str           # canonical skill display, or theme id
  payload_json: dict (JSON)   # the verified SuggestionOut payload
  fingerprint: str
  generated_at: datetime
  # unique (kind, key)
```

Upserted on regenerate (delete-then-insert or update in place). **Fingerprint** =
stable hash of `(key, sorted(profile_coverage_tokens), sorted(theme_member_skills))`.
`GET` recomputes the current fingerprint from live facts + cluster map; `stale =
stored.fingerprint != current` — e.g. after the user updates their profile or
re-clusters. Drives a "Regenerate" affordance.

A migration adds the table (follow the repo's existing migration pattern).

---

## 6. GitHub verification — `github/repos.py`

```
verify_repo(owner: str, name: str, *, token: str = "") -> RepoMeta | None
```

GETs `https://api.github.com/repos/{owner}/{name}` (httpx; `Authorization: Bearer`
when `token` set). Returns `RepoMeta{ full_name, url, stars, description }` on 200,
`None` on 404/error (repo dropped). A helper parses `owner/name` out of a GitHub
URL. The service maps each `RepoRef` through `verify_repo`, replacing `why` +
adding `stars`/`description`, dropping unresolved. All other links pass through
unchanged with their citation. Faked offline.

---

## 7. API schemas (`api/schemas/suggestions.py`, all `CamelModel`)

```
RepoOut      { name, url, why, stars: int | None, description: str | None }
ResourceOut  { title, url, kind }
ProjectOut   { title, summary, skills_demonstrated }   # → skillsDemonstrated
SuggestionOut{ kind, key, repos[], resources[], project | null, bridge,
               citations[], generated_at }             # → generatedAt
SuggestionEnvelope { suggestion: SuggestionOut | null, stale: bool }
```

`POST` reuses the existing `RunOut`. Regenerate `contracts/openapi.json` +
`contracts/ts/api.ts` via `bash scripts/gen_ts_client.sh`; the drift gate
(`tests/api/test_openapi_contract.py`) must stay green.

---

## 8. Frontend (inside Spec A's `SkillDrawer`)

- `web/src/features/match-gap/use-suggestion.ts` — `useSuggestion(kind, key)`
  (`useQuery` on the GET) + `useGenerateSuggestion()` (POST via `useLaunchRun`,
  invalidating the suggestion query on completion).
- `SkillDrawer` gains a **"How to close this gap"** section: cached suggestion
  renders repos as links with ★ stars + description, resource links, the project
  idea, and the bridge paragraph; absent → a **Generate** button fires the Run and
  watches SSE; `stale` → a badge + **Regenerate**.
- Each theme group in the dashboard gets a **learning-path** button (same flow with
  `kind: "theme"`), opening the drawer in theme mode.
- New presentational component `SuggestionPanel.tsx` (the rendered suggestion),
  tested with MSW for cached / empty / loading states.

---

## 9. Testing (offline — faked LLM, faked network)

- `build_search_equipped`: returns native config for anthropic/openai/gemini and
  tool config for deepseek under `auto`; honors `native`/`tool`/`off`. (Asserts the
  shape of the returned model/tools, not a live call.)
- `services/suggestions.generate_suggestion`: with a fake search agent, fake
  formatter (returns a `SuggestionDraft`), and fake `github` (verifies/drops);
  asserts repos verified, dead repos dropped, fingerprint computed, row upserted.
- Fingerprint staleness: changing profile coverage flips `stale`.
- Run endpoint: POST → poll to `done`; GET returns the cached envelope.
- OpenAPI contract gate regenerated and green.
- Frontend: `SuggestionPanel` + drawer wiring (cached/empty/generate) with MSW;
  `use-suggestion` hooks.

---

## 10. Out of scope

- Keyed search providers' billing/quota management.
- Multi-language resource curation.
- Anything that writes the resume — suggestions are advisory; **fact-lock does not
  apply** and they never auto-populate resume content.

---

## 11. Files touched (anticipated)

| Path | Change |
|------|--------|
| `src/resume_agent/llm_runner.py` | `build_search_equipped(model_id, mode)` + native/tool strategy; OpenAI Responses variant. |
| `src/resume_agent/config.py` (Settings) | `search_mode`, `search_provider`, `tavily_api_key`, `exa_api_key`, `github_token`, `advisor_model`. |
| `src/resume_agent/suggestions/agents.py` | **New.** `build_search_agent()`, `build_formatter_agent()`, `SuggestionDraft` + nested models. |
| `src/resume_agent/github/repos.py` | **New.** `verify_repo`, `RepoMeta`, URL parser. |
| `src/resume_agent/services/suggestions.py` | **New.** `generate_suggestion` + context assembly + fingerprint. |
| `src/resume_agent/tracking/tables.py` | **Add** `SkillSuggestion` table + migration. |
| `src/resume_agent/api/schemas/suggestions.py` | **New.** camelCase suggestion schemas. |
| `src/resume_agent/api/routers/suggestions.py` | **New.** POST generate (Run) + GET cached. |
| `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` | Regenerated. |
| `web/src/features/match-gap/use-suggestion.ts`, `SuggestionPanel.tsx` | **New.** |
| `web/src/features/match-gap/SkillDrawer.tsx` | **Modify** to host the suggestion section + theme learning-path entry. |
| Tests (backend + frontend) | As in §9. |
