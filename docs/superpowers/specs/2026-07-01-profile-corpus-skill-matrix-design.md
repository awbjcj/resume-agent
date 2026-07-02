# Profile Corpus, Evidence-Linked Skills & Skill/Experience Matrix

**Date:** 2026-07-01
**Status:** Approved design, pre-implementation

## 1. Problem

Tailored resumes hit too few of the skills a JD demands, for three compounding
reasons:

1. **Supply is thin.** The profile is built from a single resume file (plus
   GitHub). A resume is a summary; the user's fuller evidence — case-study
   decks, project write-ups, notes — never enters `facts.json`.
2. **Extraction is deliberately anti-inference.** The extractor's instructions
   say "never infer … skills", so abilities that are demonstrated but not
   literally named (almost all soft skills, many hard skills) never become
   facts.
3. **Vocabulary mismatch.** Profile skill tokens and JD skill tokens only match
   on normalized string equality plus hand-set `Skill.aliases`. The demand side
   has an LLM-built canonical alias/theme `ClusterMap`
   (`data/profile/cluster_map.json`), but nothing populates profile-side
   aliases, and related-but-distinct skills (Flask vs FastAPI) count as zero.

Soft skills are the worst case: `JobCriteria` has no soft-skill field (they
land unreliably in `must_have_skills`/`nice_to_have_skills`), and the profile
has no structured place for them to come from.

## 2. Decisions locked during brainstorming

| Decision | Choice |
| --- | --- |
| Inference policy | **Evidence-linked inference.** Derived skills (incl. soft) carry `evidence_fact_ids` → literal facts and `inferred=true`. Literal claims (bullets, dates, metrics, titles) stay strictly extraction-only. |
| Corpus model | **Source registry + per-doc extraction.** Manifest with per-doc content hash; fragments cached; adding one doc re-extracts one doc; stable fact ids across re-merges. |
| Merge/dedup | **Deterministic entity keys + union; cheap LLM collapses near-duplicate bullets; primary document wins scalar conflicts; conflicts reported.** |
| Matrix | **Derived index** (`data/profile/matrix.json`), regenerated from facts, never hand-edited. Consumed by match-plan, match-gap coverage, and fit scoring. |
| Match tiers | **Two-tier.** Equivalent (shared canonical alias space) = covered; same theme = adjacent (partial credit, transferability framing); else gap. |
| Soft skills | **Category-tagged, shown via bullets.** No new `JobCriteria` field; JD-criteria prompt strengthened; match-plan selects demonstrating bullets and echoes JD vocabulary in the summary — no "Soft skills:" label list. |
| Surface | **CLI first** (`profile add/remove/sources/build`); web Profile page is a phase-2 spec. |
| Curation | **Automatic + overrides file** (`data/profile/overrides.yaml`), applied last in matrix generation; no mandatory review gate. |
| Inferred hard skills | **Renderable.** An evidence-backed inferred hard skill may appear in the rendered skills section; the fact-check gate accepts an inferred skill whose `evidence_fact_ids` resolve. Soft skills stay out of the skills section. |

## 3. Fact-lock statement (invariant preserved)

Fact-lock survives unchanged in spirit and gains one clarification:

- Every **written claim** on a tailored resume still traces to a literal fact
  extracted from a user-authored document.
- An **inferred skill** is a *pointer*, not a claim: it may guide selection and
  emphasis, and (hard skills only) appear as a skills-section token, because
  its `evidence_fact_ids` resolve to literal facts. The fact-check reviewer
  treats "inferred skill with resolvable evidence ids" as valid provenance for
  a skills-section entry — never for bullet text.
- Adjacent-tier matches are **never claimable**: the planner may argue
  transferability ("built REST services in Flask") but may not emit the JD's
  token ("FastAPI") as a candidate skill.

## 4. Source corpus & registry (`profile/corpus.py`)

- `data/profile/sources/` holds a copy of every ingested document.
- `data/profile/sources.json` manifest — one entry per doc:
  `{id, filename, sha256, added_at, primary: bool}`. Exactly one `primary`
  (the canonical resume; wins scalar conflicts in merge).
