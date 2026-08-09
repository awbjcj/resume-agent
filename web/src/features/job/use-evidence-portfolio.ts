import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type EvidencePortfolio = components["schemas"]["EvidencePortfolioOut"];

export function useEvidencePortfolio(versionId: number, enabled: boolean) {
  return useQuery<EvidencePortfolio>({
    queryKey: ["evidence-portfolio", versionId],
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/resume-versions/{version_id}/evidence-portfolio", {
          params: { path: { version_id: versionId } },
        }),
      ),
  });
}
