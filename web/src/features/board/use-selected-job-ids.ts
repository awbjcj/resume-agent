import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { boardFilterToParams } from "@/lib/filters/params";
import type { FilterState } from "@/lib/filters/types";

type PipelineItem = components["schemas"]["PipelineItem"];

interface Selection {
  mode: "ids" | "query";
  ids: Set<number>;
}

/**
 * The selected job ids. "Select all matching" (mode "query") holds no ids,
 * only a count, so it is resolved by re-running the board query with the
 * same filter params the user sees — the same approach useApprovedLaunchJobs
 * takes for the launch dialog's status=approved query.
 */
export function useSelectedJobIds(
  board: "pipeline",
  selection: Selection,
  filter: FilterState,
  enabled: boolean,
): number[] {
  const needsResolve = enabled && selection.mode === "query";
  const params = boardFilterToParams(filter, { pageSize: 200 });
  const query = useQuery({
    queryKey: ["selected-job-ids", board, params],
    enabled: needsResolve,
    queryFn: () =>
      fetchAllPages<PipelineItem>((page) =>
        api.GET("/api/pipeline", {
          params: { query: { ...params, page } as Record<string, string | number> },
        }),
      ),
  });
  if (selection.mode !== "query") return [...selection.ids];
  return (query.data ?? []).map((row) => row.jobId);
}
