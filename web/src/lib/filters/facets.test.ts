import { describe, expect, it } from "vitest";

import {
  availableCities,
  availableCountries,
  availableSkillCloud,
  availableStates,
} from "./facets";
import type { ShortlistItem } from "./types";

const row = (over: Partial<ShortlistItem>): ShortlistItem =>
  ({ skills: [], ...over }) as ShortlistItem;

describe("location facets (port of filtering.available_*)", () => {
  const rows = [
    row({ locationCountry: "US", locationRegion: "NY", locationCity: "New York" }),
    row({ locationCountry: "US", locationRegion: "CA", locationCity: "San Jose" }),
    row({ locationCountry: "UK", locationRegion: null, locationCity: "London" }),
  ];

  it("countries are sorted and unique", () => {
    expect(availableCountries(rows)).toEqual(["UK", "US"]);
  });

  it("states honor the selected-country filter", () => {
    expect(availableStates(rows, new Set(["US"]))).toEqual(["CA", "NY"]);
  });

  it("cities honor country and state filters", () => {
    expect(availableCities(rows, new Set(["US"]), new Set(["NY"]))).toEqual(["New York"]);
  });
});

describe("availableSkillCloud", () => {
  it("merges by normalized token, ORs flags, and sorts covered first", () => {
    const rows = [
      row({ skills: [{ name: "Go", covered: false, required: true }] }),
      row({ skills: [{ name: "go", covered: true, required: false }] }),
      row({ skills: [{ name: "Rust", covered: false, required: false }] }),
    ];

    const cloud = availableSkillCloud(rows);
    const go = cloud.find((tag) => tag.name.toLowerCase() === "go");

    expect(go?.covered).toBe(true);
    expect(go?.required).toBe(true);
    expect(cloud[0]?.name).toBe("Go");
    expect(cloud[1]?.name).toBe("Rust");
  });
});
