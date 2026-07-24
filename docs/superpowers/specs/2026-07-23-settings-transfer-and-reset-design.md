# Settings Transfer and Reset — Design

**Date:** 2026-07-23
**Status:** Approved, awaiting implementation plan

## Problem

Two gaps, one root cause.

**Transfer.** The only way to move customizations between installs or users is
`GET /api/account/export` + `POST /api/account/import` — a whole-workspace
tar.gz. It already contains every setting (`provision_workspace` places
`config/` *inside* the workspace root, so `export_data_root` sweeps it up), but
it is all-or-nothing: import replaces the database, the profile corpus, and
`secrets.env` along with the settings, requires multi-user mode, and demands a
typed `REPLACE`. There is no way to carry just "my sources and my prompt
guidance" to another machine.

**Defaults.** Nothing can be restored to its default. Defaults exist only as
`config/*.example` files copied once by `provision_workspace` at provisioning
time. After the first edit, the original is unrecoverable through the product.

The root cause is that *the set of customizable settings* is not named anywhere.
It is scattered across five enumerations that no single caller can see:

| Location | What it enumerates |
| --- | --- |
| `services/config_store.py::_FILES` | six YAML/markdown domains |
| `tenancy/paths.py` | `CONNECTORS_PATH`, `SEARCH_PATH`, `REVIEW_PATH`, `REVIEW_DEEP_PATH`, `AGENT_GUIDANCE_PATH` |
| `render/templates.py::CUSTOM_TEMPLATES_DIR` | `config/templates` |
| `prompts/guidance.py` | its own locked write path for `agent_guidance.yaml` |
| `tenancy/workspace.py::provision_workspace` | the `config/*.example` glob |

"What goes in a settings bundle" and "what can be reset" are the same list read
from two directions. Declaring it once is the spine of this design.

## Goals

- A settings-only bundle that exports and imports **just** customizations —
  no jobs, no database, no profile corpus, no credentials.
- Section-level replace on import, bundle-level merge: sections absent from a
  bundle are left untouched.
- A reset-to-default control for every customizable section.

## Non-goals

- **Skill and taxonomy correction ledgers stay out of scope.**
  `data/profile/overrides.yaml`, `data/profile/group_corrections.json`, and
  `data/taxonomy/taxonomy_corrections.json` are hand-authored user intent, but
  they live under `data/`, not `config/`, and were explicitly excluded. Keeping
  the bundle boundary exactly "the workspace `config/` directory" is what makes
  the allowlist auditable at a glance. They remain covered by the existing
  whole-workspace archive.
- Deep-merging within a section (unioning two company lists, reconciling two
  reviewer rosters). Section-level replace only.
- Any change to the existing whole-workspace archive. It stays the full
  backup/restore tool.
- Transferring credentials. `secrets.env`, `gmail_token.json`, and
  `config/gmail_credentials.json` are never exported and never honored on
  import.

## Architecture

### The section registry

New module `src/resume_agent/settings_sections.py` — the single enumeration.

```python
@dataclass(frozen=True)
class SettingsSection:
    id: str                   # stable wire id
    label: str                # UI label
    files: tuple[str, ...]    # workspace-config-relative; may glob

SETTINGS_SECTIONS: tuple[SettingsSection, ...] = (...)
```

| id | label | files (relative to workspace `config/`) | default when reset |
| --- | --- | --- | --- |
| `sources` | Company sources | `connectors.yaml` | shipped `.example` |
| `search` | Search | `search.yaml` | shipped `.example` |
| `review` | Review panel | `review.yaml`, `review_deep.yaml` | shipped `.example`s |
| `agent_guidance` | Agent prompts | `agent_guidance.yaml` | *deleted* → no guidance |
| `style_guide` | Style guide | `style_guide.md` | shipped `.example` |
| `render` | Rendering | `render.yaml` | shipped `.example` |
| `templates` | Custom resume templates | `templates/*.typ` | *cleared* → bundled only |
| `prune` | Pruning | `prune.yaml` | shipped `.example` |
| `profile_sources` | Profile sources | `profile_sources.yaml` | shipped `.example` |

This table is an **allowlist**, not a denylist, and that distinction is
load-bearing: `gmail/auth.py` puts `CREDENTIALS_PATH =
"config/gmail_credentials.json"` — an OAuth client secret — in the very
directory being bundled. A denylist over `config/` would ship it the moment
someone adds a file nobody remembered to exclude. Allowlists fail closed.

