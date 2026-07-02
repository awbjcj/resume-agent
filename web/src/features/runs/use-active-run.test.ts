import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { useActiveRun } from "./use-active-run";

afterEach(() => useRunStore.setState({ runs: {} }));

describe("useActiveRun", () => {
  it("returns undefined when no run of that kind exists", () => {
    const { result } = renderHook(() => useActiveRun("profile-build"));
    expect(result.current).toBeUndefined();
  });

  it("finds the run matching the given kind", () => {
    useRunStore.getState().upsert({
      runId: "r1", kind: "profile-build", status: "running",
      percent: 40, phase: "", current: 0, total: 0, etaText: null,
    });
    const { result } = renderHook(() => useActiveRun("profile-build"));
    expect(result.current?.runId).toBe("r1");
  });

  it("ignores runs of a different kind", () => {
    useRunStore.getState().upsert({
      runId: "r2", kind: "pull", status: "running",
      percent: 0, phase: "", current: 0, total: 0, etaText: null,
    });
    const { result } = renderHook(() => useActiveRun("profile-build"));
    expect(result.current).toBeUndefined();
  });
});
