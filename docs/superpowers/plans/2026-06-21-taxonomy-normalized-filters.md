# Taxonomy-Normalized Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the messy free-text Industry/Skills filters with a dense, deduped controlled vocabulary (SIC industry, split + synonym-canonicalized skills, structured location, bucketed company-size).

**Architecture:** A new pure `taxonomy` package is the canonical authority (offline-testable; no runtime LLM). LLMs ride existing pipeline passes only: the extract agent emits atomic skills + bucketed company-size; the fit agent emits a 2-digit SIC code + parsed location at `run_score`. The deterministic layer normalizes/derives everything. Storage stays in `criteria_json` (no migration); filtering stays in-memory.

**Tech Stack:** Python 3, Pydantic / SQLModel, Typer CLI, Streamlit dashboard, pytest (offline; agents faked, data fixtured), `agno` agents.

**Spec:** `docs/superpowers/specs/2026-06-21-taxonomy-normalized-filters-design.md`

**Test command:** `.venv/Scripts/python.exe -m pytest <path> -v`
**Lint:** `ruff check`

---

## File Structure

**New — pure `taxonomy` package** (each module one responsibility; the interface is the test surface):

- `src/resume_agent/taxonomy/__init__.py`
- `src/resume_agent/taxonomy/sic.py` — load SIC table, derive label/division, coerce code.
- `src/resume_agent/taxonomy/data/sic_codes.json` — bundled static reference (divisions + 2-digit major groups).
- `src/resume_agent/taxonomy/skills.py` — split compounds, load/apply/merge/refresh alias map.
- `src/resume_agent/taxonomy/location.py` — country→ISO-2, US state→USPS, `is_us`, assemble `StructuredLocation`.
- `src/resume_agent/taxonomy/company_size.py` — snap free-text to {startup, scaleup, enterprise}.

**Modified:**

- `src/resume_agent/discovery/extract.py` — prompt: atomic skills + bucketed company-size.
- `src/resume_agent/discovery/fit.py` — `FitScore` gains `sic_major` + `location`; `compose_fit_input` takes location.
- `src/resume_agent/discovery/pipeline.py` — `run_score` writes SIC + location into `criteria_json` + alias refresh; `discover` threads canonicalizer; new `backfill_rescore`.
- `src/resume_agent/cli.py` — `--rescore` flag on `discover`.
- `src/resume_agent/tracking/queries.py` — widened `ShortlistRow`; canonical skill tags; SIC/location/size flatten.
- `src/resume_agent/dashboard/filtering.py` — `FilterState` keeps the existing `industry` interface but stores SIC major-group codes; add location/size; `_passes`; cascade option builders.
- `src/resume_agent/dashboard/pages.py` — control-desk cascades (industry + location + company-size).

**Convention note:** backfill is a `--rescore` flag on `discover`, mirroring the existing `--reextract` flag (`cli.py:171`), not a new top-level command.

---

## Task 1: SIC table + derivation (`taxonomy/sic.py`)

**Files:**

- Create: `src/resume_agent/taxonomy/__init__.py` (empty)
- Create: `src/resume_agent/taxonomy/data/sic_codes.json`
- Create: `src/resume_agent/taxonomy/sic.py`
- Test: `tests/test_taxonomy_sic.py`

- [ ] **Step 1: Create the package `__init__.py`**

Create `src/resume_agent/taxonomy/__init__.py` as an empty file.

- [ ] **Step 2: Create the bundled SIC reference data**

Create `src/resume_agent/taxonomy/data/sic_codes.json`:

```json
{
  "divisions": {
    "A": "Agriculture, Forestry & Fishing",
    "B": "Mining",
    "C": "Construction",
    "D": "Manufacturing",
    "E": "Transportation, Communications & Utilities",
    "F": "Wholesale Trade",
    "G": "Retail Trade",
    "H": "Finance, Insurance & Real Estate",
    "I": "Services",
    "J": "Public Administration"
  },
  "major_groups": {
    "01": { "label": "Agricultural Production Crops", "division": "A" },
    "02": { "label": "Agricultural Production Livestock", "division": "A" },
    "07": { "label": "Agricultural Services", "division": "A" },
    "08": { "label": "Forestry", "division": "A" },
    "09": { "label": "Fishing, Hunting & Trapping", "division": "A" },
    "10": { "label": "Metal Mining", "division": "B" },
    "12": { "label": "Coal Mining", "division": "B" },
    "13": { "label": "Oil & Gas Extraction", "division": "B" },
    "14": { "label": "Mining of Nonmetallic Minerals", "division": "B" },
    "15": {
      "label": "Building Construction-General Contractors",
      "division": "C"
    },
    "16": { "label": "Heavy Construction", "division": "C" },
    "17": {
      "label": "Construction-Special Trade Contractors",
      "division": "C"
    },
    "20": { "label": "Food & Kindred Products", "division": "D" },
    "21": { "label": "Tobacco Products", "division": "D" },
    "22": { "label": "Textile Mill Products", "division": "D" },
    "23": { "label": "Apparel & Other Finished Products", "division": "D" },
    "24": { "label": "Lumber & Wood Products", "division": "D" },
    "25": { "label": "Furniture & Fixtures", "division": "D" },
    "26": { "label": "Paper & Allied Products", "division": "D" },
    "27": { "label": "Printing & Publishing", "division": "D" },
    "28": { "label": "Chemicals & Allied Products", "division": "D" },
    "29": { "label": "Petroleum Refining", "division": "D" },
    "30": { "label": "Rubber & Misc Plastics Products", "division": "D" },
    "31": { "label": "Leather & Leather Products", "division": "D" },
    "32": {
      "label": "Stone, Clay, Glass & Concrete Products",
      "division": "D"
    },
    "33": { "label": "Primary Metal Industries", "division": "D" },
    "34": { "label": "Fabricated Metal Products", "division": "D" },
    "35": {
      "label": "Industrial Machinery & Computer Equipment",
      "division": "D"
    },
    "36": {
      "label": "Electronic & Other Electrical Equipment",
      "division": "D"
    },
    "37": { "label": "Transportation Equipment", "division": "D" },
    "38": { "label": "Measuring & Controlling Instruments", "division": "D" },
    "39": {
      "label": "Miscellaneous Manufacturing Industries",
      "division": "D"
    },
    "40": { "label": "Railroad Transportation", "division": "E" },
    "41": { "label": "Local & Interurban Passenger Transit", "division": "E" },
    "42": {
      "label": "Motor Freight Transportation & Warehousing",
      "division": "E"
    },
    "43": { "label": "United States Postal Service", "division": "E" },
    "44": { "label": "Water Transportation", "division": "E" },
    "45": { "label": "Transportation by Air", "division": "E" },
    "46": { "label": "Pipelines, Except Natural Gas", "division": "E" },
    "47": { "label": "Transportation Services", "division": "E" },
    "48": { "label": "Communications", "division": "E" },
    "49": { "label": "Electric, Gas & Sanitary Services", "division": "E" },
    "50": { "label": "Wholesale Trade-Durable Goods", "division": "F" },
    "51": { "label": "Wholesale Trade-Nondurable Goods", "division": "F" },
    "52": { "label": "Building Materials & Garden Supplies", "division": "G" },
    "53": { "label": "General Merchandise Stores", "division": "G" },
    "54": { "label": "Food Stores", "division": "G" },
    "55": { "label": "Automotive Dealers & Service Stations", "division": "G" },
    "56": { "label": "Apparel & Accessory Stores", "division": "G" },
    "57": { "label": "Home Furniture & Furnishings Stores", "division": "G" },
    "58": { "label": "Eating & Drinking Places", "division": "G" },
    "59": { "label": "Miscellaneous Retail", "division": "G" },
    "60": { "label": "Depository Institutions", "division": "H" },
    "61": { "label": "Non-depository Credit Institutions", "division": "H" },
    "62": { "label": "Security & Commodity Brokers", "division": "H" },
    "63": { "label": "Insurance Carriers", "division": "H" },
    "64": { "label": "Insurance Agents, Brokers & Service", "division": "H" },
    "65": { "label": "Real Estate", "division": "H" },
    "67": { "label": "Holding & Other Investment Offices", "division": "H" },
    "70": { "label": "Hotels & Other Lodging Places", "division": "I" },
    "72": { "label": "Personal Services", "division": "I" },
    "73": { "label": "Business Services", "division": "I" },
    "75": { "label": "Automotive Repair, Services & Parking", "division": "I" },
    "76": { "label": "Miscellaneous Repair Services", "division": "I" },
    "78": { "label": "Motion Pictures", "division": "I" },
    "79": { "label": "Amusement & Recreation Services", "division": "I" },
    "80": { "label": "Health Services", "division": "I" },
    "81": { "label": "Legal Services", "division": "I" },
    "82": { "label": "Educational Services", "division": "I" },
    "83": { "label": "Social Services", "division": "I" },
    "84": {
      "label": "Museums & Botanical/Zoological Gardens",
      "division": "I"
    },
    "86": { "label": "Membership Organizations", "division": "I" },
    "87": { "label": "Engineering & Management Services", "division": "I" },
    "88": { "label": "Private Households", "division": "I" },
    "89": { "label": "Services-Miscellaneous", "division": "I" },
    "91": {
      "label": "Executive, Legislative & General Government",
      "division": "J"
    },
    "92": { "label": "Justice, Public Order & Safety", "division": "J" },
    "93": { "label": "Public Finance & Taxation", "division": "J" },
    "94": {
      "label": "Administration of Human Resource Programs",
      "division": "J"
    },
    "95": {
      "label": "Administration of Environmental Programs",
      "division": "J"
    },
    "96": { "label": "Administration of Economic Programs", "division": "J" },
    "97": {
      "label": "National Security & International Affairs",
      "division": "J"
    },
    "99": { "label": "Nonclassifiable Establishments", "division": "J" }
  }
}
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_taxonomy_sic.py`:

