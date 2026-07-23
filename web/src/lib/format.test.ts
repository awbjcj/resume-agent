import { describe, expect, it } from "vitest";

import { formatLocationText, locationLabel } from "./format";

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
});
