import { describe, expect, it } from "vitest";

import { dateInputParts, formatCalendarDate, zonedDateTimeToIso } from "./calendar-date";

describe("calendar-date", () => {
  it("keeps an all-day UTC date stable instead of converting it to local time", () => {
    expect(dateInputParts("2026-03-09T00:00:00Z", true).date).toBe("2026-03-09");
    expect(
      formatCalendarDate("2026-03-09T00:00:00Z", true, { month: "short", day: "numeric" }, "en-US"),
    ).toBe("Mar 9");
  });

  it("round-trips a timed event through its named timezone across DST", () => {
    expect(dateInputParts("2026-03-09T19:00:00Z", false, "America/New_York")).toEqual({
      date: "2026-03-09",
      time: "15:00",
    });
    expect(zonedDateTimeToIso("2026-03-09", "15:00", "America/New_York")).toBe(
      "2026-03-09T19:00:00.000Z",
    );
  });

  it("rejects a nonexistent spring-forward wall time", () => {
    expect(() =>
      zonedDateTimeToIso("2026-03-08", "02:30", "America/New_York"),
    ).toThrow(/does not exist/i);
  });

  it("uses the earlier occurrence for an ambiguous fall-back wall time", () => {
    expect(zonedDateTimeToIso("2026-11-01", "01:30", "America/New_York")).toBe(
      "2026-11-01T05:30:00.000Z",
    );
  });
});
