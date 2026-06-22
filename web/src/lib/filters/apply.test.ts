import { describe, expect, it } from "vitest";

import { applyFilters } from "./apply";
import { emptyFilterState, type ShortlistItem } from "./types";

const base = (over: Partial<ShortlistItem> = {}): ShortlistItem =>
  ({
    jobId: 1,
    company: "Acme",
    title: "Eng",
    location: "NYC",
    fitScore: 70,
    fitRationale: null,
    sponsorshipSignal: null,
    salaryMin: null,
    salaryMax: 120000,
    salaryCurrency: "USD",
    remotePolicy: "remote",
    seniority: "senior",
    employmentType: "full_time",
    industry: "tech",
    companySize: "large",
    postedAt: null,
    skills: [],
    sicMajor: "73",
    sicLabel: "Services",
    sicDivision: "I",
    locationCountry: "US",
    locationRegion: "NY",
    locationCity: "New York",
    ...over,
  }) as ShortlistItem;

describe("applyFilters (port of filtering._passes)", () => {
  it("filters by USD salary max below salaryMin", () => {
    const rows = [base({ salaryMax: 90000 }), base({ jobId: 2, salaryMax: 150000 })];
    const state = { ...emptyFilterState(), salaryMin: 100000 };
    expect(applyFilters(rows, state).map((row) => row.jobId)).toEqual([2]);
  });

  it("does not gate non-USD salaries", () => {
    const rows = [base({ salaryMax: 10, salaryCurrency: "JPY" })];
    const state = { ...emptyFilterState(), salaryMin: 100000 };
    expect(applyFilters(rows, state)).toHaveLength(1);
  });

  it("gates by fitMin only when score present", () => {
    const rows = [base({ fitScore: 50 }), base({ jobId: 2, fitScore: null })];
    const state = { ...emptyFilterState(), fitMin: 60 };
    expect(applyFilters(rows, state).map((row) => row.jobId)).toEqual([2]);
  });

  it("keeps multi-select facet rows with null value as neutral", () => {
    const rows = [base({ remotePolicy: null }), base({ jobId: 2, remotePolicy: "onsite" })];
    const state = { ...emptyFilterState(), remote: new Set(["remote"]) };
    expect(applyFilters(rows, state).map((row) => row.jobId)).toEqual([1]);
  });

  it("skills require any-token overlap", () => {
    const rows = [
      base({ skills: [{ name: "Go", covered: false, required: true }] }),
      base({ jobId: 2, skills: [{ name: "Rust", covered: false, required: true }] }),
    ];
    const state = { ...emptyFilterState(), skills: new Set(["go"]) };
    expect(applyFilters(rows, state).map((row) => row.jobId)).toEqual([1]);
  });
});
