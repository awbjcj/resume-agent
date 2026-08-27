import { beforeEach, expect, it, vi } from "vitest";

import type { RunRecord } from "./store";

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));

import { announceCompletions } from "./announce";

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "r1",
    kind: "tailor",
    status: "succeeded",
    percent: 100,
    phase: "",
    current: 1,
    total: 1,
    etaText: null,
    result: { jobs: [{ versionCount: 2 }] },
    ...overrides,
  };
}

beforeEach(() => {
  toast.success.mockReset();
  toast.error.mockReset();
  toast.info.mockReset();
});

it("does nothing for an empty batch", () => {
  announceCompletions([]);
  expect(toast.success).not.toHaveBeenCalled();
});

it("announces a tailor completion with its successful job and version counts", () => {
  announceCompletions([run()]);
  expect(toast.success).toHaveBeenCalledOnce();
  expect(toast.success.mock.calls[0][0]).toContain("1 job tailored");
  expect(toast.success.mock.calls[0][0]).toContain("2 resume versions");
});

it("counts tailored jobs from the jobs array even when nested version counts are absent", () => {
  announceCompletions([
    run({ result: { jobs: [{ jobId: 1 }, { jobId: 2 }] } }),
  ]);

  expect(toast.success.mock.calls[0][0]).toContain("2 jobs tailored");
  expect(toast.success.mock.calls[0][0]).not.toContain("resume version");
});

it("accepts snake-case nested counts from restored or legacy run payloads", () => {
  announceCompletions([
    run({ result: { jobs: [{ job_id: 1, version_count: 3 }] } }),
  ]);

  expect(toast.success.mock.calls[0][0]).toContain("1 job tailored");
  expect(toast.success.mock.calls[0][0]).toContain("3 resume versions");
});

it("does not invent a zero-job result when tailoring detail is unavailable", () => {
  announceCompletions([run({ result: null })]);

  expect(toast.success.mock.calls[0][0]).toBe(
    "Tailoring complete. Open a job's Versions tab to render PDF.",
  );
});

it("renders accurate cover-letter and redo completion summaries", () => {
  announceCompletions([
    run({ kind: "coverLetter", result: { coverLetters: [{}, {}] } }),
    run({ kind: "redo", result: { outcomes: [{}] } }),
  ]);

  expect(toast.success).toHaveBeenNthCalledWith(
    1,
    "Cover-letter generation complete: 2 cover letters created.",
  );
  expect(toast.success).toHaveBeenNthCalledWith(
    2,
    "Pipeline redo complete: 1 stage processed.",
  );
});

it("tells the user a deferred backlog will be picked up next run", () => {
  announceCompletions([
    run({
      kind: "refreshClusters",
      result: {
        assignedSkills: 300,
        aliasesMerged: 12,
        domainsCreated: 4,
        uncertainSkills: 900,
        deferredSkills: 880,
        failedSkills: 0,
        skippedStaleSkills: 0,
      },
    }),
  ]);

  expect(toast.success).toHaveBeenCalledWith(
    "Regroup complete: 300 assigned · 12 aliases merged · 4 domains created · 900 uncertain · 880 deferred to next run · 0 failed · 0 skipped.",
  );
});

it("omits the deferred clause when nothing was deferred", () => {
  announceCompletions([
    run({
      kind: "refreshClusters",
      result: {
        assignedSkills: 5,
        aliasesMerged: 0,
        domainsCreated: 1,
        uncertainSkills: 0,
        deferredSkills: 0,
        failedSkills: 0,
        skippedStaleSkills: 0,
      },
    }),
  ]);

  expect(toast.success).toHaveBeenCalledWith(
    "Regroup complete: 5 assigned · 0 aliases merged · 1 domains created · 0 uncertain · 0 failed · 0 skipped.",
  );
});

it("uses honest generic summaries when specialized result detail is malformed", () => {
  announceCompletions([
    run({ kind: "refreshClusters", result: {} }),
    run({ kind: "maintainTaxonomy", result: null }),
  ]);

  expect(toast.success).toHaveBeenNthCalledWith(1, "Skill regrouping complete.");
  expect(toast.success).toHaveBeenNthCalledWith(2, "Taxonomy maintenance complete.");
});

it("renders user-facing labels instead of internal run identifiers", () => {
  announceCompletions([
    run({ kind: "profile-build", result: null }),
    run({ kind: "coverLetterRevise", result: null }),
  ]);

  expect(toast.success).toHaveBeenNthCalledWith(1, "Profile build completed");
  expect(toast.success).toHaveBeenNthCalledWith(2, "Cover-letter revision completed");
});

it("routes failures and cancellations to their own toast kinds", () => {
  announceCompletions([run({ kind: "coverLetter", status: "failed", error: "boom" })]);
  expect(toast.error).toHaveBeenCalledWith("Cover-letter generation failed: boom");

  announceCompletions([run({ kind: "refreshClusters", status: "cancelled" })]);
  expect(toast.info).toHaveBeenCalledWith("Skill regrouping cancelled");
});

it("gives three completions three toasts", () => {
  announceCompletions([
    run({ runId: "a" }),
    run({ runId: "b" }),
    run({ runId: "c" }),
  ]);
  expect(toast.success).toHaveBeenCalledTimes(3);
});

it("collapses four completions into exactly one summary toast", () => {
  announceCompletions([
    run({ runId: "a" }),
    run({ runId: "b" }),
    run({ runId: "c" }),
    run({ runId: "d" }),
  ]);
  expect(toast.success).toHaveBeenCalledOnce();
  expect(toast.success.mock.calls[0][0]).toContain("4 runs finished");
  expect(toast.error).not.toHaveBeenCalled();
});

it("says how many of a collapsed batch failed", () => {
  announceCompletions([
    run({ runId: "a" }),
    run({ runId: "b" }),
    run({ runId: "c", status: "failed", error: "boom" }),
    run({ runId: "d", status: "failed", error: "boom" }),
  ]);
  expect(toast.success.mock.calls[0][0]).toContain("2 failed");
});

it("reports an all-failed batch as an error, not a success", () => {
  announceCompletions([
    run({ runId: "a", status: "failed", error: "boom" }),
    run({ runId: "b", status: "failed", error: "boom" }),
    run({ runId: "c", status: "failed", error: "boom" }),
    run({ runId: "d", status: "failed", error: "boom" }),
  ]);

  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledOnce();
  expect(toast.error.mock.calls[0][0]).toContain("4 failed");
});
