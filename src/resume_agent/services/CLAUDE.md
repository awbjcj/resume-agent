# Services layer developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/services/`.

- **`ConfigStore.put` writes over a file's keys; it never replaces the file.**
  A Doc deliberately does not declare every key its YAML may hold — rendering
  keeps `template_path`/`output_dir` as runtime-only CLI fields (see
  `render/CLAUDE.md`) and `profile_sources.yaml` keeps the wizard's
  `resume_path` — and the original wholesale rewrite **deleted** each of them
  the first time an unrelated field on that page was saved. So a DTO field
  missing from a Doc means "not editable here", never "safe to destroy". Three
  consequences: the merge is **shallow**, because a key the Doc *does* own must
  be replaced outright or removing a list item would resurrect it;
  `_SUPERSEDED_KEYS` is the one exception, dropping a deprecated spelling whose
  replacement now owns the meaning (`match_plan_enabled`, which `ReviewConfig`
  *rejects* when it disagrees with `evidence_portfolio_enabled`, so preserving
  it would turn a UI toggle into an unloadable config); and adding a field to a
  Doc is now purely a question of whether users should edit it.
  `tests/test_config_store_roundtrip.py` asserts the property against the
  shipped `.example` files rather than comparing Doc fields to domain fields,
  because those two legitimately diverge and the failure mode that matters is
  data loss.
- **`ReviewConfigDoc.length_budget` is not nullable, because
  `ReviewConfig.length_budget` is not.** The settings page used to offer an
  "Enforce a length budget" switch whose off position wrote `length_budget:
null`; the domain model rejects that outright, so turning the budget off
  broke every subsequent tailor run at config load. The switch is gone and the
  budget is always present. A `before` validator still coerces `None` to
  defaults on read, because files written by the old switch exist and a
  settings page that 500s cannot be used to repair itself.
- **The customizable settings surface is declared once.** `settings_sections.py`
  holds `SETTINGS_SECTIONS`: twelve rows naming each transferable, resettable
  unit and the canonical relative paths it owns (`config/connectors.yaml`,
  `data/profile/overrides.yaml`). It is an **allowlist** — it spans the
  workspace root alongside `secrets.env`, `gmail_token.json`,
  `resume_agent.db`, and `config/gmail_credentials.json`, so a file not named
  there can neither leave a workspace in a settings bundle nor enter one from
  an imported bundle. `services/settings_bundle.py` exports and imports that
  set as a tar.gz (`GET/POST /api/settings/bundle`), replacing the sections a
  bundle names and leaving the rest untouched — a bundle can add or replace
  settings but never clear them. Reset (`POST
/api/settings/sections/{id}/reset`) copies the shipped `.example` when one
  exists and deletes the file otherwise, which is the same rule
  `provision_workspace` uses to seed a fresh workspace. Import validation uses
  the artifacts' **models** but not their read-time loaders:
  `load_group_corrections` and `load_taxonomy_corrections` return an empty
  ledger on corruption, which is right for reading and catastrophic for
  importing.
