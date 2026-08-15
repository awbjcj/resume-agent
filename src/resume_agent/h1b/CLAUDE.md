# H-1B sponsorship developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/h1b/`.

- **H-1B evidence is per company, and the cache is the only display source.**
  `h1b_company_evidence` (keyed by `normalize_company`, TTL
  `Settings.h1b_cache_ttl_days`) is read through the single batched seam
  `h1b/cache.py::load_company_evidence` — one query per request, the map passed
  down to row projections rather than looked up per row. The job detail and all
  three board projections read it; `JobAnalysisMeta.h1b_evidence_snapshot` is no
  longer written or read (the field remains only so old rows deserialize, and
  `h1b_evidence_id` remains as a provenance pointer). **Expired rows still
  render**, labelled stale via `H1BSponsorshipOut.stale` — historical filings do
  not rot, and nothing auto-refreshes: an LLM call happens only on an explicit
  manual check or a discovery run. Evidence carries a per-quarter `periods`
  breakdown whose top-level **count** rollup is **derived by the model validator,
  never trusted from the agent**, so count totals can never contradict the parts
  shown beneath them; report-level wage summaries remain provider aggregates.
  `periods: []` is valid and degrades to the flat pre-quarter view.
  Discovery researches every surviving job's company (gated on
  `config.sponsorship_required`, bounded by
  `Settings.h1b_enrich_max_companies_per_run`), but `run_h1b_enrichment` still
  returns **only** `silent` jobs to the fit scorer — a JD that explicitly refuses
  sponsorship must not have its score lifted by filing history. Fresh cache hits
  reach that map without an agent call; expired entries deferred by the cap are
  display-only until refreshed. `h1b_evidence_id` is updated for every covered
  in-scope job as provenance, while no job writes a snapshot.
