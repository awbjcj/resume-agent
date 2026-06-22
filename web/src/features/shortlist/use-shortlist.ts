import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ShortlistItem } from "@/lib/filters/types";

export function useShortlist() {
  return useQuery({
    queryKey: ["shortlist"],
    queryFn: async (): Promise<ShortlistItem[]> => {
      const page = await unwrap(
        api.GET("/api/shortlist", { params: { query: { pageSize: 200 } } }),
      );
      return (page as { data: ShortlistItem[] }).data;
    },
  });
}
