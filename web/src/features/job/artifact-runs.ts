import type { RunRecord } from "@/lib/runs/store";

export const ACTIVE_RUN_STATUSES: RunRecord["status"][] = [
  "queued",
  "running",
  "cancelling",
];

export function latestArtifactRun(
  runs: Record<string, RunRecord>,
  kind: string,
  metaKey: "versionId" | "coverLetterId",
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
