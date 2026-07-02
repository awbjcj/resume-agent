import { useState } from "react";

/**
 * Seeds local draft state from server data exactly once per distinct fetched
 * value, without an effect. Setting state during render (not in useEffect) is
 * React's documented pattern for "adjust state when a prop/query result
 * changes" — it re-runs the component before paint instead of committing an
 * extra render. Comparison is by value (JSON), not reference, so a refetch
 * that resolves to the same content never clobbers an in-progress edit.
 */
export function useDraft<T>(data: T | undefined) {
  const [draft, setDraft] = useState<T | null>(null);
  const [seenKey, setSeenKey] = useState<string | undefined>(undefined);
  const dataKey = data === undefined ? undefined : JSON.stringify(data);

  if (dataKey !== undefined && dataKey !== seenKey) {
    setSeenKey(dataKey);
    setDraft(data as T);
  }

  const dirty = draft !== null && JSON.stringify(draft) !== dataKey;
  return {
    draft,
    setDraft,
    dirty,
    reset: () => setDraft(data ?? null),
  } as const;
}
