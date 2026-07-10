# Profile Depth — GitHub Project Profiles, Dossiers, and Material Intake

**Date:** 2026-07-10
**Status:** Approved
**Problem:** The profile build draws almost entirely from the resume. GitHub
contributes only shallow repo metadata (name, description, one language, topics,
stars) via `repo_to_project` — `GitHubClient.fetch_readme` exists but is never
called. READMEs, CLAUDE.md/CONTEXT.md/AGENTS.md, per-repo language breakdowns,
and code-level insight never reach the fact-lock, so tailoring has thin project
material and a sparse skill matrix to work with.

**Goal:** Maximize facts/skills/projects available to tailoring while keeping
the fact-lock honest: every new fact traces to a source document the user
authored or generated, and repo-derived text can never fabricate employment
history.

---

## 1. Architecture overview

Two-tier GitHub depth, one ingestion path. Everything becomes a **corpus source
document** and rides the existing fragment pipeline (sha-keyed cache → extract →
merge → matrix). No parallel cache or registry is introduced.

- **Tier 1 — auto-harvest (breadth):** a GitHub harvester fetches each
  qualifying repo's root docs and writes them as a virtual source doc
  `sources/github--<repo>.md`, registered in `sources.json` with
  `origin="github"`, `mode="project"`.
- **Tier 2 — project dossier (depth):** a new **`project-dossier` skill**
  (shipped in this repo under `.claude/skills/project-dossier/`) that the user
  runs in a separate Claude Code session inside any repo. With full codebase and
  git-history access it emits `<repo>-dossier.md` in a fixed format. The user
  adds it like any upload; **a dossier supersedes the auto-doc for the same
  `repo_url`**.
- The deterministic metadata merge (`repo_to_project` + `build_github_profile`)
  stays, upgraded with the `GET /repos/{owner}/{repo}/languages` endpoint so
  `Project.languages` carries the full byte-weighted language list instead of a
  single language.

Additional material intake (independent of GitHub): **quick-add text notes** and
**URL ingestion**, both landing as small `.md` literal sources.

## 2. Model and mode changes

### SourceDoc

- New field `origin: Literal["upload", "github"] = "upload"`.
  - `origin="github"` docs are owned by the harvester: it creates, refreshes,
    and removes them. `remove_source` works on them like any doc.
  - The SourcesPage badges github-origin docs and can refresh them as a group.
- `SourceMode` gains a third value: `"project"`.
  - Manifest validation: the primary must remain `literal` (unchanged);
    `anchor` remains synthesis-only (a `project`-mode doc may not carry one).

### Project extraction mode

A `project`-mode doc runs a **project-scoped extractor** (new prompt + response
schema, same `AgentRunner` seam):

- May emit **exactly one `Project`** — description, role, tech, highlights.
  Quantified claims in the doc (e.g. "reduced latency 40%") become claimable
  Project highlights with fact ids, because the user authored the source.
- May emit **skills** evidenced by the doc. These are regular extracted skills
  (`inferred=false`) with fact-id provenance, so the skill matrix picks them up
  and they survive rebuilds (unlike `inferred=true` skills, which are
  regenerated each build).
- May **never** emit `Experience`, `Education`, `Certification`, or any other
  section — a template README or forked doc cannot inject employment claims.
  The resume (and other literal uploads) remain the sole authority on
  employment history.
- Fragment caching, meta files, and staleness reuse the existing walk; the
  project-mode meta records its own prompt version
  (`project_prompt_version`) so prompt bumps invalidate only project fragments.
- The project extraction boundary is closed even though the repository's general
  fact models preserve forward-compatible extras: undeclared project-document
  sections are rejected, nested Project/Skill values are projected back to their
  declared fields, GitHub-origin facts are marked `source=github`, and uploaded
  dossier facts are marked `source=manual` before deterministic fact ids are
  assigned.

### Merge identity

The fragment's `Project` and the metadata `Project` (from `repo_to_project`)
unify on normalized `repo_url` (HTTPS and SSH GitHub remote forms, optional
`.git`, case, and trailing slash normalize identically; fallback: normalized
repo name). This identity rule applies while merging literal/project/synthesis
fragments as well as during metadata enrichment:

- Metadata side fills: `stars`, `forks`, `languages` (byte-weighted full list),
  `topics`, `last_updated`, `is_fork`, `primary_language`, `homepage_url`.
- Fragment side fills: `description`, `role`, `tech`, `highlights`.
- Result: one Project row per repo, never duplicates.

## 3. Tier 1 — GitHub auto-harvest

### Repo selection

- Default: skip forks, skip archived repos, skip repos containing none of the
  target docs. Deny always wins. Allowlisted repos bypass fork/archive filters
  and are prioritized before the bounded newest-repo selection, so a
  "force-include" cannot be dropped by the cap.
- Order: newest `pushed_at` first; cap at a configurable limit (default 20).
- Profile config (config store, `profile` section) gains:
  `github_repo_allow` (force-include, e.g. an authored fork),
  `github_repo_deny` (exclude), `github_repo_limit`.

### Harvest set (per qualifying repo)

- One root contents-listing call; case-insensitive match on:
  `README*` (any extension, incl. `readme.txt`), `CLAUDE.md`, `CONTEXT.md`,
  `AGENT.md`, `AGENTS.md`.
- Each file is truncated at 30,000 UTF-8 bytes before concatenation, without
  splitting a code point; the combined virtual document is also bounded.
