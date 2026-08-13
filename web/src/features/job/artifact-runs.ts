import type { RunRecord } from "@/lib/runs/store";

export const ACTIVE_RUN_STATUSES: RunRecord["status"][] = [
  "queued",
  "running",
  "cancelling",
];

/** Whether a run is working on this job, however its launcher tagged it.
 *
 * Per-job launchers record `meta.jobId`; bulk cover-letter launches persist the
 * backend-resolved target set as `meta.jobIds`. Checking both shapes keeps
 * generation state visible after reload and across tabs.
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