```python
from resume_agent.taxonomy import sic


def test_load_table_has_divisions_and_major_groups():
    table = sic.load_sic_table()
    assert table["divisions"]["H"] == "Finance, Insurance & Real Estate"
    assert table["major_groups"]["73"]["label"] == "Business Services"
    assert table["major_groups"]["73"]["division"] == "I"


def test_major_group_label():
    table = sic.load_sic_table()
    assert sic.major_group_label("60", table) == "Depository Institutions"
    assert sic.major_group_label("zz", table) is None


def test_division_for_returns_code_and_label():
    table = sic.load_sic_table()
    assert sic.division_for("80", table) == ("I", "Services")
    assert sic.division_for("zz", table) is None


def test_coerce_code_keeps_valid_drops_invalid():
    table = sic.load_sic_table()
    assert sic.coerce_code("73", table) == "73"
    assert sic.coerce_code("9999", table) is None
    assert sic.coerce_code(None, table) is None
    assert sic.coerce_code("  60 ", table) == "60"


def test_display_label_falls_back_to_unclassified():
    table = sic.load_sic_table()
    assert sic.display_label("73", table) == "Business Services"
    assert sic.display_label(None, table) == sic.UNCLASSIFIED
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_sic.py -v`
Expected: FAIL with `ModuleNotFoundError`/`AttributeError` (sic module/functions not defined).

- [ ] **Step 5: Write minimal implementation**

Create `src/resume_agent/taxonomy/sic.py`:

```python
"""SIC industry vocabulary: load the bundled 2-digit table and derive labels."""

import json
from importlib.resources import files

UNCLASSIFIED = "Unclassified"


def load_sic_table() -> dict:
    """Load the bundled divisions + major-groups reference."""
    raw = files("resume_agent.taxonomy").joinpath("data", "sic_codes.json").read_text("utf-8")
    return json.loads(raw)


def major_group_label(code: str | None, table: dict) -> str | None:
    if code is None:
        return None
    return table["major_groups"].get(code, {}).get("label")


def division_for(code: str | None, table: dict) -> tuple[str, str] | None:
    if code is None:
        return None
    group = table["major_groups"].get(code)
    if group is None:
        return None
    division = group["division"]
    return division, table["divisions"][division]


def coerce_code(raw: str | None, table: dict) -> str | None:
    """Return the code if it is a known major group, else None."""
    if raw is None:
        return None
    code = str(raw).strip()
    return code if code in table["major_groups"] else None


def display_label(code: str | None, table: dict) -> str:
    """Return the major-group label, or the display fallback for unknown industry."""
    return major_group_label(code, table) or UNCLASSIFIED
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_sic.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Ensure the data file ships with the package**

Open `pyproject.toml`. This project uses Hatchling, so verify the built wheel includes `src/resume_agent/taxonomy/data/sic_codes.json`. If it does not, add:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/resume_agent/taxonomy/data/sic_codes.json" = "resume_agent/taxonomy/data/sic_codes.json"
```

Then run `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_sic.py -v` again to confirm still green.

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/taxonomy/__init__.py src/resume_agent/taxonomy/sic.py src/resume_agent/taxonomy/data/sic_codes.json tests/test_taxonomy_sic.py pyproject.toml
git commit -m "Add SIC taxonomy table and derivation"
```

---

## Task 2: Skill splitter (`taxonomy/skills.py`)

**Files:**

- Create: `src/resume_agent/taxonomy/skills.py`
- Test: `tests/test_taxonomy_skills.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_taxonomy_skills.py`:

```python
from resume_agent.taxonomy import skills


def test_split_skill_on_comma_and_or():
    assert skills.split_skill("Python, C++ or C") == ["Python", "C++", "C"]


def test_split_skill_on_slash():
    assert skills.split_skill("Python/Java") == ["Python", "Java"]


def test_split_skill_protects_known_tokens():
    assert skills.split_skill("CI/CD") == ["CI/CD"]
    assert skills.split_skill("A/B testing") == ["A/B testing"]


def test_split_skill_atomic_passthrough():
    assert skills.split_skill("Node.js") == ["Node.js"]
    assert skills.split_skill("  Go  ") == ["Go"]


