# Settings Transfer and Reset — Design

**Date:** 2026-07-23
**Status:** Approved, awaiting implementation plan

## Problem

Two gaps, one root cause.

**Transfer.** The only way to move customizations between installs or users is
`GET /api/account/export` + `POST /api/account/import` — a whole-workspace
tar.gz. It already contains every setting (`provision_workspace` places
`config/` _inside_ the workspace root, so `export_data_root` sweeps it up), but
it is all-or-nothing: import replaces the database, the profile corpus, and
`secrets.env` along with the settings, requires multi-user mode, and demands a
typed `REPLACE`. There is no way to carry just "my sources and my prompt
guidance" to another machine.

**Defaults.** Nothing can be restored to its default. Defaults exist only as
`config/*.example` files copied once by `provision_workspace` at provisioning
time. After the first edit, the original is unrecoverable through the product.

The root cause is that _the set of customizable settings_ is not named anywhere.
It is scattered across six enumerations that no single caller can see:

| Location                                                                       | What it enumerates                                                                         |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `services/config_store.py::_FILES`                                             | six YAML/markdown domains                                                                  |
| `tenancy/paths.py`                                                             | `CONNECTORS_PATH`, `SEARCH_PATH`, `REVIEW_PATH`, `REVIEW_DEEP_PATH`, `AGENT_GUIDANCE_PATH` |
| `render/templates.py::CUSTOM_TEMPLATES_DIR`                                    | `config/templates`                                                                         |
| `prompts/guidance.py`                                                          | its own locked write path for `agent_guidance.yaml`                                        |
| `tenancy/workspace.py::provision_workspace`                                    | the `config/*.example` glob                                                                |
| `profile/group_corrections.py`, `taxonomy/corrections.py`, `profile/matrix.py` | three correction-ledger paths, each known only to its own module                           |

"What goes in a settings bundle" and "what can be reset" are the same list read
from two directions. Declaring it once is the spine of this design.

## Goals

- A settings-only bundle that exports and imports **just** hand-authored
  customizations — no jobs, no database, no derived profile corpus, no
  credentials.
- Section-level replace on import, bundle-level merge: sections absent from a
  bundle are left untouched.
- A reset-to-default control for every customizable section.

## Non-goals

- **Derived artifacts.** Only hand-authored intent travels. `facts.json`,
  `matrix.json`, `cluster_map.json`, and `data/skill_aliases.json` are all
  regenerated from sources by `profile build` or the discovery pipeline
  (`_refresh_skill_aliases`), so bundling them would ship stale output that the
  next rebuild overwrites. The correction ledgers _are_ included precisely
  because they are the inputs a rebuild replays, not its output.
- Deep-merging within a section (unioning two company lists, reconciling two
  reviewer rosters). Section-level replace only.
- Any change to the existing whole-workspace archive. It stays the full
  backup/restore tool.
- Transferring credentials. `secrets.env`, `gmail_token.json`, and
  `config/gmail_credentials.json` are never exported and never honored on
  import.

## Architecture

### The section registry

New module `src/resume_tailor_harness/settings_sections.py` — the single enumeration.

```python
@dataclass(frozen=True)
class SettingsSection:
    id: str                   # stable wire id
    label: str                # UI label
    files: tuple[str, ...]    # canonical relative paths; may glob

SETTINGS_SECTIONS: tuple[SettingsSection, ...] = (...)
```

`files` holds paths in the **canonical relative form already spoken by
`tenancy/paths.py`** — `config/connectors.yaml`, `data/profile/overrides.yaml`.
Running each through `resolve_tenant_path` yields the live file in either tenant
or legacy mode, and the same string is both the archive arcname and the key for
locating a shipped default. No second path vocabulary is introduced.

