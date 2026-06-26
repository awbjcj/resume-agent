import { describe, expect, it } from "vitest";

import { industryLabel } from "./sic-labels";

describe("industryLabel", () => {
  it("resolves a SIC major code to its label", () => {
    expect(industryLabel("07")).toBe("Agricultural Services");
    expect(industryLabel("35")).toBe("Industrial Machinery & Computer Equipment");
  });

  it("passes free-text industry values through, normalizing underscores", () => {
    expect(industryLabel("fin_tech")).toBe("fin tech");
    expect(industryLabel("Renewables")).toBe("Renewables");
  });
});
