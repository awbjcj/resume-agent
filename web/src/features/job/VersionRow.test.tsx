import { describe, expect, it } from "vitest";

import { failedGateLabel } from "./VersionRow";

describe("failedGateLabel", () => {
  it("names the gate that actually blocked instead of always blaming fact-check", () => {
    // The reported symptom: 19 of 77 stored versions failed only on provenance,
    // and every one of them rendered "Fact-check failed".
    expect(failedGateLabel(["provenance"])).toBe("Fact-lock failed — provenance");
    expect(failedGateLabel(["fact-check"])).toBe("Fact-lock failed — fact-check");
  });

  it("lists every failing gate", () => {
    expect(failedGateLabel(["provenance", "fact-check"])).toBe(
      "Fact-lock failed — provenance, fact-check",
    );
  });

  it("falls back to an unqualified label when the server sent no detail", () => {
    expect(failedGateLabel([])).toBe("Fact-lock failed");
    expect(failedGateLabel(undefined)).toBe("Fact-lock failed");
  });
});
