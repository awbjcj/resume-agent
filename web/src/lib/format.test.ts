import { describe, expect, it } from "vitest";

import { fieldLabel, formatLocationText, locationLabel } from "./format";

describe("location display formatting", () => {
  it("normalizes all-caps place names and country codes in raw locations", () => {
    expect(formatLocationText("SAN FRANCISCO, CALIFORNIA, us")).toBe(
      "San Francisco, California, US",
    );
    expect(formatLocationText("remote - ie")).toBe("Remote - IE");
  });

  it("normalizes structured facets before card, table, and modal rendering", () => {
    expect(
      locationLabel({
        location: "ignored",
        locationCity: "BENGALURU",
        locationRegion: "KARNATAKA",
        locationCountry: "in",
      }),
    ).toBe("Bengaluru, Karnataka, IN");
  });

  it.each([
    {
      raw: "San Francisco, CA | New York City, NY | Seattle, WA",
      city: null,
      region: null,
      country: "US",
    },
    {
      raw: "New York City, NY; San Francisco, CA; Seattle, WA",
      city: "San Francisco",
      region: "CA",
      country: "US",
    },
    {
      raw: "Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA | New York City, NY",
      city: "Remote-Friendly",
      region: null,
      country: "US",
    },
  ])("keeps every provider location in $raw", ({ raw, city, region, country }) => {
    expect(
      locationLabel({
        location: raw,
        locationCity: city,
        locationRegion: region,
        locationCountry: country,
      }),
    ).toBe(raw.replaceAll("; ", " | "));
  });

  it("renders canonical location instances consistently across providers", () => {
    expect(
      locationLabel({
        location: "provider-specific ignored value",
        locations: [
          { city: "AUSTIN", region: "tx", country: "us", raw: "Austin TX" },
          { city: "TORONTO", region: "Ontario", country: "ca", raw: "Toronto" },
        ],
      }),
    ).toBe("Austin, TX, US | Toronto, Ontario, CA");
  });

  it("keeps the remote qualifier on a structured country-only instance", () => {
    expect(
      locationLabel({
        locations: [
          { city: null, region: null, country: "us", raw: "Remote - US" },
        ],
      }),
    ).toBe("Remote - US");
  });

  it("upper-cases a dotted abbreviation instead of lowercasing after its first letter", () => {
    expect(formatLocationText("remote - U.S")).toBe("Remote - U.S");
    expect(formatLocationText("New York, N.Y.")).toBe("New York, N.Y.");
  });
});

describe("fieldLabel", () => {
  it("title-cases a snake_case job-brief value", () => {
    expect(fieldLabel("full_time")).toBe("Full Time");
    expect(fieldLabel("part_time")).toBe("Part Time");
    expect(fieldLabel("senior")).toBe("Senior");
  });

  it("upper-cases known acronyms instead of title-casing them", () => {
    expect(fieldLabel("ai")).toBe("AI");
    expect(fieldLabel("artificial_intelligence_and_ml")).toBe("Artificial Intelligence and ML");
    expect(fieldLabel("h1b")).toBe("H1B");
    expect(fieldLabel("saas")).toBe("SAAS");
  });

  it("keeps connector words lowercase mid-phrase but capitalizes them as the first word", () => {
    expect(fieldLabel("media_and_entertainment")).toBe("Media and Entertainment");
    expect(fieldLabel("food_and_beverage")).toBe("Food and Beverage");
    expect(fieldLabel("and_the_rest")).toBe("And the Rest");
  });

  it("never capitalizes and/or", () => {
    expect(fieldLabel("visa_and/or_relocation")).toBe("Visa and/or Relocation");
  });

  it("handles null/undefined/empty gracefully", () => {
    expect(fieldLabel(null)).toBe("");
    expect(fieldLabel(undefined)).toBe("");
    expect(fieldLabel("")).toBe("");
  });
});
