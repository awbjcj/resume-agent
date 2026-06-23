import { withTokenParam } from "@/lib/api/client";
import { useRunStore, type RunRecord } from "./store";

/**
 * Subscribe to a run's SSE stream. The backend (api/runs/sse.py) emits default
 * `message` events whose data is the RunOut JSON: { state, percent, label,
 * error, ... }, where state is pending|running|done|error and the stream closes
 * on a terminal state. Returns an unsubscribe function.
 */
export function watchRun(runId: string, kind: string, onDone?: () => void): () => void {
  const source = new EventSource(withTokenParam(`/api/runs/${runId}/events`));

  source.onmessage = (e) => {
    let data: { state?: string; percent?: number; label?: string; error?: string };
    try {
      data = JSON.parse(e.data);
    } catch {
      return; // ignore keep-alive / non-JSON frames
    }
    const state = data.state ?? "running";
    const status: RunRecord["status"] =
      state === "done" ? "succeeded" : state === "error" ? "failed" : "running";
    useRunStore.getState().upsert({
      runId,
      kind,
      status,
      percent: typeof data.percent === "number" ? data.percent : 0,
      phase: data.label ?? "",
      error: data.error ?? undefined,
    });
    if (state === "done" || state === "error") {
      source.close();
      onDone?.();
      // Let the finished bar linger briefly, then clear it.
      setTimeout(() => useRunStore.getState().remove(runId), 4000);
    }
  };

  source.onerror = () => {
    useRunStore
      .getState()
      .upsert({ runId, kind, status: "failed", percent: 0, phase: "", error: "stream error" });
    source.close();
    onDone?.();
  };

  return () => source.close();
}
