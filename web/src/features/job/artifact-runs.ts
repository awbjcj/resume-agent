import type { RunRecord } from "@/lib/runs/store";

export const ACTIVE_RUN_STATUSES: RunRecord["status"][] = [
  "queued",
  "running",
  "cancelling",
];

/** Whether a run is working on this job, however its launcher tagged it.
 *
 * Per-job launchers record `meta.jobId`; the Pipeline bulk actions record
 * `meta.jobIds`. A per-job surface that only checked `jobId` treated a bulk run
 * covering the same job as absent — offering a second Generate on a job already
 * being processed, which really does run twice (`POST /api/cover-letters` has no
 * singleton key). An approved-scope bulk run resolves its targets server-side
 * and so carries neither; it stays invisible here by necessity.
 */
export function runCoversJob(run: RunRecord, jobId: number): boolean {
  if (run.meta?.jobId === jobId) return true;
  const jobIds = run.meta?.jobIds;
  return Array.isArray(jobIds) && jobIds.includes(jobId);
}

/** The most recent run of `kind` working on this job, by either meta shape. */
export function latestJobRun(
  runs: Record<string, RunRecord>,
  kind: string,
  jobId: number,
): RunRecord | undefined {
  return Object.values(runs)
    .filter((run) => run.kind === kind && runCoversJob(run, jobId))
    .sort((left, right) => (right.updatedAt ?? 0) - (left.updatedAt ?? 0))[0];
}

export function latestArtifactRun(
  runs: Record<string, RunRecord>,
  kind: string,
  metaKey: "versionId" | "coverLetterId" | "jobId",
  artifactId: number,
): RunRecord | undefined {
  return Object.values(runs)
    .filter((run) => run.kind === kind && run.meta?.[metaKey] === artifactId)
    .sort((left, right) => (right.updatedAt ?? 0) - (left.updatedAt ?? 0))[0];
}

export function runCreatedArtifact(
  runs: Record<string, RunRecord>,
  kind: string,
  resultKey: "versionId" | "coverLetterId",
  artifactId: number,
): boolean {
  return Object.values(runs).some(
    (run) =>
      run.kind === kind &&
      run.status === "succeeded" &&
      (run.result as Record<string, unknown> | null)?.[resultKey] === artifactId,
  );
}
