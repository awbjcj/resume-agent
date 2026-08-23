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

it("announces a tailor completion with its version count", () => {
  announceCompletions([run()]);
  expect(toast.success).toHaveBeenCalledOnce();
  expect(toast.success.mock.calls[0][0]).toContain("2 resume versions");
});

it("routes failures and cancellations to their own toast kinds", () => {
  announceCompletions([run({ status: "failed", error: "boom" })]);
  expect(toast.error).toHaveBeenCalledOnce();

  announceCompletions([run({ status: "cancelled" })]);
  expect(toast.info).toHaveBeenCalledOnce();
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
