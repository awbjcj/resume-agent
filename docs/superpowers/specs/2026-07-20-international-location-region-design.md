# International Job Location Region Classification — Design

**Date:** 2026-07-20
**Scope:** Extend structured `{city, region, country}` extraction for discovered **jobs** so non-US countries get a real `region` value too, instead of `region` always being `null` outside the US. Same two layers as the prior US-only work: the deterministic taxonomy (`taxonomy/location.py`) and the LLM extraction prompt (`discovery/fit.py`).

Out of scope (explicitly decided): candidate/profile location structuring (`ProfileFacts.location` stays a raw string), a 4th "district"/"subregion" field, and per-country canonical region tables (province/state code lookups) beyond the existing US one.

## Problem

[2026-07-18-us-location-extraction-design.md](2026-07-18-us-location-extraction-design.md) deliberately left foreign-location behavior unchanged: `normalize_region()` early-returns `None` whenever the country isn't US ("foreign = city + country"). That was correct for that increment's scope, but it means a posting like `"New Taipei, Banqiao District, New Taipei City, Taiwan"` today resolves to `{city: "Banqiao District", region: null, country: null}` (Taiwan isn't even in the country table) — no region, and country-based filtering can't tell it apart from any other job. The board's country/region/city filters (`services/board.py`, `services/shortlist_filtering.py`) and the job-detail UI (`JobMeta.tsx`) already treat `location_region` generically; they just never receive a non-null value for non-US rows.

## Country table (`_COUNTRY_TO_ISO2`)

Add Taiwan plus a broader set of commonly-seen countries, each keyed the same way existing entries are (lowercase name/abbreviation → ISO2), including 1-2 common variants where ambiguity exists (matching the existing `"uk"` / `"united kingdom"` pattern):

Taiwan (TW), China (CN), Hong Kong (HK), South Korea (KR, plus `"korea, republic of"`), Mexico (MX), Italy (IT), Switzerland (CH), Sweden (SE), Portugal (PT), New Zealand (NZ), Austria (AT), Belgium (BE), Denmark (DK), Norway (NO), Finland (FI), Czechia (CZ), Romania (RO), UAE (AE, plus `"united arab emirates"`), South Africa (ZA), Argentina (AR), Colombia (CO), Chile (CL), Philippines (PH), Vietnam (VN), Indonesia (ID), Malaysia (MY), Thailand (TH).

## Layer 2 — deterministic taxonomy (`taxonomy/location.py`)

**`normalize_region(raw, country_iso2)`:**

- `country_iso2 == "US"` → unchanged: resolve via `_US_STATE_TO_USPS` / `_US_STATE_ABBREV` / bare USPS code.
- `country_iso2` resolved to any other known country → **new:** run `raw` through `_clean_region()` and return that (pass-through, not a canonical code — no per-country lookup table exists or is being built here).
- `country_iso2 is None` (country unresolved) → unchanged: `None`. We only ever infer a country from a bare region for the US (see below); there's no lookup table to justify guessing any other country from an untagged region string.

**`_clean_region(raw) -> str | None`** (new helper): strip, collapse internal whitespace, strip a trailing ZIP-like suffix (reuse `_ZIP_RE`). No forced casing — the LLM's raw output is normally already well-cased, and forcing `.title()` would corrupt a 2-letter code or acronym-like region if one ever shows up (e.g. `"CA"` → `"Ca"`). Returns `None` for empty/whitespace-only input.

**`build_location()` restructure:** Keeps computing `region_usps` first via the existing US-pattern match — unconditionally, before country is known — exactly as today, since that ordering is what lets `"San Francisco, CA"` (no country written) infer `country="US"`. Only the final region assignment changes:

```
if us:
    region = region_usps
elif iso2 is not None:       # resolved non-US country
    region = _clean_region(region_raw)
else:
    region = None
```

The existing US-only "city leaked `'City, ST'`" repair (`_split_city_region`) and curated metro aliases (NYC, Bay Area, Silicon Valley, SF) stay US-only. There is no safe country-agnostic equivalent without a lookup table: if a connector or the LLM concatenates district/city into one field for a non-US posting, splitting it correctly is left to the LLM extraction step (Layer 1), not this deterministic layer.

## Layer 1 — LLM prompt (`discovery/fit.py`)

Generalize the instruction that currently reads:

> "Split a combined location into its parts: put the city in city, the US state (full name or 2-letter code) in region, and the nation in country."

to be country-agnostic, e.g.:

> "Split a combined location into its parts: put the city in city, the state/province/administrative region in region, and the nation in country."

Keep the existing, separate instruction that infers `country="US"` when a US state or clearly-US city is named — that heuristic is unaffected and still the only free country inference in the system.

## Invariants preserved

- `FitScore` / `FitLocation` schemas and the camelCase wire contract are unchanged (still exactly `city`/`region`/`country`, no new field).
- Downstream consumers (`services/board.py` `FacetSpec`s, `services/shortlist_filtering.py` cascading filters, `tracking/queries.py` `ShortlistRow`, `JobMeta.tsx`) need no changes — they already treat `location_region` generically and simply start receiving non-null values for non-US rows.
- US behavior is byte-for-byte unchanged: US inference order, USPS resolution, abbreviation variants, ZIP-stripping, metro aliases, and the `LA`-is-Louisiana-never-Los-Angeles guard are untouched.
- A location with an unresolved country still yields `region=null` — the module never guesses a country from a bare, uncorroborated region string for anyone but the US.

## Testing

Pure-logic, offline. Extend `tests/test_taxonomy_location.py`:

- Taiwan end-to-end: `("Banqiao District", "New Taipei City", "Taiwan")` → `region="New Taipei City"`, `country="TW"`, `is_us=False`.
- `_clean_region`: whitespace collapse, trailing-ZIP-like strip, empty string → `None`, case preserved (no forced title-casing).
- Update `test_normalize_region_us_only` — a non-US resolved country now returns the pass-through region string, not `None` (rename/re-scope this test accordingly).
- Update `test_build_location_foreign_has_no_region` — `London` / `Greater London` / `United Kingdom` now yields `region="Greater London"`, not `null`.
- Update `test_foreign_country_keeps_region_null_even_with_state_like_field` — `("Ontario", "CA", "Canada")` now yields `region="CA"` (verbatim pass-through of the given region field, still not corrupted into "California"); rename to reflect that the guard is specifically "a non-US country never gets `region` re-interpreted through the US table," not "non-US region is always null."
- Bare region, no resolvable country: `("Somewhere", "Some Province", None)` → all fields stay `null` except the raw `city`/`region` inputs are simply not surfaced (mirrors the existing `test_does_not_infer_us_from_bare_city` boundary).
- Regression: every existing US-path test (state inference, metro aliases, abbreviation variants, ZIP strip, `LA`-is-Louisiana) unchanged.
- Prompt-contract: `tests/test_agent_prompt_contracts.py`, if it gates fit instructions — assert the updated (country-agnostic) region wording is present.
