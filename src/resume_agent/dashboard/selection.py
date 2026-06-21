"""Pure helper for the Triage page's bulk-delete gate.

Kept Streamlit-free so the rule is unit-testable; the render layer derives the
selected ids directly from the per-card checkbox widget state.
"""


def all_deletable(selected_ids: set[int], deletable_ids: set[int]) -> bool:
    """True only if something is selected and every selected job may be hard-deleted."""
    return bool(selected_ids) and selected_ids <= deletable_ids