- Atomic writes (same tmp-then-replace pattern as `save_cluster_map`).

**Migration.** `config/profile_sources.yaml` keeps `github_username`.
On `profile build`, if the manifest is empty and `resume_path` is set, the
legacy resume is auto-registered as the primary source. `resume_path` is then
documented as deprecated in favor of `profile add --primary`.

**Readers.** `profile/resume_reader.py` generalizes to
`read_document_text(path)` supporting:

| Format | Mechanism |
| --- | --- |
| `.txt`, `.md` | plain UTF-8 read (markdown syntax passes through; the extractor handles it) |
| `.pdf` | `pypdf` (existing) |
| `.docx` | `python-docx` paragraphs + table cells (existing) |
| `.pptx` | **new dep `python-pptx`**: all slide text frames + speaker notes, slide order preserved, one blank line between slides |

Unsupported suffix → same `ValueError` style as today.

## 5. Per-document extraction + fragment cache

- Each registered doc extracts independently into a ProfileFacts-shaped
  fragment at `data/profile/fragments/{doc_id}.json`, with sidecar metadata
  `{sha256, prompt_version}`.
- `profile build` re-extracts a fragment only when the doc hash or
  `PROMPT_VERSION` (a module constant bumped when extractor instructions
  change) differs from the sidecar. Removing a doc deletes its fragment.
- The extraction agent is the existing `build_extractor_agent` with its
  anti-inference instructions **unchanged**; one instruction is added to note
  the input may be a deck/notes document, not only a resume, and that
  `contact` may legitimately be sparse (a fragment's `contact.name` may be
  empty; merge fills it from the primary).
- Per-doc failures do not abort the build: a failed fragment keeps its previous
  cached version (if any) and is reported.

## 6. Model changes (`models/base.py`, `models/profile.py`)

```python
class FactItem(ExtensibleModel):
    id: str
    source: Source            # unchanged enum: resume | github | manual
    source_ref: str | None    # NEW: doc id from sources.json (None for github/manual)

class Skill(FactItem):
    name: str
    aliases: list[str]
    context: str | None
    inferred: bool = False              # NEW
    evidence_fact_ids: list[str] = []   # NEW: required non-empty when inferred
    category: Literal["hard", "soft", "domain"] | None = None  # NEW
```

All new fields default to today's semantics, so existing `facts.json` files
load unchanged (`ExtensibleModel` round-trips unknown/absent keys).

