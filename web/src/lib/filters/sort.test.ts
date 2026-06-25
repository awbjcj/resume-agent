import { describe, expect, it } from "vitest";

import { compositeScore } from "./sort";
import type { ShortlistItem } from "./types";

const NOW = new Date("2026-06-22T00:00:00Z");

const row = (over: Partial<ShortlistItem>): ShortlistItem =>
  ({
    jobId: 0,
    salaryMin: null,
    salaryMax: null,
    salaryCurrency: "USD",
    fitScore: null,
    postedAt: null,
    skills: [],
    ...over,
  }) as ShortlistItem;

describe("compositeScore (port of filtering.composite_score)", () => {
  it("uses neutral 50 for missing fit/salary/recency under balanced", () => {
    expect(compositeScore(row({}), "balanced", NOW)).toBe(50);
  });

  it("clamps future-dated recency to 100, not above", () => {
    const future = new Date(NOW.getTime() + 10 * 86_400_000).toISOString();
    const score = compositeScore(row({ postedAt: future, fitScore: 50 }), "freshest", NOW);
    expect(score).toBeLessThanOrEqual(100);
  });
});
