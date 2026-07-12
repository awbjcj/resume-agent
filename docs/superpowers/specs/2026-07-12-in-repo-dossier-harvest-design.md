# In-Repo Dossier Harvesting — Design

**Date:** 2026-07-12
**Status:** Approved for planning

## Problem

The GitHub harvest (`profile/github_harvest.py`) only fetches root README and
context docs (`README*`, `claude.md`, `context.md`, `agent.md`, `agents.md`)
into one virtual doc per repo, and the project extraction schema
(`ProjectDocFacts`) emits exactly one `Project` per document. Consequences:

1. A dossier produced by the `project-dossier` skill and committed to its repo
   is invisible to the harvest — it must be manually uploaded via
   `resume-agent profile add`.
2. A monorepo containing several distinct projects is flattened into a single
   Project fact.

## Decision summary

| Decision                   | Choice                                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Multi-project shape        | Multiple dossier files, each describing exactly one project; the one-project `ProjectDocFacts` schema is untouched                                                       |
| Detection                  | Root-listing filename match `*dossier*.md` (case-insensitive), confirmed by valid `repo_url:` frontmatter after fetch                                                    |
| Frontmatter validation     | Dossier `repo_url` must normalize (via `normalize_repo_url`) to the harvested repo's own URL; mismatches are skipped with a warning                                      |
| README virtual doc         | Replaced: if ≥1 valid dossier is found, `github--<repo>.md` is not written and an existing one is removed; zero valid dossiers → README doc exactly as today             |
| Manual-upload supersession | Unchanged repo-level key: an uploaded dossier with the repo's URL removes ALL github-origin docs for that repo (README doc and harvested dossiers) and blocks re-harvest |
| Limits                     | 30 KB per dossier (existing `_MAX_FILE_BYTES`), max 5 dossiers per repo (alphabetical by filename), repo root only; overflow → `HarvestReport.warnings`                  |

## Behavior

### Discovery (in `sync_github_sources`)

For each selected repo, partition the root listing:

- Entries matching `*dossier*.md` (case-insensitive) are dossier candidates.
- README/CONTEXT picks (`_pick_doc_entries`) are computed exactly as today but
  only used when no valid dossier survives validation. Dossier discovery must
  not remove a name such as `README-dossier.md` from this fallback set; doing
  so would violate the zero-valid-dossier compatibility guarantee.

Fetch at most 5 candidates in deterministic alphabetical (casefolded) order.
If more than 5 match, record a warning naming the skipped files. A fetched
candidate is **valid** when `frontmatter_repo_url` yields a URL that
normalizes to the harvested repo's `html_url`. Invalid candidates (missing or
foreign `repo_url`) are skipped; each foreign-URL skip records a warning.

### Materialization

Each valid dossier becomes its own source doc:

- Filename `github--<repo>--<dossier-slug>.md`, where `dossier-slug` is the
  dossier filename stem sanitized by the existing `_SAFE_REPO_NAME` rule;
  filename conflicts with non-github docs resolve via the existing sha1-suffix
  scheme. If two dossier names sanitize to the same slug, every member of that
  collision group receives an identity-derived sha1 suffix based on the
  original filename. Re-sync must allocate the same names so one candidate can
  never overwrite another.
- Content is the dossier file **verbatim** (it already carries frontmatter),
  truncated to 30 KB with `_truncate_utf8`; written atomically only when
  changed, so unchanged dossiers keep their sha and hit the fragment cache.
- Registered with `mode="project"`, `origin="github"`, participating in the
  existing `kept`-set cleanup so removed/renamed dossiers are purged on the
  next successful sync.

### Replacement semantics

If a repo yields ≥1 valid dossier, the README virtual doc for that repo is
not written and is absent from `kept`, so the existing cleanup removes any
stale `github--<repo>.md`. If a repo yields zero valid dossiers, harvest is
byte-for-byte identical to today.

### Supersession (unchanged)

`dossier_repo_urls` still scans only `origin == "upload"` docs. A manual
upload whose `repo_url` matches the repo removes all github-origin docs for
that repo (`_remove_local_superseded` plus the harvest-loop skip) — README
doc and harvested dossiers alike — and blocks future re-harvest.

### Extraction (unchanged)

Harvested dossier docs flow through `extract_project_fragments` →
`aextract_project_facts` as any other project-mode doc: one `Project` plus
evidenced skills per doc, closed schema, fact-lock intact, cache keyed by
content sha + `PROJECT_PROMPT_VERSION`. A multi-project repo yields N Project
facts because it yields N docs, not because the schema changed.

### Failure posture (unchanged)

Per-repo fetch/parse failures land in `HarvestReport.failures` and keep the
previous doc (`kept.add`). Rate-limit responses stop the sync early and
preserve all cached docs, exactly as today.

## project-dossier skill update

`.claude/skills/project-dossier/SKILL.md` gains a monorepo clause:

- When the repository contains multiple distinct projects, write one
  `<project-slug>-dossier.md` per project at the repository root, each with
  the same `repo_url` (the repo's canonical URL) and its own `# Project:`
  section describing exactly one project.
- The handoff note mentions that committing dossiers to the repo root lets
  `resume-agent profile sync-github` pick them up automatically — manual
  `profile add` remains the way to override.

## Out of scope

- No per-project supersession key (`project:` frontmatter) — repo-level
  upload-wins is sufficient.
- No `dossiers/` subdirectory listing — root only.
- No new Settings knobs; caps are constants.
- No changes to `ProjectDocFacts`, fragment cache metadata, or fact-lock.

## Testing

Extend `tests/` github-harvest coverage with fixture-driven cases:

1. Repo with one valid dossier → dossier doc written, README doc absent and
   removed if previously present.
2. Repo with three dossiers → three docs with distinct filenames, stable
   across re-sync (cache hit, no rewrite).
3. Name-matched file without frontmatter → ignored, README fallback intact.
4. Dossier with foreign `repo_url` → skipped with warning.
5. More than 5 candidates → first 5 alphabetically, warning lists the rest.
6. Manual upload for the repo → all harvested docs (README + dossiers)
   removed, repo skipped on re-sync.
7. Rate-limit mid-repo → cached dossier docs preserved.
8. Two dossier filenames that sanitize to the same stem → two stable, distinct
   source filenames; neither dossier is overwritten.
