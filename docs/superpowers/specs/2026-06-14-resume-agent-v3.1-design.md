# Resume Agent v3.1 — Broadsheet Dashboard + Setup Wizard — Design Spec

- **Date:** 2026-06-14
- **Status:** Approved (design) — ready for implementation planning
- **Scope of this document:** Full v3.1 design. Builds on the v1 (`2026-06-08-resume-agent-design.md`), v2 (`2026-06-11-resume-agent-v2-connectors-design.md`), and v3 (`2026-06-13-resume-agent-v3-design.md`) specs.
- **Successor planning:** one spec → two independent component plans (mirrors the v1/v2/v3 spec→multi-plan pattern).

---

## 1. Overview

v1–v3 built and sharpened the fact-locked pipeline. v3.1 is a **presentation + onboarding** release: it does not change a single pipeline behavior. It does two independent things:

1. **Broadsheet dashboard (Pillar A):** retire the centered, 1120px-wide "Midnight Atelier" dark theme for a **fresh light "Broadsheet" visual identity** with an **adaptive multi-column layout** that fills a 32″ 4K display at high density. Split the 527-line `dashboard/app.py` god-file into a pure design-system module + thin page bodies.
2. **Setup wizard (Pillar B):** replace the manual first-run ritual (hand-edit `.env`, hand-copy and edit six YAML files) with a **standalone Textual TUI** — `resume-agent setup` — that takes a new user from zero → configured → validated → ready, writing all config atomically.

### Defining property

v3.1 changes **no pipeline logic, no data model, and no agent behavior**. Zero database migrations. Pillar A is layout + CSS + a module split that preserves every existing pure helper's behavior. Pillar B is net-new I/O *into* local config files only (`.env`, `config/*.yaml`) — it never touches `facts.json`, the database, or any outward-facing surface.

### Non-goals (unchanged from v1–v3)

Not a product, not multi-tenant, not an auto-submitter. The wizard configures; it never submits, never edits ground-truth `facts.json` (it may *launch* `profile build` as a subprocess, which itself respects the existing no-clobber rule), and adds no new scrapers or network writes. No new dashboard **features** (no new pages, no chart-library swap, no new metrics) — Pillar A is identity + layout only.

---

## 2. Decisions (resolved during brainstorming + grilling)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Frontend strategy | **Hybrid.** Keep/improve the **Streamlit** dashboard; build the setup wizard as a **separate standalone surface**. No React rewrite. |
| 2 | Wizard host technology | **Textual TUI** (in-terminal), launched by `resume-agent setup`. Not a local web page; not a Streamlit page. |
| 3 | Wizard scope | **Full zero→ready:** secrets→`.env`, config YAML generation, live validation/preflight, optional `profile build` + handoff. |
| 4 | Dashboard 4K layout | **Adaptive multi-column** (responsive CSS grid, ~2400px max-width, **4 columns on 4K**), not full-bleed command-center, not a merely-widened single column. |
| 5 | Dashboard visual identity | **Fresh "Broadsheet" identity** (light, editorial, dense). The Midnight Atelier dark theme is **retired**, not evolved. |
| 6 | Architecture pattern | **Pure cores + thin shells**, both pillars. Testable logic lives in pure functions; Streamlit/Textual are thin presentation layers. |
| 7 | Wizard write timing | **Atomic-at-end.** No disk writes until a final confirm screen; per-file diffs shown first; temp-file + `os.replace`. |
| 8 | Review/Render config | **Auto-generated from `.example` defaults** — no dedicated wizard screen. |
| 9 | Generated-YAML form | **Clean, loader-validated YAML with a provenance header.** Inline `.example` annotations are **not** preserved (the wizard *is* the documentation). No `ruamel.yaml` dependency. |
| 10 | Secret freshness model | Pre-write validation reads secrets **explicitly from `WizardState`** (never the `@lru_cache` singleton); post-write `profile build` runs as a **subprocess** that reads the just-written `.env`. |
| 11 | Secrets surface | **6 prompted** (Anthropic required; GitHub, Adzuna×2, LinkedIn×2 optional), **4 under "Advanced"** (`db_url`, 3 model tiers), **2 omitted from UI** (`openai_api_key` — dead config; `linkedin_user_data_dir`). `merge_env` still preserves omitted keys if present. |
| 12 | Greenhouse board input | **Single multiline field** (`token` or `token, Company` per line), parsed by a pure `parse_greenhouse_boards()`. No dynamic row-repeater widget. |
| 13 | Dashboard type system | **3 families:** Newsreader (display) · IBM Plex Mono (figures/labels/status) · IBM Plex Sans (all body/table text). Spectral serif body **dropped** for legibility at density. |
| 14 | Preflight behavior | **Detect-and-instruct**, never silent auto-install. `textual` becomes a **hard dependency**. One opt-in exception: a "Install browser" button on the LinkedIn step shells out to `playwright install chromium`. |
| 15 | Packaging | **One spec → two independent component plans** (Broadsheet dashboard; setup wizard). No dependency edge; either order; each independently green. |

