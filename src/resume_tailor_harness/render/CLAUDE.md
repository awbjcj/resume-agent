# Rendering developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_tailor_harness/render/`.

- **Rendering is template-id based.** The web contract is `{template,
fitOnePage}`; legacy `template_path` and `output_dir` remain runtime-only CLI
  fields. Bundled templates are anchored in `render/templates.py`; validated
  custom `.typ` uploads live under the tenant `config/templates/` directory.
  Custom stems are path-safe, Typst compilation is root-pinned, and uploads
  replace live templates only after a successful validation compile. Deleting
  an active custom template falls back to `classic`; missing templates never
  silently fall back during rendering.
