import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ launch: vi.fn() }));

vi.mock("@/features/runs/use-launch-run", () => ({
  useLaunchRun: () => ({ launch: mocks.launch }),
}));

import { useReviseCoverLetter, useReviseVersion } from "./use-job-mutations";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
  );
}

describe("revision run mutations", () => {
  beforeEach(() => {
    mocks.launch.mockReset();
    mocks.launch.mockResolvedValue(true);
  });

  it("launches resume revision with retry metadata", async () => {
    const { result } = renderHook(() => useReviseVersion(3), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        versionId: 5,
        instruction: "shorter",
        reReview: true,
      }),
    );

    expect(mocks.launch).toHaveBeenCalledWith(
      "revise",
      expect.any(Function),
      ["job"],
      { versionId: 5, jobId: 3, instruction: "shorter", reReview: true },
    );
  });

  it("launches cover-letter revision with retry metadata", async () => {
    const { result } = renderHook(() => useReviseCoverLetter(8), { wrapper });

    await act(() =>
      result.current.mutateAsync({ coverLetterId: 7, instruction: "warmer" }),
    );

    expect(mocks.launch).toHaveBeenCalledWith(
      "coverLetterRevise",
      expect.any(Function),
      ["job"],
      { coverLetterId: 7, jobId: 8, instruction: "warmer" },
    );
  });
});
