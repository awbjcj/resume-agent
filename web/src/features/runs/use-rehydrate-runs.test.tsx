import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pollRunsNow: vi.fn(async () => undefined),
  startRunPoller: vi.fn(),
  stopRunPoller: vi.fn(),
}));
vi.mock("@/lib/runs/tracker", () => mocks);

import { useRehydrateRuns } from "./use-rehydrate-runs";

beforeEach(() => {
  mocks.pollRunsNow.mockClear();
  mocks.startRunPoller.mockClear();
  mocks.stopRunPoller.mockClear();
});

/**
 * The hook used to own its own `/api/runs` fetch. That reconciliation now lives
 * in the tracker (see tracker.test.ts for the multi-page, terminal-run, and
 * transport-failure coverage) so the endpoint has exactly one owner. All this
 * hook still does is kick the first pass and keep the interval alive.
 */
it("runs one immediate reconciliation and starts the poller", async () => {
  renderHook(() => useRehydrateRuns());

  await waitFor(() => expect(mocks.pollRunsNow).toHaveBeenCalledOnce());
  expect(mocks.startRunPoller).toHaveBeenCalledOnce();
});

it("stops the poller on unmount so a dead client keeps no interval", () => {
  const { unmount } = renderHook(() => useRehydrateRuns());
  expect(mocks.stopRunPoller).not.toHaveBeenCalled();

  unmount();

  expect(mocks.stopRunPoller).toHaveBeenCalledOnce();
});
