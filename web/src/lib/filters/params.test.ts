import { describe, expect, it } from "vitest";

import { boardFilterToParams } from "./params";
import { emptyFilterState } from "./types";

describe("boardFilterToParams", () => {
  it("joins sets, aliases camel keys, and omits empties", () => {
    const s = emptyFilterState();
    s.source = new Set(["adzuna", "lever"]);
    s.seniority = new Set(["senior"]);
    s.fitMin = 60;
    s.q = "acme";
    s.rejectReason = "sponsorship";
    const p = boardFilterToParams(s, { page: 2, pageSize: 50 });
    expect(p.source).toBe("adzuna,lever");
    expect(p.seniority).toBe("senior");
    expect(p.minFit).toBe("60");
    expect(p.q).toBe("acme");
    expect(p.rejectReason).toBe("sponsorship");
    expect(p.page).toBe("2");
    expect(p.sortBy).toBe("fit");
    expect("city" in p).toBe(false);
  });
});
