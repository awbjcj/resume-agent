import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type CompanyIntelligenceVersionList =
  components["schemas"]["CompanyIntelligenceVersionListOut"];
export type RolePreparationResource =
  | components["schemas"]["RolePreparationUnavailableOut"]
  | components["schemas"]["RolePreparationEmptyOut"]
  | components["schemas"]["RolePreparationReadyOut"];
export type HiringContactResource =
  | components["schemas"]["HiringContactUnavailableOut"]
  | components["schemas"]["HiringContactEmptyOut"]
  | components["schemas"]["HiringContactReadyOut"];

export function useCompanyIntelligenceVersions(jobId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["company-intelligence-versions", jobId],
    enabled,
    queryFn: (): Promise<CompanyIntelligenceVersionList> =>
      unwrap(
        api.GET("/api/jobs/{job_id}/company-intelligence/versions", {
          params: { path: { job_id: jobId }, query: { limit: 10 } },
        }),
      ) as Promise<CompanyIntelligenceVersionList>,
  });
}

export function useRolePreparation(jobId: number) {
  return useQuery({
    queryKey: ["role-preparation", jobId],
    queryFn: (): Promise<RolePreparationResource> =>
      unwrap(
        api.GET("/api/jobs/{job_id}/role-preparation-brief", {
          params: { path: { job_id: jobId } },
        }),
      ) as Promise<RolePreparationResource>,
  });
}

export function useHiringContactIntelligence(jobId: number) {
  return useQuery({
    queryKey: ["hiring-contact-intelligence", jobId],
    queryFn: (): Promise<HiringContactResource> =>
      unwrap(
        api.GET("/api/jobs/{job_id}/hiring-contact-intelligence", {
          params: { path: { job_id: jobId } },
        }),
      ) as Promise<HiringContactResource>,
  });
}
