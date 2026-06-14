"""Broadsheet design system: theme CSS, palette, and pure HTML helpers.

All functions here are pure (no Streamlit calls at import or call time) so the
module imports cleanly and the helpers are unit-testable without a server.
"""


def column_count(width: int, card_min: int = 360, max_cols: int = 4) -> int:
    """How many card columns fit in ``width`` px, clamped to [1, max_cols]."""
    if width <= 0:
        return 1
    return max(1, min(max_cols, width // card_min))
