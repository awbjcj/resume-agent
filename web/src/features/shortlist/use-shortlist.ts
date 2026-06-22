import { useQuery } from "@tanstack/react-query";

import { api, fetchAllPages } from "@/lib/api/client";
import type { ShortlistItem } from "@/lib/filters/types";

export function useShortlist() {
  return useQuery({
    queryKey: ["shortlist"],
    queryFn: (): Promise<ShortlistItem[]> =>
      fetchAllPages<ShortlistItem>((page) =>
        api.GET("/api/shortlist", { params: { query: { pageSize: 200, page } } }),
      ),
  });
}
