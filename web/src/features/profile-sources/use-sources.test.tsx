import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  active: null as { status: string } | null,
  launch: vi.fn(),
}));

vi.mock("@/features/runs/use-active-run", () => ({
  useActiveRun: () => mocks.active,
}));

vi.mock("@/features/runs/use-launch-run", () => ({
  launchers: { githubSync: vi.fn() },
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

import { useSyncGithub } from "./use-sources";

describe("useSyncGithub", () => {
  beforeEach(() => {
    mocks.active = null;
    mocks.launch.mockReset();
  });

  it("stays pending while the tracked run launch request is in flight", async () => {
    let finish!: (value: boolean) => void;
    mocks.launch.mockReturnValue(new Promise<boolean>((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => useSyncGithub());

    act(() => result.current.mutate());
    expect(result.current.isPending).toBe(true);

    act(() => finish(true));
    await waitFor(() => expect(result.current.isPending).toBe(false));
  });

  it.each(["queued", "running", "cancelling"])(
    "is pending for a %s run",
    (status) => {
      mocks.active = { status };
      const { result } = renderHook(() => useSyncGithub());
      expect(result.current.isPending).toBe(true);
    },
  );
});
