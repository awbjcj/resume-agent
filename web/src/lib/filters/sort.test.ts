import { describe, expect, it } from "vitest";

import { compositeScore, sortRows } from "./sort";
import { emptyFilterState, type ShortlistItem } from "./types";

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

describe("sortRows", () => {
  it("sorts by fit desc with nulls last", () => {
    const rows = [
      row({ jobId: 1, fitScore: 40 }),
      row({ jobId: 2, fitScore: null }),
      row({ jobId: 3, fitScore: 90 }),
    ];
    const out = sortRows(rows, { ...emptyFilterState(), sort: "fit" }, NOW);
    expect(out.map((item) => item.jobId)).toEqual([3, 1, 2]);
  });

  it("sorts by salary desc using salaryMax then salaryMin", () => {
    const rows = [
      row({ jobId: 1, salaryMax: 100 }),
      row({ jobId: 2, salaryMin: 200 }),
      row({ jobId: 3, salaryMax: null }),
    ];
    const out = sortRows(rows, { ...emptyFilterState(), sort: "salary" }, NOW);
    expect(out.map((item) => item.jobId)).toEqual([2, 1, 3]);
  });
});
