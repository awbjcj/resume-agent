import { describe, expect, it } from "vitest";

import { timeAgo } from "./time-ago";

const NOW = 1_700_000_000_000;

describe("timeAgo", () => {
  it("says just now under a minute", () => {
    expect(timeAgo(NOW - 30_000, NOW)).toBe("just now");
  });
  it("reports minutes, hours, days", () => {
    expect(timeAgo(NOW - 5 * 60_000, NOW)).toBe("5m ago");
    expect(timeAgo(NOW - 3 * 3_600_000, NOW)).toBe("3h ago");
    expect(timeAgo(NOW - 2 * 86_400_000, NOW)).toBe("2d ago");
  });
});
