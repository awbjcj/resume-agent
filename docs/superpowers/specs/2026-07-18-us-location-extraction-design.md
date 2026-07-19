# US Job Location Extraction — Design

**Date:** 2026-07-18
**Scope:** Improve structured `{city, region, country}` extraction for discovered **jobs**, focused on US postings. Two layers: the deterministic taxonomy (`taxonomy/location.py`) and the LLM extraction prompt (`discovery/fit.py`).

Out of scope (explicitly decided): the mock interview agent, and structuring candidate/experience location in profile build. Foreign-location behavior is unchanged (region stays `null` for non-US).

## Problem

US job postings almost never write the country — they say `"San Francisco, CA"`, not `"…, USA"`. Today:

1. The `score_fit` agent returns `country=null` (nothing written to resolve).
2. `normalize_region(raw, country_iso2)` early-returns `None` because `is_us(None)` is `False`.
3. The state is **silently dropped** → `{city: "San Francisco", region: null, country: null}`.

So the highest-leverage fix is **inferring US-ness from the region/metro**, not adding more countries.

## Layer 2 — deterministic taxonomy (`taxonomy/location.py`), primary lift

The crux is an **ordering inversion**: today country gates region. To infer US *from* a state, region must resolve first and feed back into country. This is a `build_location` restructure, not just a bigger dict.

1. **US inference (state + curated metros).** When the country field does not resolve:
   - If the region resolves to a real US state/USPS code → `country="US"`, `is_us=True`.
   - If a curated metro alias matches → `country="US"`, `is_us=True`, and supply its region.
   - Never infer US from a bare arbitrary city.
2. **State abbreviation variants.** AP-style / colloquial → USPS: `Calif.→CA`, `Mass.→MA`, `Wash.→WA`, `Fla.→FL`, `Tex.→TX`, `Pa.`/`Penn.→PA`, `Conn.→CT`, `Ariz.→AZ`, `Colo.→CO`, `Ga.→GA`, `Ill.→IL`, `Mich.→MI`, `Minn.→MN`, `Mo.→MO`, `N.C.→NC`, `Nev.→NV`, `Ore.→OR`, `Tenn.→TN`, `Va.→VA`, `Wis.→WI`, etc. Strip trailing periods and collapse whitespace before lookup.
3. **Combined-field splitting (defensive).** If the LLM leaks `"San Francisco, CA"` into `city` with region `null`, split on the trailing comma: `city="San Francisco"`, derive `region=CA`. Strip a trailing ZIP (`"Austin, TX 78701"` → `TX`). Same split applies when the region field itself carries `"City, ST"`.
4. **Curated metro-alias map (tight, unambiguous only).** → `(city|None, region)`:
   - `nyc`, `new york city` → `(New York, NY)`
   - `sf`, `san francisco bay area`, `bay area` → `(San Francisco|None, CA)`
   - `silicon valley` → `(None, CA)`
   - **`LA` is deliberately excluded** — `LA` is the USPS code for Louisiana; expanding it to Los Angeles would corrupt state data. `LA` in a region field resolves to Louisiana only.

## Layer 1 — LLM prompt (`discovery/fit.py`), the assist

Append 2–3 lines to `_INSTRUCTIONS` (matching existing terse style):
- Split a combined location string into city, region (US state, full name or 2-letter), and country.
- Set `country="US"` when the location names a US state or a clearly-US city, even when the country is unwritten.
- For remote roles, capture any country qualifier (`"Remote (US)"` → country US); leave city/region null unless a specific hub is named.

The deterministic layer remains the backstop, so a prompt miss is still caught. This keeps the feature testable offline (no live LLM).

## Invariants preserved

- Foreign locations: region stays `null` (existing behavior; US inference only fires when country is unresolved, so a resolved `GB`/`DE`/etc. is untouched).
- `FitScore` / `FitLocation` schemas and the camelCase wire contract are unchanged.
- Existing tests hold: `United Kingdom`→GB (region null), `Ontario`/CA→null, `"2 Locations"`→all null, `Austin`/`Texas`/`US`→TX.

## Testing

Pure-logic, offline. Extend `tests/test_taxonomy_location.py`:
- US inferred from state when country absent: `("San Francisco","CA",None)` → US/CA.
- US inferred from metro: `("NYC",None,None)` → US/NY, city New York.
- Abbreviation variants: `Calif.`, `Mass.`, `Tex.` → CA/MA/TX.
- Combined leak in city: `("San Francisco, CA",None,None)` → split.
- ZIP strip: `("Austin","TX 78701",None)` → TX.
- `LA` stays Louisiana; never Los Angeles.
- Regression: all current cases unchanged.

Prompt-contract: `tests/test_agent_prompt_contracts.py` if it gates fit instructions — assert the new guidance strings are present.
