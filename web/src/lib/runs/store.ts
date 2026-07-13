import { create } from "zustand";

export type PullRunResult = {
  totals?: Record<string, number>;
  upgraded?: Record<string, number>;
  skipped?: Record<string, number>;
  failures?: Record<string, Record<string, string>>;
};

export type RunMeta = {
  jobId?: number;
  versionId?: number;
  coverLetterId?: number;
  instruction?: string;
  reReview?: boolean;
  [key: string]: unknown;
};

export interface RunRecord {
  runId: string;
  kind: string;
  status: "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  percent: number;
  phase: string;
  current: number;
  total: number;
  etaText: string | null;
  error?: string;
  result?: PullRunResult | Record<string, unknown> | null;
  meta?: RunMeta | null;
  subject?: { kind: "skill" | "theme"; key: string };
  /** Epoch ms of the last upsert for this run — client-side only. */
  updatedAt?: number;
}

interface RunState {
  runs: Record<string, RunRecord>;
  upsert: (r: RunRecord) => void;
  remove: (id: string) => void;
}

export const useRunStore = create<RunState>((set) => ({
  runs: {},
  upsert: (r) =>
    set((s) => ({
      runs: { ...s.runs, [r.runId]: { ...s.runs[r.runId], ...r, updatedAt: Date.now() } },
    })),
  remove: (id) =>
    set((s) => {
      const runs = { ...s.runs };
      delete runs[id];
      return { runs };
    }),
}));
