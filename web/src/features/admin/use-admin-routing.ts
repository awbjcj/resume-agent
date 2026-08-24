import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export const adminRoutingKey = ["admin", "routing"] as const;

export function useAdminRouting(enabled = true) {
  return useQuery({
    queryKey: adminRoutingKey,
    queryFn: () => unwrap(api.GET("/api/admin/routing")),
    enabled,
  });
}

export function useSaveAdminRouting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: components["schemas"]["RoutingUpdate"]) =>
      unwrap(api.PUT("/api/admin/routing", { body })),
    onSuccess: (data) => queryClient.setQueryData(adminRoutingKey, data),
  });
}