def test_split_skills_flattens_and_dedupes_preserving_order():
    assert skills.split_skills(["Python, Go", "Go", "Rust"]) == ["Python", "Go", "Rust"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_skills.py -v`
Expected: FAIL (`AttributeError`: `split_skill` not defined).

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/taxonomy/skills.py`:

```python
"""Skill taxonomy: split compound skills and apply a synonym alias map."""

import re

# Raw tokens that legitimately contain a split delimiter and must stay whole.
PROTECTED_TOKENS: tuple[str, ...] = (
    "CI/CD",
    "A/B testing",
    "TCP/IP",
    "I/O",
    "C/C++",
    "R&D",
)

# Split on comma, semicolon, slash, ampersand, and the words "or"/"and".
_DELIMITERS = re.compile(r"\s*(?:,|;|/|&|\bor\b|\band\b)\s*", re.IGNORECASE)


def split_skill(raw: str) -> list[str]:
    """Split one possibly-compound skill string into atomic skills."""
    text = raw
    placeholders: dict[str, str] = {}
    for i, token in enumerate(PROTECTED_TOKENS):
        marker = f"\x00{i}\x00"
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(marker, text)
            placeholders[marker] = token
    parts = _DELIMITERS.split(text)
    out: list[str] = []
    for part in parts:
        for marker, token in placeholders.items():
            part = part.replace(marker, token)
        part = part.strip()
        if part:
            out.append(part)
    return out


def split_skills(items: list[str]) -> list[str]:
    """Split every item and flatten, de-duplicating while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        for atomic in split_skill(item):
            if atomic not in seen:
                seen.add(atomic)
                out.append(atomic)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_skills.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/taxonomy/skills.py tests/test_taxonomy_skills.py
git commit -m "Add deterministic compound-skill splitter"
```

---

## Task 3: Skill alias map (`taxonomy/skills.py`)

**Files:**

- Modify: `src/resume_agent/taxonomy/skills.py`
- Test: `tests/test_taxonomy_skills.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_taxonomy_skills.py`:

```python
import json


class _FakeCanonicalizer:
    def __init__(self, mapping):
        self._mapping = mapping
        self.seen = None

    def __call__(self, tokens):
        self.seen = set(tokens)
        return {t: self._mapping.get(t, t) for t in tokens}


def test_load_aliases_missing_file_is_empty(tmp_path):
    assert skills.load_aliases(tmp_path / "nope.json") == {}


def test_canonical_skill_applies_alias_then_normalizes():
    aliases = {"k8s": "kubernetes"}
    assert skills.canonical_skill("K8s", aliases) == "kubernetes"
    assert skills.canonical_skill("Python", aliases) == "python"


def test_merge_aliases_keeps_existing_choice():
    merged = skills.merge_aliases({"k8s": "kubernetes"}, {"k8s": "k8s", "js": "javascript"})
    assert merged == {"k8s": "kubernetes", "js": "javascript"}


def test_refresh_aliases_writes_and_merges(tmp_path):
    path = tmp_path / "skill_aliases.json"
    path.write_text(json.dumps({"py": "python"}), "utf-8")
    canon = _FakeCanonicalizer({"k8s": "kubernetes"})
    merged = skills.refresh_aliases({"k8s", "kubernetes"}, canon, path)
    assert merged["py"] == "python"
    assert merged["k8s"] == "kubernetes"
    assert json.loads(path.read_text("utf-8"))["k8s"] == "kubernetes"
    assert canon.seen == {"k8s", "kubernetes"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_skills.py -v`
Expected: FAIL (`AttributeError`: `load_aliases` not defined).

- [ ] **Step 3: Write minimal implementation (append to `skills.py`)**

Add these imports at the top of `src/resume_agent/taxonomy/skills.py` (below the existing `import re`):

```python
import json
from pathlib import Path

from resume_agent.tracking.match_gap import Canonicalizer, normalize_skill
```

Append to `src/resume_agent/taxonomy/skills.py`:

```python
def load_aliases(path: str | Path) -> dict[str, str]:
    """Load the token->canonical map; missing file -> empty (identity)."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text("utf-8"))


def canonical_skill(name: str, aliases: dict[str, str]) -> str:
    """Normalize a skill name, then map it to its canonical token."""
    token = normalize_skill(name)
    return aliases.get(token, token)


def merge_aliases(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Monotonic merge: existing canonical choices win for stability."""
    merged = dict(new)
    merged.update(existing)
    return merged


def refresh_aliases(
    tokens: set[str], canonicalizer: Canonicalizer, path: str | Path
) -> dict[str, str]:
    """Canonicalize the token union, merge into the saved map, write atomically."""
    mapping = canonicalizer(tokens) if tokens else {}
    merged = merge_aliases(load_aliases(path), mapping)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp")
    tmp.write_text(json.dumps(merged, sort_keys=True), "utf-8")
    tmp.replace(p)
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_skills.py -v`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/taxonomy/skills.py tests/test_taxonomy_skills.py
git commit -m "Add machine-grown skill alias map (load/canonical/merge/refresh)"
```

---

## Task 4: Location normalization (`taxonomy/location.py`)

**Files:**

- Create: `src/resume_agent/taxonomy/location.py`
- Test: `tests/test_taxonomy_location.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_taxonomy_location.py`:

```python
from resume_agent.taxonomy import location


def test_normalize_country_variants_to_iso2():
    assert location.normalize_country("United States") == "US"
    assert location.normalize_country("USA") == "US"
    assert location.normalize_country("us") == "US"
    assert location.normalize_country("United Kingdom") == "GB"
    assert location.normalize_country("UK") == "GB"
    assert location.normalize_country("Atlantis") is None
    assert location.normalize_country(None) is None


def test_normalize_region_us_only():
    assert location.normalize_region("California", "US") == "CA"
    assert location.normalize_region("CA", "US") == "CA"
    assert location.normalize_region("Ontario", "CA") is None  # non-US -> None
    assert location.normalize_region(None, "US") is None


def test_build_location_us():
    loc = location.build_location("Mountain View", "CA", "USA", raw="Mountain View, CA, USA")
    assert loc.city == "Mountain View"
    assert loc.region == "CA"
    assert loc.country == "US"
    assert loc.is_us is True
    assert loc.raw == "Mountain View, CA, USA"


def test_build_location_foreign_has_no_region():
    loc = location.build_location("London", "Greater London", "United Kingdom")
    assert loc.country == "GB"
    assert loc.region is None
    assert loc.is_us is False


def test_build_location_unparseable_country():
    loc = location.build_location(None, None, None, raw="2 Locations")
    assert loc.city is None
    assert loc.region is None
    assert loc.country is None
    assert loc.is_us is False
    assert loc.raw == "2 Locations"


def test_as_dict_roundtrips():
    loc = location.build_location("Austin", "Texas", "US")
    assert loc.as_dict() == {
        "city": "Austin", "region": "TX", "country": "US", "is_us": True, "raw": None
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/taxonomy/location.py`:

```python
"""Location taxonomy: parse free-text into a normalized {city, region, country}."""

from dataclasses import asdict, dataclass

# Minimal controlled vocab; extend as real data demands.
_COUNTRY_TO_ISO2 = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "france": "FR", "india": "IN",
    "ireland": "IE", "netherlands": "NL", "australia": "AU", "singapore": "SG",
    "spain": "ES", "poland": "PL", "brazil": "BR", "japan": "JP", "israel": "IL",
}

_US_STATE_TO_USPS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC", "washington dc": "DC", "d.c.": "DC",
}
_USPS_CODES = set(_US_STATE_TO_USPS.values())


