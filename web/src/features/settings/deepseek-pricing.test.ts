import { describe, expect, it } from "vitest";

import {
  formatCountdown,
  formatUtcClock,
  getDeepSeekPricingStatus,
} from "./deepseek-pricing";

describe("getDeepSeekPricingStatus", () => {
  it("returns null before the DeepSeek peak/off-peak cutover", () => {
    expect(getDeepSeekPricingStatus(new Date("2026-08-16T15:59:00Z"))).toBeNull();
  });

  it("is off-peak just after the cutover and counts down to the first peak window", () => {
    const now = new Date("2026-08-16T16:00:00Z");
    expect(getDeepSeekPricingStatus(now)).toEqual({
      period: "off_peak",
      changesAt: new Date("2026-08-17T01:00:00Z"),
      now,
    });
  });

  it("is peak inside 01:00-04:00 UTC and counts down to 04:00", () => {
    const now = new Date("2026-08-17T02:30:00Z");
    expect(getDeepSeekPricingStatus(now)).toEqual({
      period: "peak",
      changesAt: new Date("2026-08-17T04:00:00Z"),
      now,
    });
  });

  it("is off-peak at the 04:00 boundary itself (half-open band)", () => {
    const now = new Date("2026-08-17T04:00:00Z");
    expect(getDeepSeekPricingStatus(now)).toEqual({
      period: "off_peak",
      changesAt: new Date("2026-08-17T06:00:00Z"),
      now,
    });
  });

  it("is peak inside 06:00-10:00 UTC and counts down to 10:00", () => {
    const now = new Date("2026-08-17T09:00:00Z");
    expect(getDeepSeekPricingStatus(now)).toEqual({
      period: "peak",
      changesAt: new Date("2026-08-17T10:00:00Z"),
      now,
    });
  });

  it("rolls over past the last boundary of the day to tomorrow's first peak", () => {
    const now = new Date("2026-08-17T23:45:00Z");
    expect(getDeepSeekPricingStatus(now)).toEqual({
      period: "off_peak",
      changesAt: new Date("2026-08-18T01:00:00Z"),
      now,
    });
  });
});

describe("formatCountdown", () => {
  it("drops the hours segment when under an hour", () => {
    expect(formatCountdown(45 * 60_000)).toBe("45m");
  });

  it("drops the minutes segment on an exact hour", () => {
    expect(formatCountdown(2 * 60 * 60_000)).toBe("2h");
  });

  it("shows both segments otherwise", () => {
    expect(formatCountdown(2 * 60 * 60_000 + 14 * 60_000)).toBe("2h 14m");
  });
});

describe("formatUtcClock", () => {
  it("zero-pads hours and minutes", () => {
    expect(formatUtcClock(new Date("2026-08-17T04:05:00Z"))).toBe("04:05");
  });
});
