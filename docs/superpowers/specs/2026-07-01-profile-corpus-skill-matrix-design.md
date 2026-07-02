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
| Soft skills | **Category-tagged, shown via literal evidence.** No new `JobCriteria` field; JD-criteria prompt strengthened; match-plan selects demonstrating bullets. It must not add an inferred soft-skill label to the skills section or turn it into an unsupported summary claim. |
| Surface | **CLI first** (`profile add/remove/sources/build`); web Profile page is a phase-2 spec. |
| Curation | **Automatic + overrides file** (`data/profile/overrides.yaml`), applied through one effective canonical map shared by matrix generation and every matching consumer; no mandatory review gate. |
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
  `{id, filename, sha256, added_at, primary: bool}`. A non-empty manifest has
  exactly one `primary` (the canonical resume; wins scalar conflicts in merge).
  The first added source is promoted automatically. Removing the primary
  promotes the oldest remaining source deterministically; setting a new primary
  demotes the old one in the same manifest write. A malformed manifest is a
  hard error, not an empty corpus, so corruption cannot silently orphan sources.
- Atomic writes (same tmp-then-replace pattern as `save_cluster_map`).
- Stored source copies are content-tracked inputs. Before every cache decision, the
  builder hashes the stored bytes and compares that hash with the manifest. A
  mismatch is reported and re-extracted using the observed hash (with the
  manifest repaired atomically) rather than accepting a stale fragment.

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
- Per-doc failures do not normally abort the build: a failed fragment keeps its
  previous cached version (if any) and is reported. A primary source with no
  usable current or cached fragment aborts the build; silently letting a
  secondary document become the scalar-conflict winner would violate the
  primary invariant.

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

An inferred skill id also includes its sorted, deduplicated evidence ids. If
the evidence changes, the inferred fact is a different fact; an old
`ResumeVersion` must not appear to retain provenance while its backing evidence
silently changes.

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

- **Entity keys.** Experience: same normalized company **and** either (a) same
  normalized title with overlapping/unknown date ranges or (b) title-token
  overlap >= 0.5 with overlapping date ranges. Two known, disjoint ranges never
  merge, even when title and company repeat. Project: `_norm(name)` (as today). Education:
  `normalize(institution)` + degree. Certification/publication/award: name.
- **Union.** Bullets, `tech`, honors, highlights union across fragments; a
  cheap-tier LLM pass flags near-duplicate bullet pairs (reworded same
  accomplishment) and the shorter one is dropped. LLM failure → keep both
  (safe, verbose).
