import { describe, expect, it } from "vitest";

import { industryLabel } from "./industry-label";

describe("industryLabel", () => {
  it("preserves canonical readable names", () => {
    expect(industryLabel("Fintech")).toBe("Fintech");
    expect(industryLabel("Autonomous Driving")).toBe("Autonomous Driving");
  });

  it("replaces underscore separators without changing the canonical wording", () => {
    expect(industryLabel("Digital_Health")).toBe("Digital Health");
  });
});