def normalize_country(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    if key.upper() in _COUNTRY_TO_ISO2.values():
        return key.upper()
    return _COUNTRY_TO_ISO2.get(key)


def is_us(country_iso2: str | None) -> bool:
    return country_iso2 == "US"


def normalize_region(raw: str | None, country_iso2: str | None) -> str | None:
    """US states -> USPS code. Non-US gets no region (foreign = city + country)."""
    if raw is None or not is_us(country_iso2):
        return None
    key = raw.strip().lower()
    if key.upper() in _USPS_CODES:
        return key.upper()
    return _US_STATE_TO_USPS.get(key)


@dataclass
class StructuredLocation:
    city: str | None
    region: str | None
    country: str | None
    is_us: bool
    raw: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def build_location(
    city: str | None,
    region: str | None,
    country: str | None,
    raw: str | None = None,
) -> StructuredLocation:
    iso2 = normalize_country(country)
    return StructuredLocation(
        city=(city.strip() if city and city.strip() else None),
        region=normalize_region(region, iso2),
        country=iso2,
        is_us=is_us(iso2),
        raw=raw,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_location.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/taxonomy/location.py tests/test_taxonomy_location.py
git commit -m "Add location normalization (ISO-2 country, USPS state, is_us)"
```

---

## Task 5: Company-size snap (`taxonomy/company_size.py`)

**Files:**

- Create: `src/resume_agent/taxonomy/company_size.py`
- Test: `tests/test_taxonomy_company_size.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_taxonomy_company_size.py`:

```python
from resume_agent.taxonomy import company_size


def test_snap_canonical_passthrough():
    assert company_size.snap("startup") == "startup"
    assert company_size.snap("Enterprise") == "enterprise"


def test_snap_variants():
    assert company_size.snap("Series A") == "startup"
    assert company_size.snap("seed stage") == "startup"
    assert company_size.snap("Series C, growth stage") == "scaleup"
    assert company_size.snap("Fortune 500") == "enterprise"
    assert company_size.snap("publicly traded") == "enterprise"


def test_snap_employee_counts():
    assert company_size.snap("1-50 employees") == "startup"
    assert company_size.snap("250 employees") == "scaleup"
    assert company_size.snap("10,000+ employees") == "enterprise"


def test_snap_unmappable_is_none():
    assert company_size.snap("we are a vibe") is None
    assert company_size.snap(None) is None
    assert company_size.snap("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_company_size.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/taxonomy/company_size.py`:

```python
"""Company-size taxonomy: snap free-text stage/size to three buckets."""

import re

BUCKETS = ("startup", "scaleup", "enterprise")

# Ordered substring rules; first match wins (most specific first).
_RULES: tuple[tuple[str, str], ...] = (
    ("pre-seed", "startup"),
    ("seed", "startup"),
    ("series a", "startup"),
    ("series b", "startup"),
    ("early stage", "startup"),
    ("startup", "startup"),
    ("series c", "scaleup"),
    ("series d", "scaleup"),
    ("series e", "scaleup"),
    ("growth", "scaleup"),
    ("scaleup", "scaleup"),
    ("scale-up", "scaleup"),
    ("mid-size", "scaleup"),
    ("fortune 500", "enterprise"),
    ("fortune 100", "enterprise"),
    ("publicly traded", "enterprise"),
    ("enterprise", "enterprise"),
    ("multinational", "enterprise"),
)
_COUNT = re.compile(r"(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)|(\d[\d,]*)\s*\+?")


def _employee_count_bucket(text: str) -> str | None:
    if "employee" not in text and "people" not in text:
        return None
    match = _COUNT.search(text)
    if match is None:
        return None
    high = match.group(2) or match.group(1) or match.group(3)
    count = int(high.replace(",", ""))
    if count <= 50:
        return "startup"
    if count <= 1000:
        return "scaleup"
    return "enterprise"


def snap(raw: str | None) -> str | None:
    """Map free-text size/stage to one of BUCKETS, or None if unrecognized."""
    if not raw:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    for needle, bucket in _RULES:
        if needle in text:
            return bucket
    return _employee_count_bucket(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_company_size.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/taxonomy/company_size.py tests/test_taxonomy_company_size.py
git commit -m "Add company-size snap to {startup, scaleup, enterprise}"
```

---

## Task 6: Extract prompt — atomic skills + bucketed company-size

**Files:**

- Modify: `src/resume_agent/discovery/extract.py:9-18` (the `_INSTRUCTIONS` list)
- Test: `tests/test_discovery_extract.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_discovery_extract.py`:

```python
def test_instructions_require_atomic_skills_and_size_buckets():
    joined = " ".join(_INSTRUCTIONS).lower()
    assert "one skill" in joined or "single" in joined  # atomic-skills guidance
    assert "startup" in joined and "scaleup" in joined and "enterprise" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py::test_instructions_require_atomic_skills_and_size_buckets -v`
Expected: FAIL (assertion error — guidance not present).

- [ ] **Step 3: Edit the instructions**

In `src/resume_agent/discovery/extract.py`, replace the skills + company-size lines inside `_INSTRUCTIONS`. Change the existing line:

```python
    "Capture company size or stage (startup, scaleup, enterprise) when stated.",
```

to:

```python
    "Capture company size as exactly one of: startup, scaleup, enterprise -- leave null if unclear.",
```

And add two new lines to the list (after the tech-stack line):

```python
    "Emit each skill as a single atomic skill -- never combine several into one item;",
    "e.g. 'Python, C++ or C' becomes three separate skill entries.",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py -v`
Expected: PASS (all extract tests, including the existing `test_instructions_mention_new_fields`).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/extract.py tests/test_discovery_extract.py
git commit -m "Extract prompt: atomic skills + bucketed company size"
```

---

## Task 7: Fit schema — SIC code + parsed location

**Files:**

- Modify: `src/resume_agent/discovery/fit.py`
- Test: `tests/test_discovery_fit.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_discovery_fit.py`:

```python
from resume_agent.discovery.fit import FitLocation, FitScore, compose_fit_input, score_fit
from resume_agent.models.profile import Contact, ProfileFacts


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _Result(self._content)


def test_fitscore_defaults_keep_existing_construction():
    fit = FitScore(score=90, rationale="great")
    assert fit.sic_major is None
    assert fit.location is None


def test_score_fit_returns_new_fields():
    payload = FitScore(
        score=80, rationale="ok", sic_major="73",
        location=FitLocation(city="Austin", region="TX", country="USA"),
    )
    fit = score_fit("x", _Agent(payload))
    assert fit.sic_major == "73"
    assert fit.location.city == "Austin"


def test_compose_fit_input_includes_location():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    text = compose_fit_input("the jd", facts, location="Austin, TX")
    assert "Austin, TX" in text
    assert "the jd" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_fit.py -v`
Expected: FAIL (`ImportError`: `FitLocation` not defined).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/discovery/fit.py`, update the imports line:

```python
from pydantic import ConfigDict, Field
```

Replace the `FitScore` class definition with:

```python
class FitLocation(BaseModel):
    """LLM-facing parsed location (every field required, nullable for unknown)."""

    model_config = ConfigDict(extra="forbid")

    city: str | None
    region: str | None
    country: str | None


class FitScore(ExtensibleModel):
    score: int = Field(ge=0, le=100)
    rationale: str
    # New fields default to None so existing callers/faked agents keep working.
    sic_major: str | None = None
    location: FitLocation | None = None
```

Add the `BaseModel` import — change the existing pydantic import so it reads:

```python
from pydantic import BaseModel, ConfigDict, Field
```

Extend `_INSTRUCTIONS` with classification + location guidance (append to the list):

```python
    "Classify the industry the job's domain serves into the single best 2-digit SIC "
    "major-group code (e.g. fintech -> '60', healthcare -> '80', software/business "
    "services -> '73'); set sic_major to that 2-digit string, or null if unclear.",
    "Parse the work location into city, region (US state), and country; leave any "
    "part null if the text does not support it.",
```

Update `compose_fit_input` to accept and include the location:

```python
def compose_fit_input(
    jd_text: str, profile_facts: ProfileFacts, location: str | None = None
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        f"JOB LOCATION: {location or 'unknown'}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_fit.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/fit.py tests/test_discovery_fit.py
git commit -m "Fit schema: emit sic_major + parsed location; thread location into input"
```

---

## Task 8: `run_score` writes SIC + location + alias refresh

**Files:**

- Modify: `src/resume_agent/discovery/pipeline.py`
- Test: `tests/test_discovery_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_discovery_pipeline.py`:

```python
from resume_agent.discovery.fit import FitLocation
from resume_agent.discovery.pipeline import run_score


class _SicLocFitAgent:
    def run(self, prompt):
        return _Result(
            FitScore(
                score=88, rationale="ok", sic_major="73",
                location=FitLocation(city="Austin", region="TX", country="USA"),
            )
        )


def test_run_score_writes_sic_and_location_into_criteria(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={"industry": "fintech", "location": "Austin, TX, USA"},
            ),
        )
        run_score(s, facts, _SicLocFitAgent(), aliases_path=tmp_path / "a.json")
        job = jobs_by_status(s, JobStatus.shortlisted.value)[0]
        assert job.fit_score == 88
        assert job.criteria_json["sic_major"] == "73"
        assert job.criteria_json["industry"] == "fintech"  # preserved
        assert job.criteria_json["location_parts"]["region"] == "TX"
        assert job.criteria_json["location_parts"]["is_us"] is True
        assert job.criteria_json["location_parts"]["raw"] == "Austin, TX, USA"


def test_run_score_refreshes_aliases_when_canonicalizer_given(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    path = tmp_path / "aliases.json"

    def canon(tokens):
        return {"k8s": "kubernetes"} if "k8s" in tokens else {t: t for t in tokens}

    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={"must_have_skills": ["k8s"]},
            ),
        )
        run_score(s, facts, _SicLocFitAgent(), canonicalizer=canon, aliases_path=path)
        import json
        assert json.loads(path.read_text("utf-8"))["k8s"] == "kubernetes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py::test_run_score_writes_sic_and_location_into_criteria -v`
Expected: FAIL (`TypeError`: `run_score` got unexpected keyword `aliases_path`).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/discovery/pipeline.py`, add imports at the top:

```python
from pathlib import Path

from resume_agent.discovery.fit import FitScore
from resume_agent.taxonomy import sic
from resume_agent.taxonomy.location import build_location
from resume_agent.taxonomy.skills import refresh_aliases, split_skills
from resume_agent.tracking.match_gap import Canonicalizer, normalize_skill
from resume_agent.tracking.tables import Job, JobStatus
```

Add a module constant near the top (after imports):

```python
SKILL_ALIASES_PATH = Path("data/skill_aliases.json")
_SIC_TABLE = sic.load_sic_table()
```

Replace the existing `run_score` with:

```python
def run_score(
    session: Session,
    profile_facts: ProfileFacts,
    agent: Runner,
    canonicalizer: Canonicalizer | None = None,
    aliases_path: Path | str = SKILL_ALIASES_PATH,
) -> None:
    for job in jobs_by_status(session, JobStatus.filtered.value):
        location_text = _job_location_text(job)
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts, location_text), agent)
        job.fit_score = fit.score
        job.fit_rationale = fit.rationale
        _write_taxonomy_fields(job, fit, location_text)
        job.status = JobStatus.shortlisted.value
        session.add(job)
    session.commit()
    if canonicalizer is not None:
        _refresh_skill_aliases(
            jobs_by_status(session, JobStatus.shortlisted.value), canonicalizer, aliases_path
        )


def _job_location_text(job: Job) -> str | None:
    criteria = job.criteria_json or {}
    value = job.location or criteria.get("location")
    return str(value).strip() if value and str(value).strip() else None


def _write_taxonomy_fields(job: Job, fit: FitScore, raw_location: str | None) -> None:
    criteria = dict(job.criteria_json or {})
    criteria["sic_major"] = sic.coerce_code(fit.sic_major, _SIC_TABLE)
    if fit.location is not None:
        loc = build_location(
            fit.location.city, fit.location.region, fit.location.country, raw=raw_location
        )
        criteria["location_parts"] = loc.as_dict()
    job.criteria_json = criteria


def _refresh_skill_aliases(
    jobs: list[Job], canonicalizer: Canonicalizer, aliases_path: Path | str
) -> None:
    tokens: set[str] = set()
    for job in jobs:
        criteria = job.criteria_json or {}
        for key in ("must_have_skills", "nice_to_have_skills", "tech_stack"):
            for atomic in split_skills([str(s) for s in (criteria.get(key) or [])]):
                token = normalize_skill(atomic)
                if token:
                    tokens.add(token)
    if tokens:
        refresh_aliases(tokens, canonicalizer, aliases_path)
```

Update `compose_fit_input` import usage is unchanged (already imported). Update the `score_fit`/`compose_fit_input` import line at the top of pipeline.py if needed — it already imports `from resume_agent.discovery.fit import compose_fit_input, score_fit`.

Update `discover` to thread the canonicalizer through:

```python
def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    relevance_agent: Runner | None = None,
    canonicalizer: Canonicalizer | None = None,
) -> dict[str, int]:
    """Run the full funnel over current rows and return final status counts."""
    run_relevance(session, config, relevance_agent)
    run_extract(session, extract_agent)
    run_filter(session, config)
    run_score(session, profile_facts, fit_agent, canonicalizer=canonicalizer)
    return status_counts(session)
