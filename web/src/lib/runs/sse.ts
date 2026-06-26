import { withTokenParam } from "@/lib/api/client";
import { useRunStore, type PullRunResult, type RunRecord } from "./store";

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
): () => void {
  const source = new EventSource(withTokenParam(`/api/runs/${runId}/events`));

  source.onmessage = (e) => {
    let data: {
      state?: string;
      percent?: number;
      label?: string;
      current?: number;
      total?: number;
      etaText?: string | null;
      error?: string;
      result?: PullRunResult | Record<string, unknown> | null;
    };
    try {
      data = JSON.parse(e.data);
    } catch {
      return; // ignore keep-alive / non-JSON frames
    }
    const state = data.state ?? "running";
    const status: RunRecord["status"] =
      state === "done"
        ? "succeeded"
        : state === "error"
          ? "failed"
          : state === "cancelled"
            ? "cancelled"
            : state === "cancelling"
              ? "cancelling"
            : "running";
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
    };
    useRunStore.getState().upsert(run);
    if (state === "done" || state === "error" || state === "cancelled") {
      source.close();
      onDone?.(run);
      // Let the finished bar linger briefly, then clear it.
      setTimeout(() => useRunStore.getState().remove(runId), 4000);
    }
  };

  source.onerror = () => {
    const run: RunRecord = {
      runId,
      kind,
      status: "failed",
      percent: 0,
      phase: "",
      current: 0,
      total: 0,
      etaText: null,
      error: "stream error",
      result: null,
    };
    useRunStore.getState().upsert(run);
    source.close();
    onDone?.(run);
  };

  return () => source.close();
}
