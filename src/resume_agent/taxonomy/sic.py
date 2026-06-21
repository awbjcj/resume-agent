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
