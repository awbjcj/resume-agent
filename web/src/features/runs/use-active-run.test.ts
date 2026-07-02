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

  it("prefers an in-flight run over an earlier completed one of the same kind", () => {
    // A prior build finished; a rebuild mints a fresh runId. The stale succeeded
    // run is inserted first, so a naive find() would return it instead of the
    // one that is actually running.
    const base = { percent: 0, phase: "", current: 0, total: 0, etaText: null };
    useRunStore.getState().upsert({ ...base, runId: "done", kind: "profile-build", status: "succeeded", percent: 100 });
    useRunStore.getState().upsert({ ...base, runId: "live", kind: "profile-build", status: "running", percent: 30 });
    const { result } = renderHook(() => useActiveRun("profile-build"));
    expect(result.current?.runId).toBe("live");
  });

  it("returns the most recently updated run when none are in flight", () => {
    // Set updatedAt explicitly: upsert stamps Date.now(), which can tie within a
    // single test tick and make the "latest" assertion flaky.
    const base = { percent: 100, phase: "", current: 0, total: 0, etaText: null, kind: "profile-build", status: "succeeded" as const };
    useRunStore.setState({
      runs: {
        old: { ...base, runId: "old", updatedAt: 1000 },
        new: { ...base, runId: "new", updatedAt: 2000 },
      },
    });
    const { result } = renderHook(() => useActiveRun("profile-build"));
    expect(result.current?.runId).toBe("new");
  });
});