| id                | label                   | files                                           | default when reset          |
| ----------------- | ----------------------- | ----------------------------------------------- | --------------------------- |
| `sources`         | Company sources         | `config/connectors.yaml`                        | shipped `.example`          |
| `search`          | Search                  | `config/search.yaml`                            | shipped `.example`          |
| `review`          | Review panel            | `config/review.yaml`, `config/review_deep.yaml` | shipped `.example`s         |
| `agent_guidance`  | Agent prompts           | `config/agent_guidance.yaml`                    | _deleted_ → no guidance     |
| `style_guide`     | Style guide             | `config/style_guide.md`                         | shipped `.example`          |
| `render`          | Rendering               | `config/render.yaml`                            | shipped `.example`          |
| `templates`       | Custom resume templates | `config/templates/*.typ`                        | _cleared_ → bundled only    |
| `prune`           | Pruning                 | `config/prune.yaml`                             | shipped `.example`          |
| `profile_sources` | Profile sources         | `config/profile_sources.yaml`                   | shipped `.example`          |
| `skill_overrides` | Skill overrides         | `data/profile/overrides.yaml`                   | _deleted_ → no overrides    |
| `skill_groups`    | Skill group corrections | `data/profile/group_corrections.json`           | _deleted_ → taxonomy wins   |
| `taxonomy`        | Taxonomy corrections    | `data/taxonomy/taxonomy_corrections.json`       | _deleted_ → LLM output wins |

Twelve sections. The last three are the correction ledgers: hand-authored intent
that every rebuild replays, and the most painful customizations to lose because
they represent accumulated judgement rather than a one-time configuration.

This table is an **allowlist**, not a denylist, and that distinction is
load-bearing. It now spans the workspace root, whose immediate neighbours
include `secrets.env`, `gmail_token.json`, `resume_tailor_harness.db`, and — per
`gmail/auth.py` — `config/gmail_credentials.json`, an OAuth client secret. A
denylist would ship any of those the moment someone adds a file nobody
remembered to exclude. Allowlists fail closed, and the twelve rows above are the
complete, auditable statement of what can leave or enter a workspace this way.

`provision_workspace`'s `*.example` glob becomes a reader of this table, which
is what makes "reset a section" and "provision that section fresh" literally the
same operation.

`config_store.py::_FILES` deliberately stays as it is. ConfigStore domains and
settings sections are different granularities — the `review` _section_ owns two
files (`review.yaml`, `review_deep.yaml`) while the `review` _domain_ owns one —
so forcing one to derive from the other would need a "primary file" concept that
earns nothing. The `tenancy/paths.py` constants likewise stay: they are named
strings consumed by leaf code, not a competing list.

A section is **customized** when any file it owns differs from that file's
shipped `.example`, or — for sections that ship no `.example` — when the file
exists at all, or the glob matches anything.

### Reset is policy-free

`provision_workspace` already defines "fresh" as _copy every shipped
`.example`_. Reset re-runs that definition for one section:

> For each file the section owns, copy the shipped `.example` if the repository
> ships one; otherwise delete the file.

No policy enum, no per-section special cases, and the five sections that reset
by deletion all land on their real defaults for free:

| Section           | After deletion                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| `agent_guidance`  | `load_guidance()` returns `{}` — its documented default                                                 |
| `templates`       | `render/templates.py` falls back to bundled templates, as it already does for a missing custom template |
| `skill_overrides` | the next `profile build` re-derives without overrides                                                   |
| `skill_groups`    | `decorate_matrix_groups` falls through to overrides, then taxonomy                                      |
| `taxonomy`        | `apply_taxonomy_corrections` replays an empty ledger, leaving LLM clustering intact                     |

The default for a file is `_REPOSITORY_ROOT / <canonical path> + ".example"`,
reusing the anchor idiom in `render/templates.py:14` rather than the process
working directory, so reset behaves identically under Railway and locally. The
three `data/` ledgers ship no `.example`, which is why they reset by deletion —
the rule needs no knowledge of _which_ directory a section lives in.

Resetting `skill_overrides` is the one case whose effect is not immediate: the
ban/alias/forbid/category rules are consumed at build time, so the matrix keeps
showing the old shape until the next `profile build`. The confirm dialog says so.

### The bundle

