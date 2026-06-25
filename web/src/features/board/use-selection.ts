import { useCallback, useRef, useState } from "react";

type Mode = "ids" | "query";

export function useSelection() {
  const [mode, setMode] = useState<Mode>("ids");
  const [ids, setIds] = useState<Set<number>>(new Set());
  const [matchingTotal, setMatchingTotal] = useState(0);
  const lastIndex = useRef<number | null>(null);

  const clear = useCallback(() => {
    setMode("ids");
    setIds(new Set());
    setMatchingTotal(0);
    lastIndex.current = null;
  }, []);

  const toggle = useCallback(
    (id: number, index?: number, shift?: boolean, ordered?: number[]) => {
      setMode("ids");
      setMatchingTotal(0);
      setIds((prev) => {
        const next = new Set(prev);
        if (shift && index != null && lastIndex.current != null && ordered) {
          const [a, b] = [lastIndex.current, index].sort((x, y) => x - y);
          for (let i = a; i <= b; i += 1) next.add(ordered[i]);
        } else if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
      });
      if (index != null) lastIndex.current = index;
    },
    [],
  );

  const selectPage = useCallback((pageIds: number[]) => {
    setMode("ids");
    setMatchingTotal(0);
    setIds(new Set(pageIds));
  }, []);

  const selectAllMatching = useCallback((total: number) => {
    setMode("query");
    setMatchingTotal(total);
  }, []);

  const reconcile = useCallback(
    (loadedIds: number[], total: number) => {
      const loaded = new Set(loadedIds);
      if (mode === "query") {
        setMatchingTotal(total);
        return;
      }
      setIds((prev) => {
        const next = new Set([...prev].filter((id) => loaded.has(id)));
        return next.size === prev.size ? prev : next;
      });
    },
    [mode],
  );

  const isSelected = useCallback((id: number) => (mode === "query" ? true : ids.has(id)), [ids, mode]);

  return {
    mode,
    ids,
    count: mode === "query" ? matchingTotal : ids.size,
    isAllMatching: mode === "query",
    toggle,
    selectPage,
    selectAllMatching,
    reconcile,
    clear,
    isSelected,
  };
}
