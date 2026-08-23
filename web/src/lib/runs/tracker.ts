import { api, fetchAllPages, unwrap } from "@/lib/api/client";
import { forgetInvalidation } from "./invalidation";
import { isRevisionKind } from "./revisions";
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
  return run.status === "failed" && isRevisionKind(run.kind);
}

/** Put a terminal run on screen and retire its bar, without announcing it. */
function retain(run: RunRecord): void {
  completed.add(run.runId);
  useRunStore.getState().upsert(run);
  forgetInvalidation(run.runId);
  if (isDurableFailure(run)) return;
  setTimeout(() => useRunStore.getState().remove(run.runId), TERMINAL_DISPLAY_MS);
}

/**
 * Restore terminal runs the server says were already announced.
 *
 * A failed revision stays in `/api/runs` after acknowledgement because the
 * retry UI needs it, so announcing every terminal run in the payload would
 * re-toast the same failure on every page load until it was swept. The run
 * still belongs on screen — it just isn't news any more.
 */
export function restoreAnnouncedRuns(runs: readonly RunRecord[]): void {
  for (const run of runs) {
    if (completed.has(run.runId)) continue;
    retain(run);
  }
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
  for (const run of fresh) retain(run);
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
  /** Set once the client has told the user about this run's completion. */
  announcedAt?: string | null;
}

interface TrackedRun {
  seed: RunSeed;
  callbacks: Set<(run: RunRecord) => void>;
  unsubscribe: () => void;
  /** Next reconnect delay; grows on each failure, resets on any received frame. */
  delayMs: number;
}

const tracked = new Map<string, TrackedRun>();

/** Stop watching a run, without deciding anything about its outcome. */
function detach(entry: TrackedRun): void {
  entry.unsubscribe();
  tracked.delete(entry.seed.runId);
}

/**
 * Terminal handling for one run.
 *
 * Order matters and is shared with the poller's batch path: the store is
 * updated first, then per-run callbacks run — so a callback never observes a
 * run the store still thinks is in flight.
 */
function finish(entry: TrackedRun, run: RunRecord): void {
  detach(entry);
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
/**
 * Bumped only when polling is torn down from outside (unmount, test reset), so
 * an in-flight poll knows its results belong to a client that is gone.
 *
 * Deliberately NOT bumped when a poll stops the idle interval itself: that
 * would let whichever concurrent poll finishes first invalidate the others,
 * and a poll that had just fetched a completion would throw it away — losing
 * exactly the completion this whole path exists to deliver.
 */
let pollGeneration = 0;
/** The poll currently in flight, so concurrent callers share one request. */
let pollInFlight: Promise<void> | null = null;

/**
 * Reconcile every run the server considers live or newly finished.
 *
 * This is the correctness guarantee; SSE is only the latency optimisation. It
 * covers two cases a live stream cannot: a run whose stream died, and a run
 * that finished while no client was connected. The interval stops once nothing
 * is tracked, so a run started in another tab is picked up on the next load or
 * the next local launch, not continuously.
 */
export function pollRunsNow(): Promise<void> {
  // Coalesce. A backend restart errors every tracked run's stream at once, and
  // each one asks for a reconciliation; N identical requests would return the
  // same listing N times and race each other applying it.
  pollInFlight ??= reconcileRuns().finally(() => {
    pollInFlight = null;
  });
  return pollInFlight;
}

async function reconcileRuns(): Promise<void> {
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
  if (generation !== pollGeneration) return;

  const listed = new Set<string>();
  const announce: RunRecord[] = [];
  const restore: RunRecord[] = [];
  const settled: { entry: TrackedRun; run: RunRecord }[] = [];

  for (const payload of items) {
    const run = recordFromStatus(payload);
    listed.add(run.runId);
    if (!TERMINAL_STATUSES.includes(run.status)) {
      useRunStore.getState().upsert(run);
      if (!tracked.has(run.runId)) trackRun({ runId: run.runId, kind: run.kind });
      continue;
    }
    const entry = tracked.get(run.runId);
    if (entry) {
      detach(entry);
      settled.push({ entry, run });
    }
    // Already acknowledged means the server is listing it for its own reasons
    // (a failed revision the retry UI still needs), not because it is news.
    if (payload.announcedAt) restore.push(run);
    else announce.push(run);
  }

  restoreAnnouncedRuns(restore);
  // One batch, so the announcement cap sees the whole reconnect at once rather
  // than deciding run-by-run without knowing how many siblings follow.
  completeRuns(announce);
  for (const { entry, run } of settled) {
    for (const callback of entry.callbacks) callback(run);
  }

  await resolveUnlisted(listed, generation);

  if (tracked.size === 0) stopPolling();
}

/**
 * Settle tracked runs the listing did not mention.
 *
 * Absence is ambiguous: another tab acknowledged the completion, or the 24h
 * sweep removed the record. Either way the listing will never mention it
 * again, so without asking directly the entry stays tracked forever — the
 * interval never idles and its progress bar never leaves the screen.
 */
async function resolveUnlisted(
  listed: ReadonlySet<string>,
  generation: number,
): Promise<void> {
  const unlisted = [...tracked.keys()].filter((runId) => !listed.has(runId));
  for (const runId of unlisted) {
    const entry = tracked.get(runId);
    if (entry === undefined) continue;
    let payload: RunStatusPayload | null = null;
    try {
      payload = (await unwrap(
        api.GET("/api/runs/{run_id}", { params: { path: { run_id: runId } } }),
      )) as RunStatusPayload;
    } catch {
      // 404 (swept) or a transport error. Neither leaves anything to wait for.
    }
    if (generation !== pollGeneration) return;
    detach(entry);
    const run = payload ? recordFromStatus(payload) : null;
    if (run === null || !TERMINAL_STATUSES.includes(run.status)) {
      useRunStore.getState().remove(runId);
      continue;
    }
    if (payload?.announcedAt) restoreAnnouncedRuns([run]);
    else completeRuns([run]);
    for (const callback of entry.callbacks) callback(run);
  }
}

export function startRunPoller(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => void pollRunsNow(), POLL_INTERVAL_MS);
}

/** Clear the interval without disowning in-flight results. */
function stopPolling(): void {
  if (pollTimer === null) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

/** Tear polling down from outside: in-flight results no longer belong to anyone. */
export function stopRunPoller(): void {
  pollGeneration += 1;
  stopPolling();
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
