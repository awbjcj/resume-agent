import type { QueryClient } from "@tanstack/react-query";

const BOARD_QUERY_KEYS = ["shortlist", "pipeline", "triage", "job"] as const;

export function invalidateBoardQueries(queryClient: QueryClient): Promise<unknown[]> {
  return Promise.all(
    BOARD_QUERY_KEYS.map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
  );
}
