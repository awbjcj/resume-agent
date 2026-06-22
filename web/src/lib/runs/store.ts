import { create } from "zustand";

export interface RunRecord {
  runId: string;
  kind: string;
  status: "running" | "succeeded" | "failed";
  percent: number;
  phase: string;
  error?: string;
}

interface RunState {
  runs: Record<string, RunRecord>;
  upsert: (r: RunRecord) => void;
  remove: (id: string) => void;
}

export const useRunStore = create<RunState>((set) => ({
  runs: {},
  upsert: (r) => set((s) => ({ runs: { ...s.runs, [r.runId]: r } })),
  remove: (id) =>
    set((s) => {
      const { [id]: _removed, ...rest } = s.runs;
      return { runs: rest };
    }),
}));
