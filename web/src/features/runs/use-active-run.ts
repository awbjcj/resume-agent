import { useRunStore, type RunRecord } from "@/lib/runs/store";

/** Finds the (at most one) tracked run of the given kind, if any. */
export function useActiveRun(kind: string): RunRecord | undefined {
  return useRunStore((s) => Object.values(s.runs).find((r) => r.kind === kind));
}
