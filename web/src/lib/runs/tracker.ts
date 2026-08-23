import { api, fetchAllPages } from "@/lib/api/client";
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
  /** Next reconnect delay; grows on each failure, resets on any received frame. */
  delayMs: number;
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

export const POLL_INTERVAL_MS = 15_000;
export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_MAX_MS = 30_000;

function nextDelay(current: number): number {
  const raw = Math.min(current * 2, RECONNECT_MAX_MS);
  // Jitter so a backend restart does not bring every tab back in lockstep.
  return Math.round(raw * (0.8 + Math.random() * 0.4));
}

function subscribe(entry: TrackedRun): void {
  entry.unsubscribe = watchRun(
    entry.seed.runId,
    entry.seed.kind,
    (run) => finish(entry, run),
    () => scheduleReconnect(entry),
    () => {
      entry.delayMs = RECONNECT_BASE_MS;
    },
  );
}

/**
 * A dropped stream is not evidence the run failed, and there is no honest
 * number of retries at which it becomes evidence. The old `reconnects < 1` cap
 * simply picked a point to start being silently wrong — the bar froze and the
 * completion was lost. Unbounded retry is affordable because the poller
 * independently reconciles every tracked run, so a stream that never comes back
 * costs one request per POLL_INTERVAL_MS, not a lost completion.
 */
function scheduleReconnect(entry: TrackedRun): void {
  if (tracked.get(entry.seed.runId) !== entry) return;
  // Ask the server what actually happened right now, rather than waiting out a
  // poll interval: the most common reason a stream dies is that the run ended.
  void pollRunsNow();
  const delay = entry.delayMs;
  entry.delayMs = nextDelay(entry.delayMs);
  setTimeout(() => {
    if (tracked.get(entry.seed.runId) !== entry) return;
    subscribe(entry);
  }, delay);
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
    delayMs: RECONNECT_BASE_MS,
  };
  tracked.set(seed.runId, entry);
  subscribe(entry);
  startRunPoller();
}

const TERMINAL_STATUSES: readonly RunRecord["status"][] = [
  "succeeded",
  "failed",
  "cancelled",
];

let pollTimer: ReturnType<typeof setInterval> | null = null;
/** Bumped whenever polling stops, so an in-flight poll knows not to apply. */
let pollGeneration = 0;

/**
 * Reconcile every run the server considers live or newly finished.
 *
 * This is the correctness guarantee; SSE is only the latency optimisation. It
 * covers three cases a live stream cannot: a run whose stream died, a run that
 * finished while no client was connected, and a run launched from another tab
 * or device.
 */
export async function pollRunsNow(): Promise<void> {
  const generation = pollGeneration;
  const fetchPage = (page: number) =>
    api.GET("/api/runs", { params: { query: { page, pageSize: 200 } } });
  let items: RunStatusPayload[];
  try {
    // One immediate retry, as the old rehydrate path had: a single failed
    // request on page load should not cost the user a 15s blank bar.
    try {
      items = await fetchAllPages<RunStatusPayload>(fetchPage);
    } catch {
      items = await fetchAllPages<RunStatusPayload>(fetchPage);
    }
  } catch {
    // A transport error is not evidence about any run.
    return;
  }
  // The poller was torn down while this request was in flight (the app
  // unmounted). Applying now would resurrect tracking for a dead client.
  if (generation !== pollGeneration) return;

  const finished: RunRecord[] = [];
  for (const payload of items) {
    const run = recordFromStatus(payload);
    if (TERMINAL_STATUSES.includes(run.status)) {
      const entry = tracked.get(run.runId);
      if (entry) {
        entry.unsubscribe();
        tracked.delete(run.runId);
        for (const callback of entry.callbacks) callback(run);
      }
      finished.push(run);
      continue;
    }
    useRunStore.getState().upsert(run);
    if (!tracked.has(run.runId)) trackRun({ runId: run.runId, kind: run.kind });
  }
  // One batch, so the announcement cap sees the whole reconnect at once rather
  // than deciding run-by-run without knowing how many siblings follow.
  completeRuns(finished);
  if (tracked.size === 0) stopRunPoller();
}

export function startRunPoller(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => void pollRunsNow(), POLL_INTERVAL_MS);
}

export function stopRunPoller(): void {
  pollGeneration += 1;
  if (pollTimer === null) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

export function isTracking(runId: string): boolean {
  return tracked.has(runId);
}

export function resetRunTrackerForTests(): void {
  for (const entry of tracked.values()) entry.unsubscribe();
  tracked.clear();
  stopRunPoller();
  terminalListeners.clear();
  completed.clear();
}
