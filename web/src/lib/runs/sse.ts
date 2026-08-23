import { getToken, withTokenParam } from "@/lib/api/client";
import { getSseLinkToken } from "./linkToken";
import {
  useRunStore,
  type PullRunResult,
  type RunMeta,
  type RunRecord,
} from "./store";

/** Map a backend run state to the store projection. */
export function stateToStatus(state: string): RunRecord["status"] {
  switch (state) {
    case "done":
      return "succeeded";
    case "error":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "cancelling":
      return "cancelling";
    case "pending":
      return "queued";
    default:
      return "running";
  }
}

/**
 * Subscribe to a run's SSE stream. The backend (api/runs/sse.py) emits default
 * `message` events whose data is the RunOut JSON: { state, percent, label,
 * error, ... }, where state is pending|running|done|error and the stream closes
 * on a terminal state. Returns an unsubscribe function.
 */
export function watchRun(
  runId: string,
  kind: string,
  onDone?: (run: RunRecord) => void,
  onTransportError?: () => void,
): () => void {
  let source: EventSource | null = null;
  let closed = false;

  const connect = (token?: string) => {
    if (closed) return;
    const base = `/api/runs/${runId}/events`;
    const url = token ? `${base}?token=${encodeURIComponent(token)}` : withTokenParam(base);
    const eventSource = new EventSource(url);
    source = eventSource;

  eventSource.onmessage = (e) => {
    let data: {
      state?: string;
      percent?: number;
      label?: string;
      current?: number;
      total?: number;
      etaText?: string | null;
      error?: string;
      result?: PullRunResult | Record<string, unknown> | null;
      meta?: RunMeta | null;
    };
    try {
      data = JSON.parse(e.data);
    } catch {
      return; // ignore keep-alive / non-JSON frames
    }
    const state = data.state ?? "running";
    const status = stateToStatus(state);
    const run: RunRecord = {
      runId,
      kind,
      status,
      percent: typeof data.percent === "number" ? data.percent : 0,
      phase: data.label ?? "",
      current: typeof data.current === "number" ? data.current : 0,
      total: typeof data.total === "number" ? data.total : 0,
      etaText: data.etaText ?? null,
      error: data.error ?? undefined,
      result: data.result ?? null,
      ...(data.meta !== undefined ? { meta: data.meta } : {}),
    };
    useRunStore.getState().upsert(run);
    if (state === "done" || state === "error" || state === "cancelled") {
      eventSource.close();
      // Everything a terminal run implies — announcing it, acknowledging it,
      // refreshing queries, retiring the bar — belongs to the tracker, which
      // reaches the same lifecycle whether the news arrived here or from the
      // reconciliation poller. This module only translates the wire.
      onDone?.(run);
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    onTransportError?.();
  };

  };

  if (getToken()) {
    connect();
  } else {
    void getSseLinkToken()
      .then((token) => connect(token))
      .catch(() => connect());
  }

  return () => {
    closed = true;
    source?.close();
  };
}
