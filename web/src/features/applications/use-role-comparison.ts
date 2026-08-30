import { useMutation } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type RoleComparison = components["schemas"]["RoleComparisonOut"];

export function useRoleComparison() {
  return useMutation({
    mutationFn: (jobIds: number[]): Promise<RoleComparison> =>
      unwrap(
        api.POST("/api/jobs/company-intelligence-comparisons", {
          body: { jobIds },
        }),
      ) as Promise<RoleComparison>,
  });
}
