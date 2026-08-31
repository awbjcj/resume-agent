# Skill Groups + Eval Anchoring — Design

**Date:** 2026-07-10
**Status:** Approved (grilled 2026-07-10)
**Plans:** one — skill-group axis on the matrix, then the live eval-anchoring checkpoint.

## Problem

The skill matrix's only categorization is `category: Literal["hard", "soft",
"domain"] | None` — coarse, and rows whose skills never received a category
render as uncategorized. The Profile skills page cannot bucket ~hundreds of
matrix rows usefully. Separately, the eval harness (resume + cover-letter)
has never been run live, so the LLM judge baseline is unanchored.

## Decision (grilled 2026-07-10)

Add a **second, finer `group` axis** on matrix rows. `category`
(hard/soft/domain) is untouched — it is load-bearing for fact-lock (only hard
skills may appear as skills-section tokens) and for the inference prompt.
Match-gap keeps its dynamic ClusterMap themes; the fixed group vocabulary
applies to the profile matrix and its web page only.

## Non-goals

- No change to `category`, fact-lock, inference, or `models/profile.py`'s
  `Skill` — the group lives on the **derived** `MatrixRow`, not on facts.
- No change to match-gap themes, aggregation, or suggestions.
- No freeform LLM-invented groups — the vocabulary is fixed in code.

## 1. Group vocabulary

A fixed constant (in `resume_tailor_harness/taxonomy/`, exported for reuse):

```
languages, frameworks, cloud-infra, data-ml, databases, devops-tooling,
testing-quality, security, practices, leadership, communication,
domain-knowledge, other
```

`other` is the visible fallback for anything unassigned or unclassifiable —
never hidden. Display labels ("Cloud & Infra", "Data & ML", …) live beside the
slugs.

## 2. Assignment — incremental, durable, override-able

- **Durable taxonomy file:** `data/taxonomy/skill_groups.json` mapping
  canonical skill token → group slug. Loaded/merged/saved like the ClusterMap
  (first-writer-wins on merge; unknown slugs dropped on load).
  Runtime call sites resolve this path from the active injected data root; tests
  and alternate app data directories must not fall back to the repository's
  production `data/` tree. Writes normalize keys, validate values, merge with
  the latest persisted state, and use an atomic sibling replace.
- **Incremental classification:** during matrix build, the delta = matrix row
  keys not present in the taxonomy file. Only the delta is sent to the LLM
  (cheap tier), sharded into batches, mirroring the
  `taxonomy/classification.py` pattern (shard → classify → validate slugs →
  merge additions → save). A batch failure leaves its tokens unassigned
  (`other` at render time) and they retry on the next build — absence-as-retry,
  same policy as industry normalization.
- **Overrides:** `Overrides` in `profile/matrix.py` gains
  `group: dict[str, str]` (token → slug, validated against the vocabulary).
  Overrides are applied after taxonomy lookup, as the last word — same
  precedence position as the existing `category` override. Durable
  corrections belong in `data/profile/overrides.yaml`, consistent with the
  "profile rebuilds regenerate inferred skills" design note.
- Group overrides do not participate in match-gap canonicalization and cannot
  create matrix rows. They only decorate rows already derived from profile
  facts; this keeps the display axis isolated from dynamic match-gap taxonomy.
- **MatrixRow:** gains `group: str | None = None` (slug; `None` renders as
  `other`). `matrix.json` is a derived artifact — no migration; rows gain
  groups on the next `profile build`.

## 3. Surfacing

- The profile/matrix API schema exposes `group` (camelCase, additive) and the
  ordered slug/label vocabulary used to render it, keeping the backend as the
  single source of truth for display order and labels. The route resolves the
  matrix from the request's configured data root and returns an empty row list
  plus the vocabulary before the first successful build;
  `bash scripts/gen_ts_client.sh` regenerates the contract and the OpenAPI
  drift gate stays green.
- The Profile skills page groups rows by group (section headers or filter
  chips, matching the page's existing filter idiom), with `other` last and
  visible so coverage gaps are inspectable. Loading, fetch-error/retry, and
  empty states are explicit and accessible.

## 4. Live eval anchoring (checkpoint)

A **LIVE CHECKPOINT** task at the end of the implementation plan (requires a
configured provider key and spends tokens):

- The cover-letter baseline already exists at
  `evals/reports/2026-07-cl-baseline.json`; verify its recorded prompt hash and
  preserve it. Run the resume eval sitting (`make eval` /
  `evals/run_eval.py`) once against the live judge unless a current-schema
  artifact already matches the current case set, judge model, and prompt hash.
- Record scores + judge prompt hashes in `evals/RESULTS.md` and a dated report
  under `evals/reports/`, establishing the anchored baseline the
  agent-quality roadmap has been missing.
- No code changes expected; if a sitting surfaces a harness defect, fix
  forward in the same plan.

## Constraints

- Offline suite green with no key/network; classification agent faked in
  tests (fixture assignments), exactly like the ClusterMap tests.
- `ruff check` clean; contract regen on any schema change.
- Group assignment must never touch `facts.json` — the matrix stays the only
  artifact that carries groups.
