import { describe, expect, it } from "vitest";

import { industryLabel } from "./industry-label";

describe("industryLabel", () => {
  it("does not reinterpret extracted industry values as SIC codes", () => {
    expect(industryLabel("07")).toBe("07");
    expect(industryLabel("35")).toBe("35");
  });

  it("passes free-text industry values through, normalizing underscores", () => {
    expect(industryLabel("fin_tech")).toBe("fin tech");
    expect(industryLabel("Renewables")).toBe("Renewables");
  });
});