**Stable fact ids.** `new_id()` (uuid4) is replaced, for corpus-derived facts,
by a deterministic id: `sha1(f"{doc_id}|{entity_key}|{content_key}")[:12]`
computed at fragment post-processing (the LLM's ids are discarded). Unchanged
facts therefore keep ids across rebuilds, so provenance links in existing
`ResumeVersion` rows survive. Merged entities keep the primary fragment's
entity id; absorbed bullets keep their own ids.

## 7. Inference pass (`profile/inference.py`)

Runs after merge, over the merged literal facts:

- Input: merged `ProfileFacts` JSON (ids visible).
- Agent (mid tier) returns `InferredSkill[]`:
  `{name, category, evidence_fact_ids, rationale}`.
- Post-processing drops any entry whose `evidence_fact_ids` don't all resolve
  (mirrors `normalize_match_plan`'s id-validation pattern), then appends
  surviving entries to `facts.skills` under their category with
  `inferred=true`; `source` is copied from the first evidence fact and
  `source_ref` stays `None` (the evidence ids are the provenance).
- Instructions: derive only abilities *demonstrated* by the evidence facts
  ("mentored 3 engineers" → mentorship); never invent seniority, credentials,
  durations, or tools not implied by explicit text; prefer conventional JD
  vocabulary for names (that is what matching runs on).
- Idempotent: inferred skills are regenerated on every build (they are cheap
  and derived), deduplicated against literal skills by normalized token.

## 8. Merge v2 (`profile/merge.py`)

Order: fragments (primary first) → entity merge → bullet dedup → literal
`facts.json` → inference pass → final `facts.json` → matrix.

- **Entity keys.** Experience: `normalize(company)` + title-token overlap or
  date-range overlap. Project: `_norm(name)` (as today). Education:
  `normalize(institution)` + degree. Certification/publication/award: name.
- **Union.** Bullets, `tech`, honors, highlights union across fragments; a
  cheap-tier LLM pass flags near-duplicate bullet pairs (reworded same
  accomplishment) and the shorter one is dropped. LLM failure → keep both
  (safe, verbose).
- **Scalar conflicts.** Primary doc wins; non-primary fills nulls only.
  Every overridden conflict (e.g. differing dates) is collected into the build
  report — never silently swallowed.
- GitHub ingestion is untouched: `merge_facts`'s project-enrich runs after the
  corpus merge, exactly as today.

## 9. Skill/experience matrix (`profile/matrix.py`)

`data/profile/matrix.json` — derived, regenerated on every build, never
hand-edited:

```jsonc
{
  "generated_at": "...",
  "rows": [
    {
      "key": "kubernetes",            // canonical token (shared alias space)
      "display": "Kubernetes",
      "aliases": ["k8s"],
      "category": "hard",             // hard | soft | domain
      "inferred": false,
      "evidence_fact_ids": ["..."],   // skills: own id + evidence ids; plus bullets/tech mentioning it
      "strength": 7.2,                // evidence count × recency decay
      "last_used": "2026-03"
    }
  ]
}
```

- `strength = Σ evidence-fact weight × recency`, where recency decays by the
  owning experience/project `end` date (current role = 1.0). Exact curve is an
  implementation detail; must be deterministic.
- **Overrides** (`data/profile/overrides.yaml`) apply last:

```yaml
ban: [synergy]                  # tokens never emitted
alias: {golang: go}             # forced equivalences
forbid_alias: [[java, kotlin]]  # never merge these
category: {ownership: soft}     # recategorize
```

## 10. Shared canonical space & two-tier matching

- `refresh_clusters` (`services/match_gap.py`) currently canonicalizes and
  themes **demand** tokens only, then prunes the map to demanded tokens.
  Change: the token universe becomes
  `collect_target_skill_tokens(session) ∪ profile_skill_tokens(facts)`, and
  **the prune keep-set includes profile tokens** — otherwise profile aliases
  would be garbage-collected on every refresh.
- Tiers, given canonical map `A` and theme map `T`:
  - **covered**: `A(jd_token) ∈ A(profile_tokens)`
  - **adjacent**: not covered and `T(A(jd_token))` equals the theme of some
    covered profile token
  - **gap**: neither
- Overrides' `alias`/`forbid_alias` are applied to the loaded `ClusterMap`
  before matching (forbid splits a merged pair back to distinct tokens).

## 11. Consumers

- **`tailor/match_plan.py`** — `compose_match_plan_input` gains a
  `SKILL MATRIX` section (rows relevant to the JD: covered + adjacent, with
  evidence ids and strengths). New instructions: prefer high-strength evidence;
  for **adjacent** requirements, select transferable evidence and note the
  framing, never claim the JD token; for **soft** requirements, satisfy by
  selecting bullets that demonstrate the trait and echoing JD vocabulary in
  the summary.
- **`tracking/match_gap.py`** — `SkillNode.covered: bool` becomes
  `coverage: Literal["covered", "adjacent", "gap"]` (API schema + dashboard
  follow; `covered` kept as a derived bool during transition). Gap report
  excludes covered, keeps adjacent flagged separately.
- **`discovery/fit.py`** — `compose_fit_input` includes the compact matrix
  (canonical skills + categories + strengths) instead of only raw profile
  skills; instructions updated to award partial credit for adjacent skills.
  The "never infer an unlisted skill" instruction stays — the matrix *is* the
  list now.
- **Fact-check reviewer (`review.yaml` path)** — gains the §3 rule: a
  skills-section token passes if it matches a literal skill **or** an inferred
  skill whose evidence ids resolve.

## 12. Demand side (soft-skill capture)

The JD-criteria extraction instructions are strengthened to explicitly
capture interpersonal/behavioral requirements (leadership, mentorship,
stakeholder & cross-team communication, ownership) into
`must_have_skills`/`nice_to_have_skills` using the JD's own wording. No schema
change; existing rows are not re-extracted (they refresh naturally on next
criteria run).

## 13. CLI (`cli.py`, `profile_app`)

| Command | Behavior |
| --- | --- |
| `profile add <file> [--primary]` | Copy into `sources/`, register in manifest (hash, id). |
| `profile remove <id\|filename>` | Unregister + delete fragment; keeps the file copy unless `--purge`. |
| `profile sources` | Table: id, filename, primary, hash prefix, added, fragment status. |
| `profile build` | Re-extract stale fragments → merge → inference → facts.json → matrix.json. Prints report: per-doc status, scalar conflicts, new inferred skills w/ evidence snippets, alias/category changes, matrix size. |

`profile build` keeps its current options (`--sources`, `--facts`) for the
legacy path and GitHub username.

## 14. Testing (offline, as always)

- Fixture corpus: tiny `.md`, `.txt`, generated minimal `.docx`/`.pptx`
  fixtures (created by a test helper, checked in as bytes or built in-test).
- Faked agents for: fragment extraction, bullet dedup, inference,
  canonicalizer/themer (existing fakes reused).
- Deterministic tests: manifest round-trip; hash-based cache skip/invalidate;
  entity-key merge incl. conflict report; stable-id preservation across
  rebuild; inference id-validation drop; matrix strength determinism;
  overrides (ban/alias/forbid/category); tri-state coverage incl. the prune
  keep-set regression (profile aliases survive `refresh_clusters`).
- Contract: `match_gap` API schema change regenerates `contracts/openapi.json`
  (drift gate `tests/api/test_openapi_contract.py`).

## 15. Out of scope

- Web Profile page (upload UI, matrix visualization) — phase-2 spec.
- Embedding-based similarity.
- Re-extracting criteria for existing jobs.
- Gmail/LinkedIn as corpus sources.
- Location-aware dedup key (pre-existing known gap).

## 16. Files touched (anticipated)

| Path | Change |
| --- | --- |
| `src/resume_agent/profile/corpus.py` | NEW — registry, manifest, readers dispatch. |
| `src/resume_agent/profile/resume_reader.py` | `read_document_text` + `.md`/`.pptx`. |
| `src/resume_agent/profile/extractor.py` | Prompt version const; deck-aware instruction. |
| `src/resume_agent/profile/inference.py` | NEW — evidence-linked skill inference. |
| `src/resume_agent/profile/merge.py` | Entity-key merge, bullet dedup, conflict report. |
| `src/resume_agent/profile/matrix.py` | NEW — matrix generation + overrides. |
| `src/resume_agent/profile/build.py` | Orchestrate corpus pipeline; legacy migration. |
| `src/resume_agent/models/base.py` | `FactItem.source_ref`. |
| `src/resume_agent/models/profile.py` | `Skill.inferred/evidence_fact_ids/category`. |
| `src/resume_agent/services/match_gap.py` | Token universe + prune keep-set. |
| `src/resume_agent/tracking/match_gap.py` | Tri-state coverage. |
| `src/resume_agent/tailor/match_plan.py` | MATRIX prompt section + instructions. |
| `src/resume_agent/discovery/fit.py` | Matrix in fit input, adjacent partial credit. |
| `src/resume_agent/discovery/pipeline.py` | Criteria prompt: soft-skill capture. |
| `src/resume_agent/cli.py` | `profile add/remove/sources`; build report. |
| `src/resume_agent/api/schemas/*` + `contracts/` | Coverage tri-state projection. |
| `pyproject.toml` | `python-pptx`. |
