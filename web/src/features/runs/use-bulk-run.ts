import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "./use-launch-run";

export function useBulkRun() {
  const { launch } = useLaunchRun();
  return {
    tailorApproved: () =>
      launch("tailor", () =>
        unwrap(api.POST("/api/tailor", { body: { approved: true, deep: false } })),
      ),
    coverLettersApproved: () =>
      launch("coverLetter", () =>
        unwrap(api.POST("/api/cover-letters", { body: { approved: true } })),
      ),
    tailorSelected: (jobIds: number[], deep: boolean) =>
      launch("tailor", () =>
        unwrap(api.POST("/api/tailor", { body: { jobIds, deep, approved: false } })),
      ),
    coverLettersSelected: (jobIds: number[]) =>
      launch("coverLetter", () =>
        unwrap(api.POST("/api/cover-letters", { body: { jobIds, approved: false } })),
      ),
  };
}
