import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "./use-launch-run";

export function useBulkRun() {
  const { launch } = useLaunchRun();
  return {
    tailorApproved: () =>
      launch("tailor", () => unwrap(api.POST("/api/tailor", { body: { approved: true } }))),
    coverLettersApproved: () =>
      launch("coverLetter", () =>
        unwrap(api.POST("/api/cover-letters", { body: { approved: true } })),
      ),
  };
}