```

- [ ] **Step 4: Run the new tests, then the full pipeline suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v`
Expected: PASS — including the pre-existing `test_discover_commits_once_per_stage` (still exactly 3 commits, because `canonicalizer` defaults to `None` so no refresh runs and the file-write path is skipped).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "run_score: write SIC + location to criteria_json; refresh skill aliases"
```

---

## Task 9: Backfill via `discover --rescore`

**Files:**

- Modify: `src/resume_agent/discovery/pipeline.py` (add `backfill_rescore`)
- Modify: `src/resume_agent/cli.py:166-194` (the `discover` command)
- Test: `tests/test_discovery_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_discovery_pipeline.py`:

```python
from resume_agent.discovery.pipeline import backfill_rescore


def test_backfill_rescore_populates_without_changing_fit_or_status(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng",
                status=JobStatus.shortlisted.value,
                criteria_json={"industry": "fintech"},
                fit_score=55, location="Austin, TX, USA",
            ),
        )
        save_job(
            s,
            Job(source="x", jd_text="other", status=JobStatus.filtered.value, criteria_json={}),
        )
        updated = backfill_rescore(s, facts, _SicLocFitAgent(), aliases_path=tmp_path / "a.json")
        job = jobs_by_status(s, JobStatus.shortlisted.value)[0]
        assert updated == 1  # only the shortlisted job
        assert job.fit_score == 55  # unchanged
        assert job.status == JobStatus.shortlisted.value
        assert job.criteria_json["sic_major"] == "73"
        assert job.criteria_json["location_parts"]["region"] == "TX"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py::test_backfill_rescore_populates_without_changing_fit_or_status -v`
Expected: FAIL (`ImportError`: `backfill_rescore` not defined).

- [ ] **Step 3: Write minimal implementation (append to `pipeline.py`)**

Append to `src/resume_agent/discovery/pipeline.py`:

```python
def backfill_rescore(
    session: Session,
    profile_facts: ProfileFacts,
    agent: Runner,
    canonicalizer: Canonicalizer | None = None,
    aliases_path: Path | str = SKILL_ALIASES_PATH,
) -> int:
    """Populate sic_major + location for already-shortlisted jobs.

    Re-runs the fit agent only to harvest the new fields; does NOT change
    fit_score or status. Returns the number of jobs updated.
    """
    updated = 0
    for job in jobs_by_status(session, JobStatus.shortlisted.value):
        if not job.jd_text.strip():
            continue
        location_text = _job_location_text(job)
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts, location_text), agent)
        _write_taxonomy_fields(job, fit, location_text)
        session.add(job)
        updated += 1
    session.commit()
    if canonicalizer is not None:
        _refresh_skill_aliases(
            jobs_by_status(session, JobStatus.shortlisted.value), canonicalizer, aliases_path
        )
    return updated
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Wire the CLI flag**