---

## 3. Cross-cutting principles (inherited)

- **Fact-Lock** (§3.1 v1) — untouched. v3.1 adds no claim-bearing surface. The wizard may launch `profile build`, which keeps its no-clobber-without-`--refresh` rule.
- **Human control / authoritative `facts.json`** (§5.1 v1) — preserved. The wizard writes only `.env` and `config/*.yaml`; `facts.json` is never written by the wizard itself.
- **Offline, pure test suite** (README) — preserved. Pure cores are tested with no network/API/key; injected clients fake all external calls; Streamlit pages and Textual screens get import/smoke tests only.
- **No schema growth** — zero migrations, no new tables/columns. (Inherited from v3's "smallest-surface" discipline.)
- **Resumability** — neither pillar adds pipeline stages or statuses.

---

## 4. Pillar A — Broadsheet dashboard

### 4.1 Module split (pure cores + thin shells)

```
dashboard/
  app.py     # THIN: st.set_page_config, sidebar nav, page routing only
  ui.py      # NEW design system: THEME_CSS, masthead/nameplate, KPI strip,
             #   card grid, column_count(), status_badge, fit_block,
             #   empty_state, table styling helpers
  pages.py   # NEW: render_shortlist/pipeline/analytics/match_gap,
             #   thin compositions over ui.py
```

Every existing **pure** helper moves verbatim (behavior unchanged): `status_badge`, `fit_block`, `analytics_table_rows`, `match_gap_table_rows` → `ui.py`/`pages.py`. Existing tests (`test_dashboard_app.py`, `test_dashboard_analytics.py`, `test_dashboard_match_gap.py`) follow with **import-path updates only** — no behavioral change expected.

### 4.2 Visual identity — "The Broadsheet"

Light, editorial, dense. A deliberate, full pivot from the dark Atelier.

- **Palette:** canvas `#f4f1ea` (warm paper) · ink `#16130f` · muted `#6c6253` · single accent **oxblood `#8c2f1f`** (fit figures, hairline rules, the one primary CTA). Status tokens keep semantic hues (emerald/amber/rose/sky) but re-tuned for contrast on paper.
- **Type (3 families, all Google Fonts):**
  - **Newsreader** — display serif: nameplate masthead, page headlines, card titles. Carries the identity.
  - **IBM Plex Mono** — figures (fit scores, counts), kickers, small-caps status tags, rule labels.
  - **IBM Plex Sans** — all running/body/table text (JD text, rationale, critiques, table cells). Chosen over serif body for legibility at density; already loaded today.
- **Motifs:** broadsheet nameplate, **hairline rules** as section dividers, right-aligned figures, oxblood reserved and sparing.
- `.streamlit/config.toml` flips `base="light"` with the paper palette (`backgroundColor=#f4f1ea`, `textColor=#16130f`, `primaryColor=#8c2f1f`, secondary paper tint).

### 4.3 Adaptive 4K layout

- Container `max-width` 1120 → **~2400px**; gutters via `clamp()`.
- Card lists (Shortlist, Pipeline) rendered inside a CSS grid: `display:grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: clamp(...)`. The browser reflows: ~1 col on a laptop, ~2 at 1440px, **~4 on a 32″ 4K panel** — no Python round-trip.
- `column_count(width, card_min=360, max_cols=4) -> int` is a **pure, unit-tested** function used for the few server-side splits (`st.columns` for the KPI strip and the fit-meter/body row).
- Type/metric sizes use `clamp()` so they read at 150%-scaled 4K without ballooning on a laptop.
- KPI strip becomes a full-width row of 3–5 figure cards.
- Card density raised: company · role · location · fit · sponsorship · stage on one entry (today's single vertical stack is the biggest 4K-emptiness loss).

### 4.4 Stock-element theming

Fix the few stock Streamlit elements that currently break the theme on a light canvas: `st.table` (analytics, match-gap), `st.selectbox`, `st.expander`, `st.download_button` — restyled in `THEME_CSS` to the Broadsheet palette.

### 4.5 Explicitly out of scope (Pillar A)

No new pages, no new metrics, no chart library, no behavior changes. Analytics stays `st.table`. Layout + identity + module split only.

---

## 5. Pillar B — Setup wizard (`resume-agent setup`)

### 5.1 Package layout (pure cores + thin shell)

```
setup/
  __init__.py
  state.py       # WizardState dataclass — single source the screens bind to
  env_writer.py  # merge_env(existing, updates) -> dict ; write_env(path, data)
  yaml_gen.py    # build_profile_sources/build_search/build_connectors/
                 #   build_review/build_render(state) -> str  (pure)
  preflight.py   # structured pass/fail checks (env faked in tests)
  validate.py    # anthropic_ping(api_key) ; connector_smoke(settings)  (injected clients)
  writer.py      # atomic_write_all(state) — temp-file + os.replace, per-file
  app.py         # THIN Textual App: one Screen per step → calls into cores
```

`cli.py` gains a `setup` command (Typer) that constructs and `.run()`s the Textual `App`. `pyproject.toml` adds `textual` as a hard dependency.

### 5.2 Screen flow

Left progress rail · Back/Next · **nothing written until the confirm screen**.

| # | Screen | Stages into state → file | Live check (pre-write, in-memory secrets) |
|---|--------|--------------------------|-------------------------------------------|
| 0 | Welcome + preflight | — | Python ≥3.13, write-perms on `config/`+`.env`, `*.example` present, chromium (only if LinkedIn later enabled) |
| 1 | Secrets | `.env` (merge) | "Test key" → `anthropic_ping(typed_key)` |
| 2 | Profile sources | `profile_sources.yaml` | resume path exists? |
| 3 | Search & hard filters | `search.yaml` | typed-field validation |
| 4 | Connectors | `connectors.yaml` | `connector_smoke()` for enabled boards; warn if Adzuna enabled but keys blank |
| 5 | *(none — review/render auto-generated)* | `review.yaml`, `render.yaml` from `.example` | files parse |
| 6 | Confirm + write | **all files, atomic** | per-file diff shown; then `atomic_write_all` |
| 7 | Build profile? (optional) | runs `resume-agent profile build` **subprocess** | streams output; shows fact count |
| 8 | Handoff | — | recap pass/fail + exact next commands (`discover` → `dashboard`); optional Gmail-OAuth link |

### 5.3 Secrets model

- Prompted (6): `anthropic_api_key` (required, masked, testable), `github_token`, `adzuna_app_id`, `adzuna_app_key`, `linkedin_email`, `linkedin_password` (all optional/masked where secret).
- Advanced collapsible (4): `db_url`, `cheap_model`, `mid_model`, `premium_model` — pre-filled with current defaults.
- Omitted from UI (2): `openai_api_key` (verified dead config — declared at `config.py:17`, read nowhere in `src/`), `linkedin_user_data_dir` (default `.linkedin_profile`).
- `merge_env(existing, updates)` is **pure**: overwrites managed keys, **preserves every unmanaged key** (including the two omitted above and any custom vars), never corrupts quoting. `write_env` wraps it with masking handled in the TUI only — full secret values touch `.env` alone.

### 5.4 Config generation

- One pure `build_*(state) -> str` per file. Output is **clean YAML** (PyYAML `safe_dump`) with a one-line provenance header: `# Generated by 'resume-agent setup' on <date> — see README for field docs`.
- **Greenhouse boards:** `parse_greenhouse_boards(text) -> list[dict]` — one board per line, `token` or `token, Company`; trims, splits on first comma, defaults company to title-cased token, skips blanks. Unit-tested independent of the TUI.
- **Validation contract (the key seam):** every `build_*` test asserts the rendered YAML both (a) parses and (b) **round-trips through the real loader** (`load_search_config`, `load_connectors_config`, `load_render_config`, `load_review_config`, `load_yaml` for profile sources) into the expected typed object. The wizard's output cannot be config the app then rejects.

### 5.5 Atomic write protocol

1. All answers accumulate in `WizardState` — **zero disk writes** through screens 0–5.
2. Confirm screen (6) renders a **per-file diff**: new file / changed keys / unchanged.
3. `atomic_write_all`: for each file, write to a temp sibling then `os.replace()` (atomic on POSIX *and* Windows). Each file is independently atomic; on partial failure, already-written files stay valid and the handoff reports exactly which succeeded — no truncated/corrupt config is ever produced.

### 5.6 Re-run safety

If `.env`/configs already exist, screens **pre-fill from them** (parse existing `.env` and YAML via the real loaders) and edit in place. The diff at confirm makes every change explicit. The wizard never silently overwrites.

### 5.7 Process & freshness model

- **Pre-write live checks** never use `get_settings()` (it's `@lru_cache` and the `.env` may be empty/absent at check time). `anthropic_ping` takes the typed key directly; `connector_smoke` builds a one-off `Settings(**state.secrets)`.
- **Post-write `profile build`** (screen 7) runs as a **subprocess** (`resume-agent profile build`), mirroring how `dashboard_cmd` shells out to `streamlit` (`cli.py:365`). A fresh process reads the just-written `.env` — no stale-cache hazard.

---

## 6. Testing strategy

**Ring 1 — pure logic (bulk; offline, no TUI/Streamlit):**
`merge_env` (preserve/overwrite/quoting); each `build_*` (parses **and** round-trips through the real loader); `parse_greenhouse_boards`; `preflight` checks (monkeypatch `shutil.which`, `sys.version_info`, temp dirs); `column_count` and the moved dashboard helpers (`status_badge`, `fit_block`, `analytics_table_rows`, `match_gap_table_rows`).

**Ring 2 — injected clients (offline):**
`anthropic_ping(client)` and `connector_smoke(...)` take fake clients returning success/auth-error/network-error → assert the right `CheckResult`. No network, no key.

**Ring 3 — thin shells (smoke only):**
Wizard: 2–3 Textual `App.run_test()` pilot tests (boots, advances screens, confirm screen calls a mocked `atomic_write_all` with the assembled state) + one `atomic_write_all` test simulating mid-write failure (no `.tmp` litter, accurate report). Dashboard: import `pages.py`, call page renderers with an in-memory SQLite session (as `test_dashboard_app.py` does today), assert no exception + key markup present.

**Out of scope:** pixel rendering, Textual/Streamlit internals, live API/network.

**Tooling:** `pytest` + `ruff` (existing). New dep: `textual` (+ its pytest pilot harness). Streamlit, PyYAML already present.

---

## 7. Files touched

**Pillar A (dashboard):** `dashboard/app.py` (slimmed), `dashboard/ui.py` (new), `dashboard/pages.py` (new), `.streamlit/config.toml`, dashboard tests (import-path updates + `column_count` tests).

**Pillar B (wizard):** `setup/*` (new package), `cli.py` (`setup` command), `pyproject.toml` (`textual` dep), `README.md` (one line: after `uv sync`, run `resume-agent setup`), new `tests/test_setup_*`.

No overlap between the two sets beyond the repo root → two independent plans.

---

## 8. Successor plans

1. `docs/superpowers/plans/2026-06-14-resume-agent-v3.1-broadsheet-dashboard.md`
2. `docs/superpowers/plans/2026-06-14-resume-agent-v3.1-setup-wizard.md`

No dependency edge; either order; each independently green. If sequenced, wizard-first delivers the larger new-user jump (zero→ready).