`provision_workspace`'s `*.example` glob becomes a reader of this table, which
is what makes "reset a section" and "provision that section fresh" literally the
same operation.

`config_store.py::_FILES` deliberately stays as it is. ConfigStore domains and
settings sections are different granularities — the `review` *section* owns two
files (`review.yaml`, `review_deep.yaml`) while the `review` *domain* owns one —
so forcing one to derive from the other would need a "primary file" concept that
earns nothing. The `tenancy/paths.py` constants likewise stay: they are named
strings consumed by leaf code, not a competing list.

A section is **customized** when any file it owns differs from that file's
shipped `.example`, or — for sections with no `.example` (`agent_guidance`,
`templates`) — when the file exists at all, or the directory is non-empty.

### Reset is policy-free

`provision_workspace` already defines "fresh" as *copy every `config/*.example`*.
Reset re-runs that definition for one section:

> For each file the section owns, copy the shipped `.example` if the repository
> ships one; otherwise delete the file.

No policy enum, no per-section special cases. `agent_guidance.yaml` has no
`.example`, so it is deleted, and `load_guidance()` then returns `{}` — exactly
its documented default. `templates/*.typ` has no `.example`, so the directory is
cleared and rendering falls back to bundled templates, which is what
`render/templates.py` already does for a missing custom template.

Defaults resolve against `_REPOSITORY_ROOT / "config"`, reusing the anchor
idiom in `render/templates.py:14` rather than the process working directory, so
reset behaves identically under Railway and locally.

### The bundle

New service `src/resume_agent/services/settings_bundle.py`. Archive layout —
arcnames are config-relative, plus a manifest at the root:

```
manifest.json      {"version": 1, "exportedAt": "...", "sections": ["sources", "review"]}
connectors.yaml
review.yaml
review_deep.yaml
templates/mine.typ
```

The manifest makes section membership explicit rather than inferred from
filenames, and carries a version for future format changes.

**Export** walks `SETTINGS_SECTIONS` and adds each file that exists. **A section
appears in the manifest only if at least one of its files exists.** So a user
with no custom templates produces a bundle with no `templates` section, and
importing it leaves the recipient's templates alone. A bundle can therefore add
or replace settings but never clear them — clearing is what Reset is for. Files
outside the table are unreachable by construction.

**Import validates everything before touching anything**, mirroring the staged
discipline of `import_data_root`:

1. Extract to a temporary stage with `services/backup.py::_extract_validated`.
   Reusing it — rather than writing a second extractor — keeps absolute-path,
   `..`, Windows-drive, symlink, non-regular-member, and duplicate-name defenses
   in one place.
2. Read `manifest.json`; reject an unknown `version`.
3. For each section named in the manifest, retain only staged files matching
   that section's declared patterns. **Unclaimed members are ignored, not
   rejected** — so a crafted bundle cannot plant a credential, and a bundle from
   a newer build stays importable by an older one.
4. Validate in the stage: every YAML parses through its existing Pydantic schema
   (`DOMAIN_SCHEMAS`), every `.typ` stem passes `validate_custom_stem`. A bad
   bundle fails with no live file modified.
5. Apply section by section: stash current files to a rollback directory,
   `os.replace` the new ones in, discard the stash on success, restore it on
   failure.

### API

