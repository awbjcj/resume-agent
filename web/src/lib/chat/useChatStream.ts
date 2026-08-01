import { useCallback, useEffect, useRef, useState } from "react";

import { cancelRun } from "@/features/runs/use-launch-run";
import { api, getToken, unwrap, withTokenParam } from "@/lib/api/client";

import { parseStreamEvent, reduceEvent, type ChatPart } from "./events";

export type ChatStreamStatus = "idle" | "streaming" | "done" | "error";

export function useChatStream(runId: string | null) {
  const [parts, setParts] = useState<ChatPart[]>([]);
  const [status, setStatus] = useState<ChatStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef(0);
  const source = useRef<EventSource | null>(null);

  const reset = useCallback(() => {
    source.current?.close();
    source.current = null;
    cursor.current = 0;
    setParts([]);
    setStatus("idle");
    setError(null);
  }, []);

  const stop = useCallback(() => {
    source.current?.close();
    source.current = null;
    if (runId) void cancelRun(runId);
    cursor.current = 0;
    setParts([]);
    setError(null);
    setStatus("idle");
  }, [runId]);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = (token?: string) => {
      if (disposed || typeof EventSource === "undefined") return;
      const base = `/api/runs/${runId}/stream?offset=${cursor.current}`;
      const url = token ? `${base}&token=${encodeURIComponent(token)}` : withTokenParam(base);
      const eventSource = new EventSource(url);
      source.current = eventSource;
      setStatus("streaming");

      eventSource.onmessage = (message) => {
        let raw: unknown;
        try {
          raw = JSON.parse(message.data);
        } catch {
          return;
        }
        const event = parseStreamEvent(raw);
        if (!event || event.i !== cursor.current) return;
        cursor.current = event.i + 1;
        if (event.t === "completed") {
          eventSource.close();
          setStatus("done");
          return;
        }
        if (event.t === "failed") {
          eventSource.close();
          setError(event.v.message);
          setStatus("error");
          return;
        }
        setParts((current) => reduceEvent(current, event));
      };

      eventSource.onerror = () => {
        eventSource.close();
        if (!disposed) reconnectTimer = setTimeout(() => connect(token), 500);
      };
    };

    queueMicrotask(() => {
      if (disposed) return;
      reset();
      if (!runId) return;
      if (getToken()) connect();
      else {
        void unwrap(api.POST("/api/auth/link-token", { body: { purpose: "sse" } }))
          .then((link) => connect(link.token))
          .catch(() => connect());
      }
    });

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source.current?.close();
      source.current = null;
    };
  }, [reset, runId]);

  return { parts, status, error, stop, reset };
}