In `src/resume_agent/cli.py`, add an import alongside the existing pipeline imports (near `cli.py:18-20`):

```python
from resume_agent.discovery.pipeline import backfill_rescore
```

(If `discover`, `reextract`, etc. are imported there as a group, add `backfill_rescore` to that group import instead.)

Also import the canonicalizer if not already at top: `from resume_agent.tracking.canonicalize import build_skill_canonicalizer` already exists (`cli.py:43`).

In `discover_cmd` (`cli.py:166`), add a new option to the signature (after `reextract_existing`):

```python
    rescore_existing: bool = typer.Option(
        False,
        "--rescore",
        help="Backfill SIC + location for already-shortlisted jobs (does not change fit or status).",
    ),
```

And add the guard/branch at the start of the body, before the existing `if reextract_existing:` block:

```python
    if reextract_existing and rescore_existing:
        typer.echo("Choose only one backfill mode: --reextract or --rescore.")
        raise typer.Exit(code=2)

    if rescore_existing:
        profile_facts = load_facts(facts)
        fit_agent = build_fit_agent()
        canonicalizer = build_skill_canonicalizer()
        engine = _engine(db_url)
        with get_session(engine) as session:
            updated = backfill_rescore(session, profile_facts, fit_agent, canonicalizer=canonicalizer)
        typer.echo(f"Backfilled SIC + location for {updated} shortlisted job(s).")
        return
```

Finally, in the normal (non-flag) `discover` path, pass the canonicalizer through so forward runs also grow the alias map. Change the `discover(...)` call (`cli.py:193`) to:

```python
        counts = discover(
            session, config, profile_facts, extract_agent, fit_agent, relevance_agent,
            canonicalizer=build_skill_canonicalizer(),
        )
```

- [ ] **Step 6: Run the full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (no regressions).
Run: `ruff check`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py src/resume_agent/cli.py tests/test_discovery_pipeline.py
git commit -m "Add discover --rescore backfill for SIC + location"
```

---

## Task 10: Widen `ShortlistRow` + canonical skills + flatten SIC/location/size

**Files:**

- Modify: `src/resume_agent/tracking/queries.py`
- Test: `tests/test_tracking_queries.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_tracking_queries.py`, using the file's existing `_session`, `save_job`,
`Job`, `JobStatus`, `Contact`, and `ProfileFacts` imports/helpers:

```python
def test_shortlist_row_exposes_sic_location_and_canonical_skills(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_text('{"k8s": "kubernetes"}', "utf-8")
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng", company="C",
                status=JobStatus.shortlisted.value, location="Austin, TX, USA",
                criteria_json={
                    "sic_major": "73",
                    "company_size": "Series A",
                    "must_have_skills": ["Python, C++ or C", "k8s"],
                    "location_parts": {
                        "city": "Austin", "region": "TX", "country": "US",
                        "is_us": True, "raw": "Austin, TX, USA",
                    },
                },
            ),
        )
        rows = shortlist_rows(s, facts=facts, aliases_path=aliases)
        row = rows[0]
        assert row.sic_major == "73"
        assert row.sic_label == "Business Services"
        assert row.sic_division == "Services"
        assert row.location_country == "US"
        assert row.location_region == "TX"
        assert row.location_city == "Austin"
        assert row.is_us is True
        assert row.company_size == "startup"
        names = {t.name for t in row.skills}
        assert {"python", "c++", "c", "kubernetes"} <= names  # split + canonicalized
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py::test_shortlist_row_exposes_sic_location_and_canonical_skills -v`
Expected: FAIL (`TypeError`: `shortlist_rows` got unexpected keyword `aliases_path`).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/tracking/queries.py`, add imports:

```python
from pathlib import Path

from resume_agent.taxonomy import sic as sic_tax
from resume_agent.taxonomy.company_size import snap as snap_size
from resume_agent.taxonomy.skills import canonical_skill, load_aliases, split_skills
```

Add the new `ShortlistRow` fields (append to the dataclass, after `skills`, all with defaults so existing construction is unaffected):

```python
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    is_us: bool = False
```

> Note: `company_size` is already a `ShortlistRow` field; this task fills it with the snapped bucket instead of raw text. `sic_major` remains `None` for unknown/invalid codes; `sic_label` carries the `Unclassified` display fallback.

Replace `_skill_tags` so it splits then canonicalizes (dedup by canonical token; the canonical token becomes the display `name`, which keeps `filtering.py` unchanged):

```python
def _skill_tags(criteria: dict, tokens: set[str], aliases: dict[str, str]) -> list[SkillTag]:
    profile_canonical = {canonical_skill(t, aliases) for t in tokens}
    tags: list[SkillTag] = []
    seen: set[str] = set()
    for key, required in (
        ("must_have_skills", True),
        ("nice_to_have_skills", False),
        ("tech_stack", False),
    ):
        raw_items = [str(s) for s in (criteria.get(key) or [])]
        for atomic in split_skills(raw_items):
            canonical = canonical_skill(atomic, aliases)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            tags.append(
                SkillTag(name=canonical, covered=canonical in profile_canonical, required=required)
            )
    return tags
```