Routes live in a new `src/resume_agent/api/routers/settings.py`, with schemas in
`src/resume_agent/api/schemas/settings.py`. All schemas are `CamelModel` subclasses, so the wire format is camelCase.
Regenerate `contracts/openapi.json` and `contracts/ts/api.ts` with
`bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the
drift gate.

| Route | Purpose |
| --- | --- |
| `GET /api/settings/sections` | Section list with `customized: bool` per section |
| `GET /api/settings/bundle` | Download the tar.gz. Lives on a `link_router` with a query token, matching `/api/account/export` |
| `POST /api/settings/bundle/preview` | Upload → sections present; no writes |
| `POST /api/settings/bundle?confirm=APPLY` | Apply the bundle |
| `POST /api/settings/sections/{id}/reset` | Reset one section |

Upload cap is 8 MB through the existing `copy_upload`, against 256 MB for a
workspace archive — these are kilobytes of text.

**Import refuses while the caller has active runs** (`409 RUNS_ACTIVE`, via
`run_manager.list_active(user_id=...)`), consistent with the existing archive
endpoints: it can rewrite nine sections at once while a tailor run is reading
`review.yaml`.

**Single-section reset does not** carry that guard. Its blast radius is the same
as the Save button already present on those settings pages, which has no such
guard; adding one only here would be inconsistent.

Per-agent prompt reset needs **no new endpoint**. `save_guidance` deletes a key
when handed an empty string, so it is `PUT /api/agents/prompts/{key}` with
`guidance: ""`.

### Errors

One envelope, `{ "error": { code, message, details? } }`, via `ApiException`.

| Code | Status | When |
| --- | --- | --- |
| `CONFIRM_REQUIRED` | 400 | import without `?confirm=APPLY` |
| `INVALID_BUNDLE` | 400 | missing/unreadable manifest, unparseable YAML, bad template stem |
| `UNSUPPORTED_VERSION` | 400 | manifest `version` this build does not know |
| `UNSAFE_ARCHIVE` | 400 | `UnsafeArchiveError` from the shared extractor |
| `UPLOAD_TOO_LARGE` | 413 | over 8 MB |
| `RUNS_ACTIVE` | 409 | import while the caller has active runs |
| `NOT_FOUND` | 404 | reset of an unknown section id |

## UI

### Settings → Backup (new page)

A nav item in the existing `System` group beside `API keys`
(`SettingsLayout.tsx:52`). Three parts:

1. **Export** — one button, `openDownload`, mirroring `DataArchiveCard`.
2. **Import** — file picker → `POST .../preview` → a dialog naming the sections
   that will be replaced *("This bundle will replace: Company sources, Review
   panel, Style guide. Your other settings are untouched.")* → confirm applies.
   No typed confirmation: the preview naming the sections is the safety, and
   unlisted sections genuinely are not touched.
3. **Sections table** — one row per section, `label` + `Customized`/`Default`
   badge + `Reset`.

The table is the **canonical, complete surface**. It has to be: `profile_sources`
has no Settings page at all — it is edited from `ProfileWorkspace.tsx` and the
setup wizard — so per-page buttons alone could never cover every section.

### Reset buttons

A shared `ResetSectionButton` component (props: section id, label) used both in
the Backup table and on individual pages. It opens the confirm dialog:

> **Reset Company sources to defaults?** This replaces `connectors.yaml` with
> the shipped default. Your current sources are lost — export a settings bundle
> first if you want them back.

The dialog names the section and its files, not a semantic count ("your 12
URLs"). Semantic summaries would require per-section introspection — nine
special cases for one line of text. The `Customized` badge carries the "you have
changes here" signal instead.

Buttons sit next to each page heading, not in `SaveBar`, which renders only when
the form is dirty and is scoped to edit-in-progress actions.

| Page | Section(s) |
| --- | --- |
| Sources | `sources` |
| Search | `search` |
| Review panel | `review` |
| Agent prompts | per-agent reset on each card, plus `agent_guidance` for all |
| Style guide | `style_guide` |
| Rendering | `render`, `templates` |
| Pruning | `prune` |
| *(no page)* | `profile_sources` — Backup table only |

## Testing

Backend tests run offline: no API key, no network, agent calls and the browser
faked.

**`tests/test_settings_sections.py`** — reset copies the `.example`; reset
deletes when no `.example` ships (`agent_guidance`); `templates/` is cleared;
`customized` detection is correct in both directions.

**`tests/test_settings_bundle.py`**

- Export → import round-trip is the identity.
- `gmail_credentials.json` and `secrets.env` never appear in an export.
- A bundle *containing* them is ignored on import, not obeyed.
- Path traversal is rejected.
- Unparseable YAML is rejected with every live file byte-identical afterwards.
- A two-section bundle leaves the other seven untouched.
- Unknown future section names are ignored.

The two credential tests are load-bearing, not incidental: they are what make
the allowlist a guarantee rather than an intention.

**`tests/api/test_settings_api.py`** — each endpoint, the `confirm` guard, `409`
while runs are active, and that the routes sit behind the normal auth guard.

**Web** — `SettingsBackupPage.test.tsx` (export button, preview→confirm flow,
section table), `ResetSectionButton.test.tsx` (dialog gate, endpoint call,
refresh), and an addition to `AgentPromptsPage.test.tsx` for per-agent reset.

**Contract** — regenerate with `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` fails the build on drift.

## Consequences

- Adding a future setting becomes one row in `SETTINGS_SECTIONS`, and it lands
  in the bundle, the preview, the sections table, and its reset button for free.
- `provision_workspace` stops carrying its own idea of what a fresh workspace
  contains, so provisioning and resetting can no longer drift apart.
- A settings bundle is safe to hand to another person: by construction it can
  carry only the nine declared sections.
