import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { applyFilters } from "./apply";
import { sortRows } from "./sort";
import { emptyFilterState, type FilterState, type ShortlistItem } from "./types";

const here = dirname(fileURLToPath(import.meta.url));
const contractPath = resolve(here, "../../../../contracts/shortlist_filter.contract.json");
const contract = JSON.parse(readFileSync(contractPath, "utf-8")) as {
  now: string;
  cases: {
    name: string;
    filterState: Record<string, unknown>;
    rows: Partial<ShortlistItem>[];
    expected: number[];
  }[];
};

const SET_KEYS = new Set([
  "remote",
  "sponsorship",
  "seniority",
  "employmentType",
  "industry",
  "country",
  "region",
  "city",
  "companySize",
  "skills",
]);

function rowFromWire(d: Partial<ShortlistItem>): ShortlistItem {
  return {
    jobId: 0,
    company: null,
    title: null,
    location: null,
    fitScore: null,
    fitRationale: null,
    sponsorshipSignal: null,
    salaryMin: null,
    salaryMax: null,
    salaryCurrency: null,
    remotePolicy: null,
    seniority: null,
    employmentType: null,
    industry: null,
    companySize: null,
    postedAt: null,
    skills: [],
    sicMajor: null,
    sicLabel: null,
    sicDivision: null,
    locationCountry: null,
    locationRegion: null,
    locationCity: null,
    ...d,
  } as ShortlistItem;
}

function filterStateFromWire(d: Record<string, unknown>): FilterState {
  const state = emptyFilterState();
  for (const [k, v] of Object.entries(d)) {
    if (SET_KEYS.has(k)) {
      (state as unknown as Record<string, unknown>)[k] = new Set(v as string[]);
    } else {
      (state as unknown as Record<string, unknown>)[k] = v;
    }
  }
  return state;
}

describe("TS satisfies the shortlist filter contract", () => {
  const now = new Date(contract.now);
  for (const c of contract.cases) {
    it(c.name, () => {
      const rows = c.rows.map(rowFromWire);
      const state = filterStateFromWire(c.filterState);
      const out = sortRows(applyFilters(rows, state), state, now);
      expect(out.map((r) => r.jobId)).toEqual(c.expected);
    });
  }
});
