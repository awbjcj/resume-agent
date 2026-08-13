import { describe, expect, it } from "vitest";

import type { RunRecord } from "@/lib/runs/store";
import {
  cachedArtifactRunIndex,
  coverLetterRevisionLifecycle,
  indexArtifactRuns,
  jobRuns,
  latestArtifactRun,
  latestJobRun,
  runCreatedArtifact,
  resumeRevisionLifecycle,
} from "./artifact-lifecycle";

function run(value: Partial<RunRecord> & Pick<RunRecord, "runId" | "kind">): RunRecord {
  return {
    status: "running",
    percent: 0,
    phase: "",
    current: 0,
    total: 0,
    etaText: null,
    ...value,
  };
}

describe("Job artifact lifecycle index", () => {
  it("indexes job, parent artifact, and created child in one snapshot", () => {
    const index = indexArtifactRuns({
      old: run({ runId: "old", kind: "revise", updatedAt: 1, meta: { jobId: 3, versionId: 5 } }),
      latest: run({
        runId: "latest",
        kind: "revise",
        status: "succeeded",
        updatedAt: 2,
        meta: { jobId: 3, versionId: 5 },
        result: { versionId: 9 },
      }),
    });

    expect(latestJobRun(index, "revise", 3)?.runId).toBe("latest");
    expect(latestArtifactRun(index, "revise", "versionId", 5)?.runId).toBe("latest");
    expect(runCreatedArtifact(index, "revise", "versionId", 9)).toBe(true);
  });

  it("builds an index once for each immutable store snapshot", () => {
    const runs = { one: run({ runId: "one", kind: "revise" }) };
    expect(cachedArtifactRunIndex(runs)).toBe(cachedArtifactRunIndex(runs));
    expect(cachedArtifactRunIndex({ ...runs })).not.toBe(cachedArtifactRunIndex(runs));
  });

  it("owns typed revision state and retry metadata", () => {
    const index = indexArtifactRuns({
      resume: run({
        runId: "resume",
        status: "failed",
        kind: "revise",
        meta: { jobId: 3, versionId: 5, instruction: "Shorter", reReview: true },
      }),
      letter: run({
        runId: "letter",
        status: "failed",
        kind: "coverLetterRevise",
        meta: { jobId: 3, coverLetterId: 8, instruction: "Warmer" },
      }),
    });
    expect(resumeRevisionLifecycle(index, 5).retryInput).toEqual({
      versionId: 5,
      instruction: "Shorter",
      reReview: true,
    });
    expect(coverLetterRevisionLifecycle(index, 8).retryInput).toEqual({
      coverLetterId: 8,
      instruction: "Warmer",
    });
  });

  it("keeps bulk job coverage and returns all matching placeholders", () => {
    const index = indexArtifactRuns({
      bulk: run({ runId: "bulk", kind: "coverLetter", meta: { jobIds: [3, 4] } }),
      one: run({ runId: "one", kind: "coverLetter", meta: { jobId: 3 } }),
    });

    expect(jobRuns(index, "coverLetter", 3)).toHaveLength(2);
    expect(jobRuns(index, "coverLetter", 4).map((item) => item.runId)).toEqual(["bulk"]);
  });
});
