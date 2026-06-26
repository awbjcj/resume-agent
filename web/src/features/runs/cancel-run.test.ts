import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRunStore } from "@/lib/runs/store";

const mocks = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/lib/api/client", () => ({
  api: { POST: mocks.post },
  unwrap: (value: unknown) => value,
}));

import { cancelRun } from "./use-launch-run";

describe("cancelRun", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ runs: {} });
  });

  it("updates the run immediately while the cancellation request is in flight", async () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "tailor",
      status: "running",
      percent: 20,
      phase: "Tailoring",
      current: 1,
      total: 5,
      etaText: null,
    });
    let resolveRequest: ((value: unknown) => void) | undefined;
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    const request = cancelRun("r1");

    expect(useRunStore.getState().runs.r1.status).toBe("cancelling");
    expect(useRunStore.getState().runs.r1.phase).toBe("Cancelling");
    resolveRequest?.({ state: "cancelling" });
    await request;
  });
});
