import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "./store";

describe("run store", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("upserts run progress by id", () => {
    useRunStore
      .getState()
      .upsert({ runId: "r1", kind: "pull", status: "running", percent: 10, phase: "adzuna" });
    useRunStore
      .getState()
      .upsert({ runId: "r1", kind: "pull", status: "running", percent: 60, phase: "adzuna" });
    expect(useRunStore.getState().runs["r1"].percent).toBe(60);
  });

  it("removes a run", () => {
    useRunStore
      .getState()
      .upsert({ runId: "r2", kind: "discover", status: "running", percent: 0, phase: "" });
    useRunStore.getState().remove("r2");
    expect(useRunStore.getState().runs["r2"]).toBeUndefined();
  });
});