New service `src/resume_tailor_harness/services/settings_bundle.py`. Archive layout —
arcnames are config-relative, plus a manifest at the root:

```
manifest.json      {"version": 1, "exportedAt": "...", "sections": ["sources", "review", "taxonomy"]}
config/connectors.yaml
config/review.yaml
config/review_deep.yaml
config/templates/mine.typ
data/profile/overrides.yaml
data/taxonomy/taxonomy_corrections.json
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
4. Validate in the stage against each artifact's existing **model**, but under a
   **strict error policy that the read-time loaders deliberately do not have**.
   A bad bundle fails with no live file modified.

   This distinction is the subtle part. `load_group_corrections` catches
   `(OSError, ValueError)` and `load_taxonomy_corrections` catches
   `(OSError, UnicodeError, json.JSONDecodeError)`, both returning an _empty_
   ledger. That tolerance is correct at read time — a corrupt ledger must not
   brick the profile page — but catastrophic at import time, where a truncated
   file would validate clean and then silently replace real corrections with
   nothing. `load_overrides` catches only `OSError`, so it already rejects.

   Validation therefore reuses the models and rejects on parse failure:

   | Artifact                                  | Validator                                           |
   | ----------------------------------------- | --------------------------------------------------- |
   | `config/*.yaml`, `style_guide.md`         | `DOMAIN_SCHEMAS[domain].model_validate`             |
   | `config/templates/*.typ`                  | `validate_custom_stem` on the stem                  |
   | `data/profile/overrides.yaml`             | `load_overrides` (already strict)                   |
   | `data/profile/group_corrections.json`     | `GroupCorrections.model_validate_json`              |
   | `data/taxonomy/taxonomy_corrections.json` | `json.loads` + `TaxonomyCorrections.model_validate` |

   What validation must _not_ reject is **semantic** unfamiliarity. The taxonomy
   ledger tolerates dangling references by design — they are inert — so a ledger
   naming clusters the recipient does not have imports cleanly. Importing
   somebody else's corrections is expected to be partially inert. The normal
   read path then applies `sanitize_taxonomy_corrections` and
   `load_group_corrections` as it always has, so unfamiliar entries are dropped
   at use, not at import.

5. Apply section by section: stash current files to a rollback directory,
   `os.replace` the new ones in, discard the stash on success, restore it on
   failure.

### API

Routes live in a new `src/resume_tailor_harness/api/routers/settings.py`, with schemas in
`src/resume_tailor_harness/api/schemas/settings.py`. All schemas are `CamelModel` subclasses, so the wire format is camelCase.
Regenerate `contracts/openapi.json` and `contracts/ts/api.ts` with
`bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` is the
drift gate.

| Route                                     | Purpose                                                                                          |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `GET /api/settings/sections`              | Section list with `customized: bool` per section                                                 |
| `GET /api/settings/bundle`                | Download the tar.gz. Lives on a `link_router` with a query token, matching `/api/account/export` |
| `POST /api/settings/bundle/preview`       | Upload → sections present; no writes                                                             |
| `POST /api/settings/bundle?confirm=APPLY` | Apply the bundle                                                                                 |
| `POST /api/settings/sections/{id}/reset`  | Reset one section                                                                                |

Upload cap is 8 MB through the existing `copy_upload`, against 256 MB for a
workspace archive — these are kilobytes of text.

**Import refuses while the caller has active runs** (`409 RUNS_ACTIVE`, via
`run_manager.list_active(user_id=...)`), consistent with the existing archive
endpoints: it can rewrite twelve sections at once while a tailor run is reading
`review.yaml`.

**Single-section reset does not** carry that guard. Its blast radius is the same
as the Save button already present on those settings pages, which has no such
guard; adding one only here would be inconsistent.

Per-agent prompt reset needs **no new endpoint**. `save_guidance` deletes a key
when handed an empty string, so it is `PUT /api/agents/prompts/{key}` with
`guidance: ""`.

### Errors

One envelope, `{ "error": { code, message, details? } }`, via `ApiException`.

| Code                  | Status | When                                                             |
| --------------------- | ------ | ---------------------------------------------------------------- |
| `CONFIRM_REQUIRED`    | 400    | import without `?confirm=APPLY`                                  |
| `INVALID_BUNDLE`      | 400    | missing/unreadable manifest, unparseable YAML, bad template stem |
| `UNSUPPORTED_VERSION` | 400    | manifest `version` this build does not know                      |
| `UNSAFE_ARCHIVE`      | 400    | `UnsafeArchiveError` from the shared extractor                   |
| `UPLOAD_TOO_LARGE`    | 413    | over 8 MB                                                        |
| `RUNS_ACTIVE`         | 409    | import while the caller has active runs                          |
| `NOT_FOUND`           | 404    | reset of an unknown section id                                   |

## UI

### Settings → Backup (new page)

A nav item in the existing `System` group beside `API keys`
(`SettingsLayout.tsx:52`). Three parts:

1. **Export** — one button, `openDownload`, mirroring `DataArchiveCard`.
2. **Import** — file picker → `POST .../preview` → a dialog naming the sections
   that will be replaced _("This bundle will replace: Company sources, Review
   panel, Style guide. Your other settings are untouched.")_ → confirm applies.
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
URLs"). Semantic summaries would require per-section introspection — twelve
special cases for one line of text. The `Customized` badge carries the "you have
changes here" signal instead.

Buttons sit next to each page heading, not in `SaveBar`, which renders only when
the form is dirty and is scoped to edit-in-progress actions.

| Page                 | Section(s)                                                                           |
| -------------------- | ------------------------------------------------------------------------------------ |
| Sources              | `sources`                                                                            |
| Search               | `search`                                                                             |
| Review panel         | `review`                                                                             |
| Agent prompts        | per-agent reset on each card, plus `agent_guidance` for all                          |
| Style guide          | `style_guide`                                                                        |
| Rendering            | `render`, `templates`                                                                |
| Pruning              | `prune`                                                                              |
| _(no Settings page)_ | `profile_sources`, `skill_overrides`, `skill_groups`, `taxonomy` — Backup table only |

Four of the twelve sections have no Settings page: `profile_sources` is edited
from `ProfileWorkspace.tsx` and the setup wizard, and the three correction
ledgers are written from the profile skills panel and the Match/Gap
constellation. Per-page buttons could therefore never be the complete surface —
which is why the Backup table is canonical rather than a convenience.

## Testing

Backend tests run offline: no API key, no network, agent calls and the browser
faked.

**`tests/test_settings_sections.py`** — reset copies the `.example`; reset
deletes for each of the five sections that ship none; `templates/` is cleared;
`customized` detection is correct in both directions; every declared path
resolves under the active workspace through `resolve_tenant_path` in both tenant
and legacy mode.

**`tests/test_settings_bundle.py`**

- Export → import round-trip is the identity, including the three `data/`
  ledgers.
- `gmail_credentials.json`, `secrets.env`, `gmail_token.json`, and
  `resume_tailor_harness.db` never appear in an export.
- A bundle _containing_ any of them is ignored on import, not obeyed.
- Path traversal is rejected.
- Unparseable YAML or JSON is rejected with every live file byte-identical
  afterwards — asserted **specifically for `group_corrections.json` and
  `taxonomy_corrections.json`**, whose read-time loaders would otherwise absorb
  the corruption and silently import an empty ledger over real corrections.
- A taxonomy ledger referencing clusters the recipient lacks imports cleanly and
  stays inert.
- A two-section bundle leaves the other ten untouched.
- Unknown future section names are ignored.

The credential tests are load-bearing, not incidental: now that the allowlist
spans the workspace root rather than `config/` alone, they are what make it a
guarantee rather than an intention.

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
  carry only the twelve declared sections.
- The correction ledgers become transferable and resettable for the first time.
  They were previously recoverable only by restoring an entire workspace, which
  meant losing every job in the process.
