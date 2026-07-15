import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { trackRun } from "@/lib/runs/tracker";

export type ScoutCandidate = {
  company: string;
  url: string;
  reason: string;
  confidence: "high" | "medium" | "low";
  status: "validated" | "unverified" | "failed" | "duplicate";
  ats: string | null;
  token: string | null;
  roleCount: number | null;
  error: string | null;
  errorCode: string | null;
};

type ScoutResult = {
  candidates: ScoutCandidate[];
  scrapeAvailable: boolean;
  scrapeUnavailableReason: string | null;
};

export function useDiscoverCompanies() {
  return useMutation({
    mutationFn: (prompt: string) =>
      unwrap(api.POST("/api/sources/discover", { body: { prompt } })) as Promise<{
        runId: string;
      }>,
  });
}

export function useDiscoverResult(runId: string | null) {
  const [completion, setCompletion] = useState<{
    runId: string;
    state: "done" | "error";
    result: ScoutResult | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!runId) return;
    trackRun({ runId, kind: "source-discovery" }, (run) => {
      if (run.status === "succeeded") {
        setCompletion({
          runId,
          state: "done",
          result: run.result as ScoutResult,
          error: null,
        });
      } else {
        setCompletion({
          runId,
          state: "error",
          result: null,
          error:
            run.error ??
            (run.status === "cancelled" ? "Discovery cancelled" : "Discovery failed"),
        });
      }
    });
  }, [runId]);

  if (!runId) return { state: "idle" as const, result: null, error: null };
  if (!completion || completion.runId !== runId) {
    return { state: "running" as const, result: null, error: null };
  }
  return completion;
}
