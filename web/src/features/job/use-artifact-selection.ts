import { useCallback, useMemo, useState } from "react";

/**
 * Checkbox selection for a list of deletable artifacts.
 *
 * The selection is stored raw and intersected with `deletableIds` on read
 * rather than being pruned by an effect. That matters because the deletable
 * set changes underneath this list — applying a version disables its checkbox,
 * and a background revision run adds rows — and a selection that outlived its
 * row would be submitted to a bulk delete that then fails on the whole batch.
 * Deriving it makes that state unrepresentable instead of merely unlikely.
 */
export function useArtifactSelection(deletableIds: readonly number[]) {
  const [raw, setRaw] = useState<ReadonlySet<number>>(() => new Set());

  const selectedIds = useMemo(
    () => deletableIds.filter((id) => raw.has(id)),
    [deletableIds, raw],
  );

  const toggle = useCallback((id: number) => {
    setRaw((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setRaw(new Set()), []);

  const toggleAll = useCallback(() => {
    setRaw((current) =>
      deletableIds.every((id) => current.has(id))
        ? new Set()
        : new Set(deletableIds),
    );
  }, [deletableIds]);

  return {
    selectedIds,
    isSelected: (id: number) => raw.has(id),
    allSelected:
      deletableIds.length > 0 && selectedIds.length === deletableIds.length,
    toggle,
    toggleAll,
    clear,
  };
}