- **Scalar conflicts.** Primary doc wins; non-primary fills nulls only. This is
  applied to contact fields, summary, experience (including `current`), project,
  education, certification, publication, award, language, and volunteer
  scalars. Collection fields are unioned. Duplicate entities are merged field
  by field rather than dropping the secondary record wholesale.
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
  "facts_sha256": "...",
  "canonical_map_sha256": "...",
  "rows": [
    {
      "key": "kubernetes",            // canonical token (shared alias space)
      "display": "Kubernetes",
      "aliases": ["k8s"],
      "category": "hard",             // hard | soft | domain
      "inferred": false,             // true only when every contributing skill is inferred
      "evidence_fact_ids": ["..."],   // skills: own id + evidence ids; plus bullets/tech mentioning it
      "strength": 7.2,                // evidence count × recency decay
      "last_used": "2026-03"
    }
  ]
}
```

- `strength = Σ evidence-fact weight × recency`, where recency decays by the
  owning experience/project `end` date (current role = 1.0). Exact curve is an
  implementation detail; must be deterministic. One occurrence is counted
  once (a matching bullet and its owner are not two independent pieces of
  evidence). An undated project is `last_used=null`, not `current`. Explicit
  `evidence_fact_ids` are resolved back to their owners for recency.
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
  `collect_target_skill_tokens(session) ∪ profile_skill_tokens(facts) ∪
  override_tokens(overrides)`, and **the prune keep-set includes all three** —
  otherwise profile aliases or forced/forbidden override heads would be
  garbage-collected on every refresh.
- Tiers, given canonical map `A` and theme map `T`:
  - **covered**: `A(jd_token) ∈ A(profile_tokens)`
  - **adjacent**: not covered and `T(A(jd_token))` equals the theme of some
    covered profile token
  - **gap**: neither
- One `effective_cluster_map(cluster_map, overrides)` function is used by matrix
  generation, match-gap, fit, and tailoring. `forbid_alias` is applied after
  forced aliases and wins on conflict; it splits both tokens into distinct
  self-canonicals even when they previously shared a third canonical.

## 11. Consumers

- **`tailor/match_plan.py`** — `compose_match_plan_input` gains a deterministic
  `SKILL MATCH CONTEXT` section (only rows relevant to the JD, each annotated
  with the JD requirement and `covered`/`adjacent`; include evidence ids and
  strengths). New instructions: prefer high-strength evidence;
  for **adjacent** requirements, select transferable evidence and note the
  framing, never claim the JD token; for **soft** requirements, satisfy by
  selecting literal bullets that demonstrate the trait. Summary wording remains
  subject to the ordinary fact-lock and may not be justified by an inferred
  soft-skill pointer.
- **`tracking/match_gap.py`** — `SkillNode.covered: bool` becomes
  `coverage: Literal["covered", "adjacent", "gap"]` (API schema + dashboard
  follow; `covered` kept as a derived bool during transition). Gap report
  excludes covered, keeps adjacent flagged separately.
- **`discovery/fit.py`** — `compose_fit_input` includes the same deterministic,
  per-job skill-match context instead of asking the LLM to guess adjacency from
  an unannotated matrix. Instructions award partial credit only to rows marked
  adjacent.
  The "never infer an unlisted skill" instruction stays — the bound matrix is
  the candidate-skill source behind that context.
- **Fact-lock gate + reviewer (`review.yaml` path)** — the deterministic gate
  rejects an inferred skill unless it is cited from the skills section, has
  `category="hard"`, has at least one evidence id, and every evidence id
  resolves to a non-inferred fact. The reviewer then checks whether that
  evidence semantically demonstrates the skill. Inferred ids are never valid
  provenance for bullets, experience/project records, or summary claims.

`facts.json`, the effective canonical map, and `matrix.json` are one artifact
set. The matrix stores hashes of both the canonical serialized facts and the
effective ClusterMap used to build it. Consumers derive the matrix path from the
selected facts path and ignore/rebuild a matrix when either hash differs; a
custom `--facts` path must never consume the default profile's matrix. A
successful cluster refresh regenerates the matrix so newly learned canonical
heads cannot leave matrix keys stale.

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
- Deterministic tests: manifest round-trip + corruption failure + primary promotion;
  observed-byte hash cache skip/invalidate;
  entity-key merge incl. conflict report; stable-id preservation across
  rebuild; inference id-validation drop; matrix strength determinism;
  overrides (ban/alias/forbid/category); facts/canonical-map matrix hash mismatch;
  tri-state coverage incl. the prune keep-set regression (profile and override
  aliases survive `refresh_clusters`); deterministic rejection of invalid inferred
  provenance.
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
| `src/resume_agent/profile/store.py` | Atomic facts persistence for the bound facts/matrix artifact set. |
| `src/resume_agent/models/base.py` | `FactItem.source_ref`. |
| `src/resume_agent/models/profile.py` | `Skill.inferred/evidence_fact_ids/category`. |
| `src/resume_agent/services/match_gap.py` | Token universe + prune keep-set. |
| `src/resume_agent/tracking/match_gap.py` | Tri-state coverage. |
| `src/resume_agent/tailor/match_plan.py` | MATRIX prompt section + instructions. |
| `src/resume_agent/discovery/fit.py` | Matrix in fit input, adjacent partial credit. |
| `src/resume_agent/discovery/pipeline.py` | Criteria prompt: soft-skill capture. |
| `src/resume_agent/cli.py` | `profile add/remove/sources`; build report. |
| `src/resume_agent/api/schemas/*` + `contracts/` | Coverage tri-state projection. |
| `web/src/features/match-gap/*` | Render/filter adjacent separately from covered and true gaps. |
| `pyproject.toml` | `python-pptx`. |
| `uv.lock` | Lock `python-pptx`. |
