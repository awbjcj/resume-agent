import { describe, expect, it } from "vitest";

import { scorePassword } from "./strength";

describe("scorePassword", () => {
  it("rates long mixed passwords above short or repetitive passwords", () => {
    const strong = scorePassword("quartz-Lantern-42-drift!").score;
    expect(strong).toBeGreaterThan(scorePassword("abc").score);
    expect(strong).toBeGreaterThan(scorePassword("aaaaaaaaaaaaaaaa").score);
  });
});
