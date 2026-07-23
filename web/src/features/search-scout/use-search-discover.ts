import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { trackRun } from "@/lib/runs/tracker";

export type SearchSuggestionRow = {
  value: string;
  kind:
    | "keyword"
    | "title"
    | "role_anchor"
    | "exclude_term"
    | "location"
    | "seniority"
    | "adjacent_role";
  reason: string;
  status: "new" | "duplicate";
  fitScore: number | null;
  citations: { url: string; title: string }[];
};

type SearchScoutResult = { prompt: string; suggestions: SearchSuggestionRow[] };

export function useDiscoverSearchTerms() {
  return useMutation({
    mutationFn: (prompt: string) =>
      unwrap(api.POST("/api/search/discover", { body: { prompt } })) as Promise<{
        runId: string;
      }>,
  });
}

export function useSearchDiscoverResult(runId: string | null) {
  const [completion, setCompletion] = useState<{
    runId: string;
    state: "done" | "error";
    result: SearchScoutResult | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!runId) return;
    trackRun({ runId, kind: "search-discovery" }, (run) => {
      if (run.status === "succeeded") {
        setCompletion({
          runId,
          state: "done",
          result: run.result as SearchScoutResult,
          error: null,
        });
      } else {
        setCompletion({
          runId,
          state: "error",
          result: null,
          error:
            run.error ??
            (run.status === "cancelled"
              ? "Search discovery cancelled"
              : "Search discovery failed"),
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
