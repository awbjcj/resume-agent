import { describe, expect, it } from "vitest";

import { emptyFilterState } from "@/lib/filters/types";
import { paramsToState, stateToParams } from "./use-board-filters";

describe("filter URL serialization", () => {
  it("round-trips a populated state", () => {
    const s = {
      ...emptyFilterState(),
      fitMin: 70,
      rejectReason: "sponsorship",
      sort: "composite" as const,
      preset: "pay_first" as const,
      remote: new Set(["remote", "hybrid"]),
      skills: new Set(["go"]),
    };
    const round = paramsToState(stateToParams(s));
    expect(round.fitMin).toBe(70);
    expect(round.rejectReason).toBe("sponsorship");
    expect(round.sort).toBe("composite");
    expect(round.preset).toBe("pay_first");
    expect([...round.remote].sort()).toEqual(["hybrid", "remote"]);
    expect([...round.skills]).toEqual(["go"]);
  });

  it("empty state produces no params", () => {
    expect(stateToParams(emptyFilterState()).toString()).toBe("");
  });

  it("uses the board-specific default sort without serializing it", () => {
    const state = paramsToState(new URLSearchParams(), "recency");
    expect(state.sort).toBe("recency");
    expect(stateToParams(state, "recency").has("sort")).toBe(false);
  });
});