- `GET /repos/{owner}/{repo}/languages` → full language byte map.
- The virtual doc is deterministic markdown: a header block (repo name, url,
  languages, topics, stars) followed by each harvested file under a labelled
  heading. Deterministic bytes ⇒ unchanged repos produce identical files ⇒
  fragment-cache hits ⇒ steady-state LLM cost ≈ 0. Files, topics, and languages
  are sorted deterministically, GitHub-safe repo filename characters are
  preserved to avoid slug collisions, and writes use atomic sibling replace.

### Sync timing

- **Phase 0 of every profile build** (when a GitHub username is configured):
  fetch repo list → write changed virtual docs → register new manifest entries →
  remove `origin="github"` entries whose repos disappeared, were delisted, or
  are now superseded by a dossier → then the normal fragment walk runs.
- Also exposed standalone: `resume-agent profile sync-github` and an API run
  (`POST /api/profile/sync-github`, 202 + run record) so the SourcesPage can
  refresh GitHub sources without paying for a full rebuild.
- Network failure degrades to a `BuildReport.warnings` entry; the build proceeds
  on cached virtual docs.

## 4. Tier 2 — project-dossier skill

- Lives at `.claude/skills/project-dossier/SKILL.md` in this repository so any
  Claude Code session can invoke it inside a target repo.
- Output: `<repo>-dossier.md` with YAML frontmatter:

  ```yaml
  ---
  repo_url: https://github.com/you/resume-agent
  repo_name: resume-agent
  role: sole author
  generated_at: 2026-07-10
  ---
  ```

  and fixed sections: `# Project: <name>`, `## Summary`,
  `## Tech stack (evidence-backed)`, `## Architecture highlights`,
  `## Quantified outcomes`, `## Skills demonstrated`.
- Skill rules (the extraction contract): only claims verifiable from the repo's
  code, docs, or git history; no employment/education claims; quantified
  outcomes must cite their evidence (file, benchmark, commit); tech stack items
  must exist in the code, not just be mentioned.
- Ingestion: the user adds the dossier like any source (SourcesPage upload, CLI
  `profile add`, or writing directly into `data/profile/sources/`).
  `add_source` sniffs `repo_url:` frontmatter on `.md` files and defaults such
  docs to `mode="project"`.
- **Dossier wins:** at sync time, any auto-harvested virtual doc whose repo URL
  matches an upload-origin doc's `repo_url` frontmatter is skipped (and an
  existing one removed). Deep beats shallow; repos without dossiers still
  contribute their tier-1 doc.

## 5. Material intake additions

- **Quick-add note:** `POST /api/profile/sources/note` `{title, text}` and CLI
  `resume-agent profile add-note` — writes `note--<slug>.md` as a literal
  source. Lowest-friction path for facts that live in no document ("led the
  on-call rotation for 2 years").
- **URL ingestion:** `POST /api/profile/sources/url` `{url}` and CLI
  `resume-agent profile add-url` — fetches the page with httpx, converts via
  `html_to_text`, saves as a literal `.md` source. For portfolio pages,
  published articles, online resumes.
- Both create ordinary manifest entries (`origin="upload"`, `mode="literal"`)
  and need no new merge machinery.
- URL ingestion is a network security boundary: it accepts only credential-free
  public HTTP(S) targets, rejects non-public resolved addresses, revalidates
  redirects, bounds redirects and response bytes, and accepts readable text
  content types only. A failed fetch never registers a source.

## 6. Error handling

- GitHub network failure: warning in `BuildReport.warnings`, build proceeds on
  cached docs. Per-repo harvest failures are isolated (recorded, never abort the
  sync) — same philosophy as connector `.failures`.
- Rate limits: ~4 API calls/repo × 20 repos exceeds the unauthenticated 60/hr
  limit. On a 403 rate-limit response the harvest stops early with a warning
  recommending `github_token`; already-written docs stand.
- Dossier with malformed/missing frontmatter: ingested as a plain literal `.md`
  with a warning (no crash, no project-mode default).
- Project-mode extraction failure for one doc: existing `_record_failure`
  behavior — previous fragment reused if present, otherwise the doc is skipped
  for this build.

## 7. Cost profile

- First build with N qualifying repos: N project-mode extraction calls
  (mid-tier model) + up to ~4N GitHub API calls. Default N ≤ 20.
- Subsequent builds: only changed repos re-extract; everything else is a
  fragment-cache hit.

## 8. Testing (offline, per repo convention)

- Harvester against httpx `MockTransport` fixtures: repo selection
  (fork/archived/no-docs skips, cap, allow/deny), doc truncation, deterministic
  virtual-doc bytes, delist removal, dossier-supersede, rate-limit early stop.
- Project-mode extraction with a fake agent: schema restriction (single Project
  + skills only; foreign sections rejected/dropped), fact-id assignment,
  fragment cache meta round-trip.
- Manifest: `origin` field round-trip, `project` mode validation (primary stays
  literal, anchor rejected).
- Merge identity: fragment Project + metadata Project unify by `repo_url`; no
  duplicate rows; languages byte-map mapping.
- `add_source` frontmatter sniffing → `mode="project"` default.
- Notes/URL endpoints + CLI; OpenAPI contract regen
  (`tests/api/test_openapi_contract.py` drift gate).
- Run tracking: standalone GitHub sync is tracked through the existing run/SSE
  surface; the web source list invalidates when that run completes, not merely
  when the `202` launch response arrives.
- Settings: repo allow/deny/limit are editable on the Profile settings page and
  share the same typed/bounded contract used by API, service, and CLI.

## 9. Out of scope

- Recursive doc search inside repo trees (docs/, monorepo subpackages) — noted
  as a possible later refinement.
- Private-repo harvesting UX beyond "set `github_token`".
- LLM summarization of code itself in tier 1 (that is the dossier skill's job).
- New file-format converters (.tex, .ipynb, LinkedIn export).
