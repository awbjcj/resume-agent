import { describe, expect, it } from "vitest";

import { applyFilters } from "./apply";
import { emptyFilterState } from "./types";

describe("applyFilters (port of filtering._passes)", () => {
  it("returns an empty list for empty input", () => {
    expect(applyFilters([], emptyFilterState())).toEqual([]);
  });
});