Update `shortlist_rows` to load the SIC table + aliases once, accept `aliases_path`, and populate the new fields:

```python
def shortlist_rows(
    session: Session,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = "data/skill_aliases.json",
) -> list[ShortlistRow]:
    fit_score_col = cast(Any, Job.fit_score)
    archived_col = cast(Any, Job.archived_at)
    jobs = session.exec(
        select(Job)
        .where(Job.status == JobStatus.shortlisted.value, archived_col.is_(None))
        .order_by(fit_score_col.desc().nullslast())
    ).all()
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    sic_table = sic_tax.load_sic_table()
    rows = []
    for job in jobs:
        job_id = _require_job_id(job)
        criteria = job.criteria_json or {}
        salary = criteria.get("salary_range") or {}
        loc = criteria.get("location_parts") or {}
        code = sic_tax.coerce_code(criteria.get("sic_major"), sic_table)
        division = sic_tax.division_for(code, sic_table)
        rows.append(
            ShortlistRow(
                job_id=job_id,
                company=job.company,
                title=job.title,
                location=job.location,
                fit_score=job.fit_score,
                fit_rationale=job.fit_rationale,
                sponsorship_signal=criteria.get("sponsorship_signal"),
                salary_min=salary.get("minimum"),
                salary_max=salary.get("maximum"),
                salary_currency=salary.get("currency"),
                remote_policy=criteria.get("remote_policy"),
                seniority=criteria.get("seniority"),
                employment_type=criteria.get("employment_type"),
                industry=criteria.get("industry"),
                company_size=snap_size(criteria.get("company_size")),
                posted_at=job.posted_at,
                skills=_skill_tags(criteria, tokens, aliases),
                sic_major=code,
                sic_label=sic_tax.display_label(code, sic_table),
                sic_division=division[1] if division else None,
                location_country=loc.get("country"),
                location_region=loc.get("region"),
                location_city=loc.get("city"),
                is_us=bool(loc.get("is_us")),
            )
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_queries.py -v`
Expected: PASS (new test + existing queries tests unaffected — new fields have defaults).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/queries.py tests/test_tracking_queries.py
git commit -m "Widen ShortlistRow with SIC/location/size; split + canonicalize skills"
```

---

## Task 11: Filtering — `FilterState` + `_passes` + cascade builders

**Files:**

- Modify: `src/resume_agent/dashboard/filtering.py`
- Test: `tests/test_dashboard_filtering.py` (extend; update the `_row` helper)

- [ ] **Step 1: Update the `_row` helper and write failing tests**

In `tests/test_dashboard_filtering.py`, update the `_row` helper to accept the new fields (add keyword params with defaults and pass them to `ShortlistRow`):

```python
def _row(
    job_id: int = 1,
    fit: int | None = 80,
    salary_min: int | None = None,
    salary_max: int | None = None,
    remote: str | None = None,
    seniority: str | None = None,
    emp: str | None = None,
    industry: str | None = None,
    sponsorship: str | None = None,
    posted: datetime | None = None,
    skills: list[SkillTag] | None = None,
    currency: str | None = "USD",
    sic_major: str | None = None,
    sic_label: str | None = None,
    sic_division: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    is_us: bool = False,
    company_size: str | None = None,
) -> ShortlistRow:
    return ShortlistRow(
        job_id=job_id,
        company="C",
        title="T",
        location="L",
        fit_score=fit,
        fit_rationale="r",
        sponsorship_signal=sponsorship,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        remote_policy=remote,
        seniority=seniority,
        employment_type=emp,
        industry=industry,
        company_size=company_size,
        posted_at=posted,
        skills=skills or [],
        sic_major=sic_major,
        sic_label=sic_label,
        sic_division=sic_division,
        location_country=country,
        location_region=region,
        location_city=city,
        is_us=is_us,
    )
```

Append new tests:

```python
from resume_agent.dashboard.filtering import (
    available_industries,
    available_countries,
    available_states,
    available_cities,
)


def test_sic_filter_unknown_passes():
    rows = [_row(job_id=1, sic_major="73"), _row(job_id=2, sic_major="60"), _row(job_id=3)]
    out = apply_filters(rows, FilterState(industry={"73"}))
    assert {r.job_id for r in out} == {1, 3}  # unclassified (None) passes


def test_location_filters_and_together_unknown_passes():
    rows = [
        _row(job_id=1, country="US", region="TX", city="Austin"),
        _row(job_id=2, country="US", region="CA", city="San Jose"),
        _row(job_id=3, country="GB", region=None, city="London"),
        _row(job_id=4),  # all unknown -> passes
    ]
    out = apply_filters(rows, FilterState(country={"US"}, region={"TX"}))
    assert {r.job_id for r in out} == {1, 4}


def test_company_size_filter():
    rows = [_row(job_id=1, company_size="startup"), _row(job_id=2, company_size="enterprise")]
    out = apply_filters(rows, FilterState(company_size={"startup"}))
    assert {r.job_id for r in out} == {1}


def test_available_industries_grouped_by_division_sorted():
    rows = [_row(sic_major="73", sic_label="Business Services", sic_division="Services"),
            _row(sic_major="60", sic_label="Depository Institutions",
                 sic_division="Finance, Insurance & Real Estate")]
    grouped = available_industries(rows)
    divisions = [d for d, _ in grouped]
    assert "Services" in divisions and "Finance, Insurance & Real Estate" in divisions
    services = dict(grouped)["Services"]
    assert ("73", "Business Services") in services


