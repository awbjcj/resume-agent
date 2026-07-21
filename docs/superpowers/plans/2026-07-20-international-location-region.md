# International Job Location Region Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give non-US job locations a real `region` value (e.g. Taiwan's `"New Taipei City"`) instead of `region` always being `null` outside the US, while leaving all US behavior byte-for-byte unchanged.

**Architecture:** Two layers, matching the existing US-only implementation. Layer 2 (`src/resume_agent/taxonomy/location.py`) is the deterministic taxonomy: it gains a country table expansion, a new `_clean_region()` pass-through helper, and a small restructure of `build_location()`'s final region assignment so a resolved non-US country gets a cleaned pass-through region instead of `None`. Layer 1 (`src/resume_agent/discovery/fit.py`) is the LLM extraction prompt: one instruction sentence is reworded from "US state" to a country-agnostic "state, province, or administrative region" so the model actually extracts a region for non-US postings. No schema, API, or frontend changes — `services/board.py`, `services/shortlist_filtering.py`, `tracking/queries.py`, and `JobMeta.tsx` already treat `location_region` generically.

**Tech Stack:** Python (pytest), no new dependencies.

## Global Constraints

- US behavior must not change: US state inference, USPS resolution, abbreviation variants, ZIP-stripping, curated metro aliases (NYC, SF, Bay Area, Silicon Valley), and the `LA`-is-Louisiana-never-Los-Angeles guard are all untouched — verify existing tests in `tests/test_taxonomy_location.py` still pass unmodified where the spec doesn't call for a rename.
- Non-US region is a verbatim pass-through (trim + collapse whitespace + strip a trailing ZIP-like suffix) — no forced casing, no per-country canonical code table.
- A location with an unresolved country still yields `region=null` — never infer a country from a bare, uncorroborated region string for anyone but the US (that inference already exists and is unchanged).
- `FitScore` / `FitLocation` schemas and the camelCase wire contract are unchanged — still exactly `city`/`region`/`country`, no new field.
- Test with `.venv/Scripts/python.exe -m pytest <path> -v`; lint with `ruff check <path>` (see `CLAUDE.md`).

---

### Task 1: Expand the country table

