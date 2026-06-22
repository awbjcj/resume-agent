import { describe, expect, it } from "vitest";

import { normalizeSkill } from "./normalize";

describe("normalizeSkill (port of match_gap.normalize_skill)", () => {
  it("lowercases, drops punctuation, collapses whitespace", () => {
    expect(normalizeSkill("  Node.JS / TypeScript!! ")).toBe("node.js typescript");
    expect(normalizeSkill("C++")).toBe("c++");
    expect(normalizeSkill("C#")).toBe("c#");
    expect(normalizeSkill("Go-lang")).toBe("go lang");
  });
});
