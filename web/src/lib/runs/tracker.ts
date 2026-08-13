import { api, unwrap } from "@/lib/api/client";
import { stateToStatus, watchRun } from "./sse";
import { useRunStore, type RunRecord } from "./store";

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
}
