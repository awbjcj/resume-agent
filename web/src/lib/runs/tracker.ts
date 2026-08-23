import { api, unwrap } from "@/lib/api/client";
import { forgetInvalidation } from "./invalidation";
import { stateToStatus, watchRun } from "./sse";
import { useRunStore, type RunRecord } from "./store";

/** How long a finished run stays on screen at 100% before the bar collapses. */
export const TERMINAL_DISPLAY_MS = 4000;

export type TerminalListener = (runs: RunRecord[]) => void;

const terminalListeners = new Set<TerminalListener>();
/** Runs already put through the lifecycle, so SSE and the poller cannot double-fire. */
const completed = new Set<string>();

export function addTerminalListener(listener: TerminalListener): () => void {
  terminalListeners.add(listener);
  return () => {
    terminalListeners.delete(listener);
  };
}

/** Failed revisions carry the retry instruction in `meta`; the retry UI needs them. */
function isDurableFailure(run: RunRecord): boolean {
  return (
    run.status === "failed" && ["revise", "coverLetterRevise"].includes(run.kind)
  );
}

/**
 * The single terminal path, reached from the SSE stream and the poller alike.
 *
 * Batched because a reconnect can surface several completions at once and the
 * announcement cap is a property of the batch, not of each run. Listeners get
 * the batch; this function owns only store state and the display timer, so the
 * tracker never needs a QueryClient or a toast library.
 */
export function completeRuns(runs: readonly RunRecord[]): void {
  const fresh = runs.filter((run) => !completed.has(run.runId));
  if (fresh.length === 0) return;
  for (const run of fresh) {
    completed.add(run.runId);
    useRunStore.getState().upsert(run);
  }
  for (const listener of terminalListeners) listener([...fresh]);
  for (const run of fresh) {
    forgetInvalidation(run.runId);
    if (isDurableFailure(run)) continue;
    setTimeout(
      () => useRunStore.getState().remove(run.runId),
      TERMINAL_DISPLAY_MS,
    );
  }
}

export interface RunSeed {
  runId: string;
  kind: string;
}

interface RunStatusPayload extends RunSeed {
  state: string;
  label: string;
  percent: number;
  current: number;
  total: number;
  etaText?: string | null;
  result?: RunRecord["result"];
  error?: string | null;
  meta?: RunRecord["meta"];
}

interface TrackedRun {
  seed: RunSeed;
  callbacks: Set<(run: RunRecord) => void>;
  unsubscribe: () => void;
  reconnects: number;
}

const tracked = new Map<string, TrackedRun>();

function finish(entry: TrackedRun, run: RunRecord): void {
  entry.unsubscribe();
  tracked.delete(entry.seed.runId);
  completeRuns([run]);
  for (const callback of entry.callbacks) callback(run);
}

function recordFromStatus(payload: RunStatusPayload): RunRecord {
  return {
    runId: payload.runId,
    kind: payload.kind,
    status: stateToStatus(payload.state),
    percent: payload.percent ?? 0,
    phase: payload.label ?? "",
    current: payload.current ?? 0,
    total: payload.total ?? 0,
    etaText: payload.etaText ?? null,
    error: payload.error ?? undefined,
    result: payload.result ?? null,
    ...(payload.meta !== undefined ? { meta: payload.meta } : {}),
  };
}

function subscribe(entry: TrackedRun): void {
  entry.unsubscribe = watchRun(
    entry.seed.runId,
    entry.seed.kind,
    (run) => finish(entry, run),
    () => void reconcile(entry),
  );
}

async function reconcile(entry: TrackedRun): Promise<void> {
  if (tracked.get(entry.seed.runId) !== entry) return;
  try {
    const payload = (await unwrap(
      api.GET("/api/runs/{run_id}", {
        params: { path: { run_id: entry.seed.runId } },
      }),
    )) as RunStatusPayload;
    const run = recordFromStatus(payload);
    useRunStore.getState().upsert(run);
    if (["succeeded", "failed", "cancelled"].includes(run.status)) {
      finish(entry, run);
      return;
    }
  } catch {
    // A transport error is not evidence that the backend run failed.
  }
  if (entry.reconnects < 1 && tracked.get(entry.seed.runId) === entry) {
    entry.reconnects += 1;
    subscribe(entry);
  } else {
    tracked.delete(entry.seed.runId);
  }
}

export function trackRun(seed: RunSeed, onDone?: (run: RunRecord) => void): void {
  const existing = tracked.get(seed.runId);
  if (existing) {
    if (onDone) existing.callbacks.add(onDone);
    return;
  }
  const entry: TrackedRun = {
    seed,
    callbacks: new Set(onDone ? [onDone] : []),
    unsubscribe: () => undefined,
    reconnects: 0,
  };
  tracked.set(seed.runId, entry);
  subscribe(entry);
}

export function isTracking(runId: string): boolean {
  return tracked.has(runId);
}

export function resetRunTrackerForTests(): void {
  for (const entry of tracked.values()) entry.unsubscribe();
  tracked.clear();
  terminalListeners.clear();
  completed.clear();
}
