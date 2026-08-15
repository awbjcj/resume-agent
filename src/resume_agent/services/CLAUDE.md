# Services layer developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/services/`.

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
