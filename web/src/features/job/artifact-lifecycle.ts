import { useRunStore, type RunRecord } from "@/lib/runs/store";

export const ACTIVE_RUN_STATUSES: RunRecord["status"][] = [
  "queued",
  "running",
  "cancelling",
];

type ArtifactKey = "versionId" | "coverLetterId" | "jobId";
export type RunIndex = {
  byJob: Map<string, RunRecord[]>;
  byArtifact: Map<string, RunRecord>;
  created: Set<string>;
};

export type ArtifactLifecycle<TInput = never> = {
  run: RunRecord | undefined;
  active: boolean;
  justCreated: boolean;
  retryInput: TInput | undefined;
};

const indexCache = new WeakMap<Record<string, RunRecord>, RunIndex>();

const key = (...parts: Array<string | number>) => parts.join("\u001f");
const newer = (left: RunRecord | undefined, right: RunRecord) =>
  left === undefined || (right.updatedAt ?? 0) > (left.updatedAt ?? 0) ? right : left;

export function runCoversJob(run: RunRecord, jobId: number): boolean {
  if (run.meta?.jobId === jobId) return true;
  const jobIds = run.meta?.jobIds;
  return Array.isArray(jobIds) && jobIds.includes(jobId);
}

/** Build every Job artifact lookup in one O(R) pass over a run snapshot. */
export function indexArtifactRuns(runs: Record<string, RunRecord>): RunIndex {
  const byJob = new Map<string, RunRecord[]>();
  const byArtifact = new Map<string, RunRecord>();
  const created = new Set<string>();

  for (const run of Object.values(runs)) {
    const jobIds = new Set<number>();
    if (typeof run.meta?.jobId === "number") jobIds.add(run.meta.jobId);
    if (Array.isArray(run.meta?.jobIds)) {
      for (const jobId of run.meta.jobIds) if (typeof jobId === "number") jobIds.add(jobId);
    }
    for (const jobId of jobIds) {
      const indexKey = key(run.kind, jobId);
      const values = byJob.get(indexKey);
      if (values) values.push(run);
      else byJob.set(indexKey, [run]);
    }
    for (const metaKey of ["versionId", "coverLetterId", "jobId"] as const) {
      const artifactId = run.meta?.[metaKey];
      if (typeof artifactId !== "number") continue;
      const indexKey = key(run.kind, metaKey, artifactId);
      byArtifact.set(indexKey, newer(byArtifact.get(indexKey), run));
    }
    if (run.status !== "succeeded") continue;
    const result = run.result as Record<string, unknown> | null;
    for (const resultKey of ["versionId", "coverLetterId"] as const) {
      const artifactId = result?.[resultKey];
      if (typeof artifactId === "number") created.add(key(run.kind, resultKey, artifactId));
    }
  }
  for (const values of byJob.values()) {
    values.sort((left, right) => (right.updatedAt ?? 0) - (left.updatedAt ?? 0));
  }
  return { byJob, byArtifact, created };
}

/** Share the O(R) index across every row observing the same Zustand snapshot. */
export function cachedArtifactRunIndex(runs: Record<string, RunRecord>): RunIndex {
  const cached = indexCache.get(runs);
  if (cached) return cached;
  const index = indexArtifactRuns(runs);
  indexCache.set(runs, index);
  return index;
}

export function latestJobRun(index: RunIndex, kind: string, jobId: number) {
  return index.byJob.get(key(kind, jobId))?.[0];
}

export function jobRuns(index: RunIndex, kind: string, jobId: number) {
  return index.byJob.get(key(kind, jobId)) ?? [];
}

export function latestArtifactRun(
  index: RunIndex,
  kind: string,
  metaKey: ArtifactKey,
  artifactId: number,
) {
  return index.byArtifact.get(key(kind, metaKey, artifactId));
}

export function runCreatedArtifact(
  index: RunIndex,
  kind: string,
  resultKey: Exclude<ArtifactKey, "jobId">,
  artifactId: number,
) {
  return index.created.has(key(kind, resultKey, artifactId));
}

export function resumeRevisionLifecycle(
  index: RunIndex,
  versionId: number,
): ArtifactLifecycle<{ versionId: number; instruction: string; reReview: boolean }> {
  const run = latestArtifactRun(index, "revise", "versionId", versionId);
  return {
    run,
    active: run !== undefined && ACTIVE_RUN_STATUSES.includes(run.status),
    justCreated: runCreatedArtifact(index, "revise", "versionId", versionId),
    retryInput:
      run?.status === "failed"
        ? {
            versionId,
            instruction: run.meta?.instruction ?? "",
            reReview: Boolean(run.meta?.reReview),
          }
        : undefined,
  };
}

export function coverLetterRevisionLifecycle(
  index: RunIndex,
  coverLetterId: number,
): ArtifactLifecycle<{ coverLetterId: number; instruction: string }> {
  const run = latestArtifactRun(
    index,
    "coverLetterRevise",
    "coverLetterId",
    coverLetterId,
  );
  return {
    run,
    active: run !== undefined && ACTIVE_RUN_STATUSES.includes(run.status),
    justCreated: runCreatedArtifact(
      index,
      "coverLetterRevise",
      "coverLetterId",
      coverLetterId,
    ),
    retryInput:
      run?.status === "failed"
        ? { coverLetterId, instruction: run.meta?.instruction ?? "" }
        : undefined,
  };
}

export function dismissArtifactRun(runId: string): void {
  useRunStore.getState().remove(runId);
}

export function useArtifactRunIndex(): RunIndex {
  const runs = useRunStore((state) => state.runs);
  return cachedArtifactRunIndex(runs);
}
