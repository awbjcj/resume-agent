import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore, type RunRecord } from "./store";

describe("run store", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  const rec = (over: Partial<RunRecord> = {}): RunRecord => ({
    runId: "r1",
    kind: "pull",
    status: "running",
    percent: 10,
    phase: "adzuna",
    current: 0,
    total: 0,
    etaText: null,
    ...over,
  });

  it("upserts run progress by id", () => {
    useRunStore.getState().upsert(rec({ percent: 10 }));
    useRunStore.getState().upsert(rec({ percent: 60 }));
    expect(useRunStore.getState().runs["r1"].percent).toBe(60);
  });

  it("removes a run", () => {
    useRunStore.getState().upsert(rec({ runId: "r2", kind: "discover", percent: 0, phase: "" }));
    useRunStore.getState().remove("r2");
    expect(useRunStore.getState().runs["r2"]).toBeUndefined();
  });
});