def test_location_cascade_builders_narrow():
    rows = [
        _row(country="US", region="TX", city="Austin"),
        _row(country="US", region="CA", city="San Jose"),
        _row(country="GB", region=None, city="London"),
    ]
    assert available_countries(rows) == ["GB", "US"]
    assert available_states(rows, {"US"}) == ["CA", "TX"]
    assert available_cities(rows, {"US"}, {"TX"}) == ["Austin"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_filtering.py -v`
Expected: FAIL (SIC filter still reads `row.industry` and `available_industries` is missing).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/dashboard/filtering.py`, update `FilterState` — keep the existing `industry` field, but treat its values as SIC major-group codes; add the location/size sets:

```python
@dataclass
class FilterState:
    salary_min: int | None = None
    remote: set[str] = field(default_factory=set)
    sponsorship: set[str] = field(default_factory=set)
    seniority: set[str] = field(default_factory=set)
    employment_type: set[str] = field(default_factory=set)
    industry: set[str] = field(default_factory=set)
    country: set[str] = field(default_factory=set)
    region: set[str] = field(default_factory=set)
    city: set[str] = field(default_factory=set)
    company_size: set[str] = field(default_factory=set)
    fit_min: int | None = None
    skills: set[str] = field(default_factory=set)
    sort: str = "fit"
    preset: str = "balanced"
```

In `_passes`, replace the categorical tuple with the new set (note `state.industry` now maps to `row.sic_major`, plus the location/size fields):

```python
    for selected, value in (
        (state.remote, row.remote_policy),
        (state.sponsorship, row.sponsorship_signal),
        (state.seniority, row.seniority),
        (state.employment_type, row.employment_type),
        (state.industry, row.sic_major),
        (state.country, row.location_country),
        (state.region, row.location_region),
        (state.city, row.location_city),
        (state.company_size, row.company_size),
    ):
        if selected and value is not None and value not in selected:
            return False
```

Add the cascade option builders (append to the module):

```python
def available_industries(rows: list[ShortlistRow]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Present SIC codes grouped by division: [(division_label, [(code, label), ...]), ...]."""
    by_division: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        if row.sic_major and row.sic_division and row.sic_label:
            by_division.setdefault(row.sic_division, set()).add((row.sic_major, row.sic_label))
    return [
        (division, sorted(codes))
        for division, codes in sorted(by_division.items())
    ]


def available_countries(rows: list[ShortlistRow]) -> list[str]:
    return sorted({r.location_country for r in rows if r.location_country})


def available_states(rows: list[ShortlistRow], countries: set[str]) -> list[str]:
    return sorted(
        {
            r.location_region
            for r in rows
            if r.location_region and (not countries or r.location_country in countries)
        }
    )


def available_cities(
    rows: list[ShortlistRow], countries: set[str], states: set[str]
) -> list[str]:
    return sorted(
        {
            r.location_city
            for r in rows
            if r.location_city
            and (not countries or r.location_country in countries)
            and (not states or r.location_region in states)
        }
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_filtering.py -v`
Expected: PASS (existing + new tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/dashboard/filtering.py tests/test_dashboard_filtering.py
git commit -m "Filtering: SIC/location/company-size filters + cascade builders"
```

---

## Task 12: Control-desk cascades (`dashboard/pages.py`)

**Files:**

- Modify: `src/resume_agent/dashboard/pages.py:125-180` (filter control desk + `FilterState` construction)

> This is Streamlit wiring (manual-verified). The pure option-builders it calls are already covered by Task 11. Keep edits surgical: only the industry/location/size controls change.

- [ ] **Step 1: Replace the flat Industry control with the SIC cascade**

In `src/resume_agent/dashboard/pages.py`, locate the industry block (`pages.py:146-148`):

```python
            industry_options = sorted({r.industry for r in rows if r.industry})
            industry = set(st.multiselect("Industry", industry_options, key="f_industry"))
```

Replace it with a Division→Major Group cascade driven by `available_industries(rows)`:

```python
            grouped = available_industries(rows)
            division_labels = [d for d, _ in grouped]
            chosen_divisions = set(
                st.multiselect("Industry — division", division_labels, key="f_division")
            )
            code_options: list[tuple[str, str]] = []
            for division, codes in grouped:
                if not chosen_divisions or division in chosen_divisions:
                    code_options.extend(codes)
            code_labels = {code: label for code, label in code_options}
            industry = set(
                st.multiselect(
                    "Industry — group",
                    sorted(code_labels),
                    format_func=lambda c: code_labels.get(c, c),
                    key="f_sic",
                )
            )
```

Add the import at the top of `pages.py` (the file already imports `available_skill_cloud` from `dashboard.filtering` near `pages.py:12`; extend that import group):

```python
from resume_agent.dashboard.filtering import (
    available_cities,
    available_countries,
    available_industries,
    available_skill_cloud,
    available_states,
)
```

- [ ] **Step 2: Add the location cascade + company-size control**

After the industry block (still inside the control desk), add:

```python
        rloc = st.columns(3, gap="medium", vertical_alignment="top")
        with rloc[0]:
            country = set(st.multiselect("Country", available_countries(rows), key="f_country"))
        with rloc[1]:
            region = set(
                st.multiselect("State (US)", available_states(rows, country), key="f_region")
            )
        with rloc[2]:
            city = set(
                st.multiselect("City", available_cities(rows, country, region), key="f_city")
            )
        size_options = sorted({r.company_size for r in rows if r.company_size})
        company_size = set(st.multiselect("Company size", size_options, key="f_size"))
```

- [ ] **Step 3: Update the `FilterState(...)` construction**

In the `return FilterState(...)` (`pages.py:169-180`), keep `industry=industry,` and add the new location/size fields:

```python
        industry=industry,
        country=country,
        region=region,
        city=city,
        company_size=company_size,
```

- [ ] **Step 4: Run the full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (no regressions; `pages.py` has no direct unit tests but must import cleanly).
Run: `ruff check`
Expected: clean.

- [ ] **Step 5: Manual dashboard verification (headless smoke)**

Run: `.venv/Scripts/python.exe -c "import resume_agent.dashboard.pages"`
Expected: imports without error (catches signature/name mistakes).
Then, if a dev DB is available, launch `resume-agent dashboard`, open the Shortlist page, and confirm: the Industry division→group cascade, the Country→State→City cascade, and the Company-size control all render and narrow results; the skill cloud shows deduped canonical chips.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/dashboard/pages.py
git commit -m "Shortlist control desk: SIC + location cascades + company-size filter"
```

---

## Self-Review

**Spec coverage:**

- SIC 2-digit + Division derived → Task 1; classify at `run_score` → Task 7/8; invalid/unknown codes stored as `None` with `Unclassified` display fallback → Tasks 1/10; cascade UI → Tasks 11/12. ✓
- Skill split (atomic + safety net) → Tasks 2, 6, 10. ✓
- Skill synonyms (machine-grown persisted alias map, merge, refresh after score) → Tasks 3, 8; applied on read → Task 10. ✓
- Alias map at `data/skill_aliases.json` grown by merge → Tasks 3, 8. ✓
- Location parse at `run_score` + ISO/USPS/is_us → Tasks 4, 7, 8; Country→State→City cascade, unknown-passes → Tasks 11, 12. ✓
- Company-size buckets + optional filter → Tasks 5, 10, 11, 12. ✓
- Backfill (re-score existing shortlisted, no fit/status change) + alias refresh → Task 9. ✓
- Storage in `criteria_json`, no migration → Tasks 8, 10. ✓
- Bundled reference inside package (data/ gitignored) → Task 1 (+ Hatchling wheel-data check). ✓
- Offline tests, agents faked, data fixtured → every task. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; SIC data file is fully enumerated.

**Type consistency:**

- `FitScore.sic_major: str | None`, `FitScore.location: FitLocation | None` — defined Task 7, used Tasks 8/9. ✓
- `criteria_json` keys `sic_major` (str|None) + `location_parts` (dict from `StructuredLocation.as_dict()`) — written Tasks 8/9, read Task 10. ✓
- `StructuredLocation.as_dict()` keys `{city, region, country, is_us, raw}` — defined Task 4, consumed Task 10 (reads `country/region/city/is_us`). ✓
- `ShortlistRow` new fields (`sic_major/sic_label/sic_division/location_country/location_region/location_city/is_us`) — defined Task 10, used Tasks 11/12. ✓
- `FilterState.industry` keeps the existing interface but now carries SIC major-group codes; `country/region/city/company_size` are defined Task 11 and constructed Task 12. ✓
- `_skill_tags(criteria, tokens, aliases)` signature — changed Task 10 (all call sites updated within `shortlist_rows`). ✓
- `run_score(..., canonicalizer=None, aliases_path=...)` and `discover(..., canonicalizer=None)` — defined Task 8, called Task 9 CLI. ✓
- `available_industries/countries/states/cities` — defined Task 11, called Task 12. ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-21-taxonomy-normalized-filters.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
