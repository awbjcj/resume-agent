import { useInfiniteQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { boardFilterToParams } from "@/lib/filters/params";
import type { FilterState } from "@/lib/filters/types";

export type Board = "shortlist" | "triage" | "pipeline";
export type Facets = Record<string, Record<string, number>>;

type BoardPage<T> = {
  data: T[];
  pagination: { page: number; pageSize: number; totalPages: number };
  facets?: Facets;
  total?: number;
};

const PATH = {
  shortlist: "/api/shortlist",
  triage: "/api/triage",
  pipeline: "/api/pipeline",
} as const;

export type ShortlistItem = components["schemas"]["ShortlistItem"];
export type TriageItem = components["schemas"]["TriageItem"];
export type PipelineItem = components["schemas"]["PipelineItem"];

export function useBoardQuery<T>(
  board: Board,
  filter: FilterState,
  opts: { archived?: boolean; pageSize?: number } = {},
) {
  const pageSize = opts.pageSize ?? 50;
  const baseParams = boardFilterToParams(filter, { pageSize, archived: opts.archived });

  const query = useInfiniteQuery({
    queryKey: [board, baseParams, opts.archived ?? false],
    queryFn: ({ pageParam }): Promise<BoardPage<T>> =>
      unwrap(
        api.GET(PATH[board], {
          params: {
            query: { ...baseParams, page: pageParam } as Record<string, string | number | boolean>,
          },
        }),
      ) as Promise<BoardPage<T>>,
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.pagination.page < last.pagination.totalPages ? last.pagination.page + 1 : undefined,
  });

  const pages = query.data?.pages ?? [];
  return {
    rows: pages.flatMap((page) => page.data),
    facets: pages[0]?.facets ?? {},
    total: pages[0]?.total ?? 0,
    fetchNextPage: query.fetchNextPage,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isLoading,
    error: query.error,
  };
}
