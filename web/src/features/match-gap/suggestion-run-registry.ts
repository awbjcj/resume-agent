import { create } from "zustand";

import type { RunRecord } from "@/lib/runs/store";
import {
  targetId,
  type SuggestionState,
  type SuggestionTarget,
} from "./aggregate";

export interface SuggestionRunEntry {
  target: SuggestionTarget;
  runId?: string;
  state: "queued" | "syncing" | "failed" | "cancelled" | "not_found";
  error?: string;
}

interface SuggestionRunRegistry {
  entries: Record<string, SuggestionRunEntry>;
  launchError: string | null;
  register: (target: SuggestionTarget, runId: string) => void;
  fail: (target: SuggestionTarget, error?: string) => void;
  cancel: (target: SuggestionTarget) => void;
  notFound: (target: SuggestionTarget) => void;
  syncing: (target: SuggestionTarget) => void;
  clear: (target: SuggestionTarget) => void;
  setLaunchError: (error: string | null) => void;
  entryFor: (target: SuggestionTarget) => SuggestionRunEntry | undefined;
}

export const useSuggestionRunRegistry = create<SuggestionRunRegistry>((set, get) => ({
  entries: {},
  launchError: null,
  register: (target, runId) =>
    set((state) => ({
      entries: {
        ...state.entries,
        [targetId(target)]: { target, runId, state: "queued" },
      },
    })),
  fail: (target, error) =>
    set((state) => ({
      entries: {
        ...state.entries,
        [targetId(target)]: {
          ...state.entries[targetId(target)],
          target,
          state: "failed",
          error,
        },
      },
    })),
  cancel: (target) =>
    set((state) => ({
      entries: {
        ...state.entries,
        [targetId(target)]: {
          ...state.entries[targetId(target)],
          target,
          state: "cancelled",
        },
      },
    })),
  notFound: (target) =>
    set((state) => ({
      entries: {
        ...state.entries,
        [targetId(target)]: { target, state: "not_found" },
      },
    })),
  syncing: (target) =>
    set((state) => ({
      entries: {
        ...state.entries,
        [targetId(target)]: {
          ...state.entries[targetId(target)],
          target,
          state: "syncing",
        },
      },
    })),
  clear: (target) =>
    set((state) => {
      const entries = { ...state.entries };
      delete entries[targetId(target)];
      return { entries };
    }),
  setLaunchError: (launchError) => set({ launchError }),
  entryFor: (target) => get().entries[targetId(target)],
}));

export function effectiveSuggestionState(
  persisted: "ready" | "stale" | undefined,
  entry: SuggestionRunEntry | undefined,
  liveStatus: RunRecord["status"] | undefined,
): SuggestionState {
  if (liveStatus === "queued") return "queued";
  if (liveStatus === "running" || liveStatus === "cancelling") return "researching";
  if (liveStatus === "failed") return "failed";
  if (liveStatus === "cancelled") return "cancelled";
  if (entry?.state === "syncing") return "researching";
  if (entry?.state) return entry.state;
  if (liveStatus === "succeeded") return "researching";
  return persisted ?? "none";
}
