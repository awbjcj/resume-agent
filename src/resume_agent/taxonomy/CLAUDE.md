# Taxonomy developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/taxonomy/`.

- **An unresolved country silently drops the region too, so the country table
  is load-bearing.** `build_location` assigns `region` only when a country
  resolved (deliberate — see
  `docs/superpowers/specs/2026-07-20-international-location-region-design.md`),
  which meant a ~45-entry hand-written country list quietly truncated most of
  the world to a bare city: "Colombo, Western Province, Sri Lanka" reached the
  board as "Colombo". `taxonomy/countries.py` now carries the whole ISO 3166-1
  standard (official short names plus an ASCII-folded variant, so "Turkiye"
  resolves as typed) with `COUNTRY_ALIASES` for the colloquial names the
  standard lacks. Fourteen official names contain a comma ("Korea, Republic
  of") and are unreachable from `_parse_location`, which splits on commas
  first — that is what the alias half is for. Regenerate the table; do not
  hand-edit it.
- **17 ISO alpha-2 codes are also USPS state codes, and "Georgia" is both a
  country and a state.** Completing the country table therefore could not be
  done alone: it would have read "Atlanta, GA" as Gabon. `_trailing_part_is_country`
  confines the ambiguity to the two-part shape, where the US-state reading
  wins ("City, ST" is far more common than "City, CountryCode", and the
  country is inferred from the state anyway); three or more parts put the
  trailing token in an unambiguous country slot ("Toronto, ON, CA"). This also
  fixed a live bug in the other direction — "San Francisco, CA" was resolving
  to Canada.
- **A workplace-type suffix is stripped before the structural read.** Boards
  glue it onto the label ("Ann Arbor, MI - Hybrid", "Seattle, WA (Hybrid)"),
  which leaves the trailing part unresolvable as either a state or a country
  and — via the region rule above — collapses the value to a bare city.
  `_strip_workplace_suffix` removes it; nothing is lost, because the workplace
  type is captured separately as its own sidebar line and `raw` keeps the
  provider's original string. A value that is *only* a workplace tag
  ("Remote", "Remote - US") is left intact for the remote branch, which is why
  the strip requires a preceding locality.
- **Skill groups are a derived display axis.** `MatrixRow.group` comes from the
  active data root's `taxonomy/skill_groups.json` (token → slug, fixed 20-slug
  vocabulary in `taxonomy/vocabulary.py`). Profile builds classify only missing
  tokens with the cheap tier; failed batches remain absent and retry on the next
  build. Match-gap refreshes apply the saved map without an LLM, and
  `overrides.yaml`'s `group:` map wins over taxonomy. User re-categorizations
  from Settings > Skill groups live in `data/profile/group_corrections.json`,
  win over both overrides and taxonomy, and are replayed by
  `decorate_matrix_groups` on every matrix rebuild. The LLM classifier never
  reads or writes corrections, and `MatrixRow.group_source` records whether a
  correction, override, or taxonomy assigned the row. Groups never alter
  `facts.json` or the hard/soft/domain categories used by fact-lock; unassigned
  rows render as Other.
- **Skill taxonomy is three-level and correction-locked.** The fixed 20-slug category
  vocabulary lives in `taxonomy/vocabulary.py` (shared by the profile matrix group axis
  and the constellation); LLM-clustered domains parent to exactly one category with a
  deterministic per-category cap (`Settings.domains_per_category_cap`, default 12)
  enforced in `classification._project_domains`, never trusted to the model. User edits
  (move/rename/merge/add/remove/alias) write intent entries to
  `data/taxonomy/taxonomy_corrections.json` via `services/taxonomy.py` and are replayed
  last by `apply_taxonomy_corrections` on every load — corrections beat LLM output;
  dangling references are inert. Legacy cluster files load aliases-only (themes ignored),
  so the first refresh reclassifies once; legacy `theme`-kind suggestions are purged.
- **Retrieval narrows the prompt; it never forbids an answer unless it is
  semantic.** `taxonomy/embeddings.py` only reduces what the classifier is
  shown, but `_project_domains` also used `allowed_domain_ids` as a hard veto on
  existing-domain reuse. That was safe only while retrieval worked — and it
  never had. `cached_embeddings` ran ~50 sequential provider calls for a real
  map (12,752 descriptors ÷ 256) and wrote the cache **only after all of them
  succeeded**, so one rate-limited shard discarded every sibling and the next
  run repeated the loss: no tenant ever had a `skill_embeddings.json`, and every
  run silently used the lexical fallback. That fallback scored symmetric Jaccard
  over the whole descriptor, whose union denominator grows with member count, so
  the _smallest_ domain won — measured on a live 155-domain taxonomy, one domain
  ranked first for **42 of 60** consecutive queries and the top-8 union reached
  only **53 of 155** domains, making two-thirds of the taxonomy unreachable per
  batch. Now: `embed_descriptors` persists every shard that lands and degrades
  to `partial` instead of raising; `_LexicalCorpus` scores IDF-weighted query
  coverage against a domain's identity (label + human category label) with a
  discounted member-overlap term; and `enforce_candidates` gates the veto on
  `mode == "embedding"`. Cosine and lexical scores are never ranked against each
  other — an embedded query competes only among embedded candidates.
- **A regroup is two passes, and the second one differs.** `refresh_clusters`
  sends only tokens with no recorded `grouping_status` to the first pass;
  anything that failed before skips straight to escalation, because a replay of
  the same batch, prompt and gates is exactly why clicking Regroup twice used to
  change nothing. Escalation uses the premium themer
  (`build_escalation_themer_agent`), quarter-size batches, the whole taxonomy
  (`candidate_context=None`, so no allowlist), and `min_new_domain_members=1` —
  the first pass still requires 2, so a genuinely novel lone skill is placed by
  escalation rather than being permanently unassignable. It is bounded by
  `Settings.taxonomy_escalation_max_skills` (300); the remainder escalates next
  run, so progress is monotonic. `failedCanonicalTokens`/`failedDomainTokens`
  count **distinct tokens** across both passes, never token-attempts.
- **Every demanded skill ends a refresh with a home, except after an outage.**
  `_apply_placement_floor` files whatever survives both passes into
  `general-<category>` (`Settings.taxonomy_placement_floor`), preferring the
  category the model stated in a group it declined to certify — `_project_domains`
  keeps that intent in `fallback_categories` precisely so the floor honours a
  real judgment instead of guessing `other`. A token whose model **call** failed
  is excluded: there is no judgment to honour, only an outage, and filing a
  skill because a request timed out would make a transient error permanent.
  `ClassificationFailure.kind` (`"call"` / `"output"`) carries that distinction,
  because the message is the raised exception's own text and the old
  `"model call failed" in message` check therefore never matched a real outage.
- **`not_skills` is a terminal disposition, and it is reversible.** The domain
  classifier may return tokens that name no skill (`8+ years of machine learning
experience`); they land in `TaxonomyState.retired_skills`, are subtracted from
  `demanded` on every later run, and are never re-sent. Without it the backlog
  re-bought the same verdict forever. They stay visible via
  `MatchGapOut.retiredSkills` and return through
  `POST /api/match-gap/restore-skills` — deliberately synchronous, since it only
  edits the state file.
- **"Reorganize domains" cannot assign a skill.** `maintain_taxonomy` merges,
  splits, renames and reparents _domains_, and gates on not increasing the
  unassigned count; nothing in it lowers that count. The button is named for
  what it does so it is not mistaken for a second Regroup.
