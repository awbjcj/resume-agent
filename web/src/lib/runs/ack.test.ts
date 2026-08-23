import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiPost: vi.fn() }));
vi.mock("@/lib/api/client", () => ({
  api: { POST: mocks.apiPost },
  unwrap: async (request: Promise<{ data?: unknown }>) => (await request).data,
}));

import { ackRuns } from "./ack";

beforeEach(() => {
  mocks.apiPost.mockReset();
  mocks.apiPost.mockResolvedValue({ data: { acknowledged: 0 }, error: undefined });
});

it("sends nothing for an empty batch", async () => {
  await ackRuns([]);
  expect(mocks.apiPost).not.toHaveBeenCalled();
});

it("splits a batch larger than the server's cap", async () => {
  // AckRunsIn.run_ids has max_length=200; one oversized request would 422, and
  // because ack failures are swallowed nothing would ever be stamped.
  const ids = Array.from({ length: 450 }, (_, index) => `run-${index}`);

  await ackRuns(ids);

  const sizes = mocks.apiPost.mock.calls.map(
    (call: unknown[]) => (call[1] as { body: { runIds: string[] } }).body.runIds.length,
  );
  expect(sizes).toEqual([200, 200, 50]);
  expect(sizes.reduce((a: number, b: number) => a + b, 0)).toBe(450);
});

it("keeps acknowledging later chunks after one fails", async () => {
  mocks.apiPost
    .mockRejectedValueOnce(new Error("500"))
    .mockResolvedValue({ data: { acknowledged: 0 }, error: undefined });

  await ackRuns(Array.from({ length: 250 }, (_, i) => `run-${i}`));

  expect(mocks.apiPost).toHaveBeenCalledTimes(2);
});