**Files:**
- Modify: `src/resume_agent/taxonomy/location.py:14-21` (`_COUNTRY_TO_ISO2`)
- Test: `tests/test_taxonomy_location.py:4-11` (`test_normalize_country_variants_to_iso2`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `normalize_country(raw: str | None) -> str | None` now resolves Taiwan and the other newly-added countries to their ISO2 codes. Later tasks rely on `normalize_country("Taiwan") == "TW"`.

- [ ] **Step 1: Write the failing test**

Replace the existing test function in `tests/test_taxonomy_location.py`:

```python
def test_normalize_country_variants_to_iso2():
    assert location.normalize_country("United States") == "US"
    assert location.normalize_country("USA") == "US"
    assert location.normalize_country("us") == "US"
    assert location.normalize_country("United Kingdom") == "GB"
    assert location.normalize_country("UK") == "GB"
    assert location.normalize_country("Taiwan") == "TW"
    assert location.normalize_country("South Korea") == "KR"
    assert location.normalize_country("Republic of Korea") == "KR"
    assert location.normalize_country("UAE") == "AE"
    assert location.normalize_country("United Arab Emirates") == "AE"
    assert location.normalize_country("Czechia") == "CZ"
    assert location.normalize_country("Czech Republic") == "CZ"
    assert location.normalize_country("Atlantis") is None
    assert location.normalize_country(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_normalize_country_variants_to_iso2 -v`
Expected: FAIL — `assert None == "TW"` (Taiwan not yet in the table).

- [ ] **Step 3: Expand `_COUNTRY_TO_ISO2`**

In `src/resume_agent/taxonomy/location.py`, replace:

```python
_COUNTRY_TO_ISO2 = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "france": "FR", "india": "IN",
    "ireland": "IE", "netherlands": "NL", "australia": "AU", "singapore": "SG",
    "spain": "ES", "poland": "PL", "brazil": "BR", "japan": "JP", "israel": "IL",
}
```

with:

```python
_COUNTRY_TO_ISO2 = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "france": "FR", "india": "IN",
    "ireland": "IE", "netherlands": "NL", "australia": "AU", "singapore": "SG",
    "spain": "ES", "poland": "PL", "brazil": "BR", "japan": "JP", "israel": "IL",
    "taiwan": "TW", "china": "CN", "hong kong": "HK",
    "south korea": "KR", "korea, republic of": "KR", "republic of korea": "KR",
    "mexico": "MX", "italy": "IT", "switzerland": "CH", "sweden": "SE",
    "portugal": "PT", "new zealand": "NZ", "austria": "AT", "belgium": "BE",
    "denmark": "DK", "norway": "NO", "finland": "FI",
    "czechia": "CZ", "czech republic": "CZ", "romania": "RO",
    "uae": "AE", "united arab emirates": "AE", "south africa": "ZA",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "philippines": "PH",
    "vietnam": "VN", "indonesia": "ID", "malaysia": "MY", "thailand": "TH",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_normalize_country_variants_to_iso2 -v`
Expected: PASS

- [ ] **Step 5: Run the full location test file to check nothing else broke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py -v`
Expected: PASS (all tests, since this task only adds table entries)

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/taxonomy/location.py tests/test_taxonomy_location.py
git commit -m "feat(taxonomy): add Taiwan and other countries to location country table"
```

---

### Task 2: Add `_clean_region()` and generalize `normalize_region()`

**Files:**
- Modify: `src/resume_agent/taxonomy/location.py` (add `_clean_region`, rewrite `normalize_region`)
- Test: `tests/test_taxonomy_location.py:14-18` (`test_normalize_region_us_only`), plus new `_clean_region` tests

**Interfaces:**
- Consumes: `_ZIP_RE` (existing module-level regex), `is_us()` (existing).
- Produces: `_clean_region(raw: str | None) -> str | None` — strips a trailing ZIP-like suffix, trims, collapses internal whitespace, preserves original casing, returns `None` for empty/whitespace-only input. `normalize_region(raw, country_iso2)` now returns a cleaned pass-through for any resolved non-US country instead of always `None`. Task 3's `build_location()` restructure calls `_clean_region` directly (not through `normalize_region`, since `build_location` has its own inline US-first resolution order — see Task 3).

- [ ] **Step 1: Write the failing tests**

Replace the existing test function in `tests/test_taxonomy_location.py`:

```python
def test_normalize_region_us_only():
    assert location.normalize_region("California", "US") == "CA"
    assert location.normalize_region("CA", "US") == "CA"
    assert location.normalize_region(None, "US") is None
```

with:

```python
def test_normalize_region_us_and_pass_through():
    assert location.normalize_region("California", "US") == "CA"
    assert location.normalize_region("CA", "US") == "CA"
    assert location.normalize_region(None, "US") is None
    assert location.normalize_region("Ontario", "CA") == "Ontario"  # non-US -> pass-through
    assert location.normalize_region("New Taipei City", "TW") == "New Taipei City"
    assert location.normalize_region("Some Province", None) is None  # country unresolved


def test_clean_region_collapses_whitespace_and_strips_zip():
    assert location._clean_region("  New   Taipei  City ") == "New Taipei City"
    assert location._clean_region("Ontario 12345") == "Ontario"
    assert location._clean_region("   ") is None
    assert location._clean_region(None) is None
```

(Note: this deletes the old `# non-US -> None` assertion line from the original test body — the whole function is being replaced, not patched.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_normalize_region_us_and_pass_through tests/test_taxonomy_location.py::test_clean_region_collapses_whitespace_and_strips_zip -v`
Expected: FAIL — `test_normalize_region_us_and_pass_through` fails on `assert None == "Ontario"`; `test_clean_region_collapses_whitespace_and_strips_zip` fails with `AttributeError: module 'resume_agent.taxonomy.location' has no attribute '_clean_region'`.

- [ ] **Step 3: Add `_clean_region()` and rewrite `normalize_region()`**

In `src/resume_agent/taxonomy/location.py`, add this function immediately after `_key()` (which ends just before `def normalize_country`):

```python
def _clean_region(raw: str | None) -> str | None:
    """Light pass-through cleanup for a non-US region: no canonical table exists.

    Strips a trailing ZIP-like suffix and collapses whitespace, but preserves
    the original casing — forcing title-case would corrupt an acronym-like
    region (e.g. a 2-letter code) if one ever shows up.
    """
    if raw is None:
        return None
    candidate = _ZIP_RE.sub("", raw.strip()).strip()
    candidate = " ".join(candidate.split())
    return candidate or None
```

Then replace:

```python
def normalize_region(raw: str | None, country_iso2: str | None) -> str | None:
    """US states -> USPS code. Non-US gets no region (foreign = city + country)."""
    if not is_us(country_iso2):
        return None
    return _region_to_usps(raw)
```

with:

```python
def normalize_region(raw: str | None, country_iso2: str | None) -> str | None:
    """US states -> USPS code. Other resolved countries -> cleaned pass-through."""
    if is_us(country_iso2):
        return _region_to_usps(raw)
    if country_iso2 is None:
        return None
    return _clean_region(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_normalize_region_us_and_pass_through tests/test_taxonomy_location.py::test_clean_region_collapses_whitespace_and_strips_zip -v`
Expected: PASS

- [ ] **Step 5: Run the full location test file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py -v`
Expected: PASS (the `build_location`-level foreign-region tests still expect the old `None` behavior at this point — that's fixed in Task 3, so don't be alarmed if you're running ahead; if you're following this plan in order, they should still pass since Task 2 doesn't touch `build_location`)

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/taxonomy/location.py tests/test_taxonomy_location.py
git commit -m "feat(taxonomy): pass through non-US region text instead of discarding it"
```

---

### Task 3: Restructure `build_location()` to use the pass-through region

**Files:**
- Modify: `src/resume_agent/taxonomy/location.py:143-178` (`build_location`)
- Test: `tests/test_taxonomy_location.py` (`test_build_location_foreign_has_no_region`, `test_foreign_country_keeps_region_null_even_with_state_like_field`, plus two new tests)

**Interfaces:**
- Consumes: `_clean_region()` from Task 2, existing `_region_to_usps`, `_split_city_region`, `_METRO_ALIASES`, `normalize_country`, `is_us`.
- Produces: `build_location(city, region, country, raw=None) -> StructuredLocation` now sets `.region` to a cleaned pass-through of the raw `region` argument whenever the country resolves to a known non-US country, instead of always `None`. `.city`, `.country`, `.is_us`, `.raw` behavior is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_taxonomy_location.py`, replace:

```python
def test_build_location_foreign_has_no_region():
    loc = location.build_location("London", "Greater London", "United Kingdom")
    assert loc.country == "GB"
    assert loc.region is None
    assert loc.is_us is False
```

with:

```python
def test_build_location_foreign_region_pass_through():
    loc = location.build_location("London", "Greater London", "United Kingdom")
    assert loc.country == "GB"
    assert loc.region == "Greater London"
    assert loc.is_us is False


def test_build_location_taiwan_end_to_end():
    loc = location.build_location(
        "Banqiao District", "New Taipei City", "Taiwan",
        raw="New Taipei, Banqiao District, New Taipei City, Taiwan",
    )
    assert loc.city == "Banqiao District"
    assert loc.region == "New Taipei City"
    assert loc.country == "TW"
    assert loc.is_us is False
    assert loc.raw == "New Taipei, Banqiao District, New Taipei City, Taiwan"


def test_build_location_bare_region_without_country_stays_unresolved():
    loc = location.build_location("Somewhere", "Some Province", None)
    assert loc.country is None
    assert loc.region is None
    assert loc.is_us is False
```

And replace:

```python
def test_foreign_country_keeps_region_null_even_with_state_like_field():
    # A resolved non-US country must not trigger US inference from a stray token.
    loc = location.build_location("Ontario", "CA", "Canada")
    assert loc.country == "CA"
    assert loc.region is None
    assert loc.is_us is False
```

with:

```python
def test_foreign_country_region_not_reinterpreted_as_us_state():
    # A resolved non-US country must not trigger US inference from a stray token,
    # and the region is passed through verbatim rather than expanded via the US table.
    loc = location.build_location("Ontario", "CA", "Canada")
    assert loc.country == "CA"
    assert loc.region == "CA"
    assert loc.is_us is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_build_location_foreign_region_pass_through tests/test_taxonomy_location.py::test_build_location_taiwan_end_to_end tests/test_taxonomy_location.py::test_build_location_bare_region_without_country_stays_unresolved tests/test_taxonomy_location.py::test_foreign_country_region_not_reinterpreted_as_us_state -v`
Expected: FAIL — `test_build_location_foreign_region_pass_through` fails on `assert None == "Greater London"`; `test_build_location_taiwan_end_to_end` fails on `assert None == "New Taipei City"`; `test_foreign_country_region_not_reinterpreted_as_us_state` fails on `assert None == "CA"`; `test_build_location_bare_region_without_country_stays_unresolved` should already pass (no code change needed for that case, it's a regression guard).

- [ ] **Step 3: Restructure `build_location()`**

In `src/resume_agent/taxonomy/location.py`, replace:

```python
    us = is_us(iso2)
    return StructuredLocation(
        city=city_value,
        region=region_usps if us else None,
        country=iso2,
        is_us=us,
        raw=raw,
    )
```

with:

```python
    us = is_us(iso2)
    if us:
        region_value = region_usps
    elif iso2 is not None:
        region_value = _clean_region(region)
    else:
        region_value = None

    return StructuredLocation(
        city=city_value,
        region=region_value,
        country=iso2,
        is_us=us,
        raw=raw,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py::test_build_location_foreign_region_pass_through tests/test_taxonomy_location.py::test_build_location_taiwan_end_to_end tests/test_taxonomy_location.py::test_build_location_bare_region_without_country_stays_unresolved tests/test_taxonomy_location.py::test_foreign_country_region_not_reinterpreted_as_us_state -v`
Expected: PASS

- [ ] **Step 5: Run the full test file to confirm every US-path test is untouched**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py -v`
Expected: PASS — all tests, including `test_build_location_us`, `test_infers_us_from_state_when_country_absent`, `test_infers_us_from_curated_metro_nyc`, `test_infers_us_from_bay_area_metro`, `test_la_is_louisiana_never_los_angeles`, `test_splits_city_state_leaked_into_city_field`, `test_strips_trailing_zip_from_region`, `test_does_not_infer_us_from_bare_city`, `test_build_location_unparseable_country`, `test_as_dict_roundtrips`.

- [ ] **Step 6: Lint**

Run: `ruff check src/resume_agent/taxonomy/location.py tests/test_taxonomy_location.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/taxonomy/location.py tests/test_taxonomy_location.py
git commit -m "feat(taxonomy): build_location passes through region for resolved non-US countries"
```

---

### Task 4: Generalize the fit-score LLM prompt's region instruction

**Files:**
- Modify: `src/resume_agent/discovery/fit.py:51-53` (`_INSTRUCTIONS`)
- Test: `tests/test_agent_prompt_contracts.py:96-100` (`test_fit_prompt_guides_us_location_segmentation`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_INSTRUCTIONS` (list of str) in `fit.py` — the region-splitting sentence no longer says "the US state" but "the state, province, or administrative region"; the separate US-country-inference sentence is unchanged. No change to `FitLocation`/`FitScore` schemas.

- [ ] **Step 1: Write the failing test**

In `tests/test_agent_prompt_contracts.py`, replace:

```python
def test_fit_prompt_guides_us_location_segmentation():
    rendered = _text(FIT_INSTRUCTIONS)
    assert "us state" in rendered
    assert 'country to "us"' in rendered
    assert "remote" in rendered
```

with:

```python
def test_fit_prompt_guides_location_segmentation():
    rendered = _text(FIT_INSTRUCTIONS)
    assert "administrative region" in rendered
    assert "us state" in rendered
    assert 'country to "us"' in rendered
    assert "remote" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_prompt_contracts.py::test_fit_prompt_guides_location_segmentation -v`
Expected: FAIL — `assert 'administrative region' in rendered` fails (phrase not present yet).

- [ ] **Step 3: Reword the region-splitting instruction**

In `src/resume_agent/discovery/fit.py`, replace:

```python
    "Split a combined location into its parts: put the city in city, the US state (full name or "
    '2-letter code) in region, and the nation in country. Set country to "US" whenever the location '
    "names a US state or a clearly US city, even when the country is not written.",
```

with:

```python
    "Split a combined location into its parts: put the city in city, the state, province, or "
    'administrative region in region, and the nation in country. Set country to "US" whenever the '
    "location names a US state or a clearly US city, even when the country is not written.",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_prompt_contracts.py::test_fit_prompt_guides_location_segmentation -v`
Expected: PASS

- [ ] **Step 5: Run the full prompt contract test file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_prompt_contracts.py -v`
Expected: PASS (all tests — `test_fit_prompt_does_not_duplicate_industry_classification` and `test_untrusted_data_prompts_define_an_instruction_boundary` are unaffected by this wording change)

- [ ] **Step 6: Lint**

Run: `ruff check src/resume_agent/discovery/fit.py tests/test_agent_prompt_contracts.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/discovery/fit.py tests/test_agent_prompt_contracts.py
git commit -m "feat(fit): generalize location-splitting prompt instruction beyond US states"
```

---

### Task 5: Full regression pass

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Run the full offline test suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS, 0 failures

- [ ] **Step 2: Run the full lint pass**

Run: `ruff check`
Expected: no errors

- [ ] **Step 3: Confirm no commit is pending**

Run: `git status --short`
Expected: clean (nothing to commit) — Task 5 has no code changes, it's purely a final verification gate before calling the plan done.
