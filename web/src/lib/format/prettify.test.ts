import { describe, expect, it } from "vitest";
import { cleanJobDescriptionText, prettifyPlainText } from "./prettify";

describe("prettifyPlainText", () => {
  it("preserves every line of newline-heavy legacy text", () => {
    const out = prettifyPlainText("Line one\nLine two\nLine three");
    expect(out.split("\n")).toHaveLength(3);
    expect(out).toContain("Line one");
    expect(out).toContain("Line three");
  });

  it("normalizes bullet glyphs to dashes", () => {
    expect(prettifyPlainText("• Build APIs")).toBe("- Build APIs");
    expect(prettifyPlainText("* Ship features")).toBe("- Ship features");
  });

  it("leaves markdown headings and existing dashes intact", () => {
    expect(prettifyPlainText("## Responsibilities")).toBe("## Responsibilities");
    expect(prettifyPlainText("- already a bullet")).toBe("- already a bullet");
  });

  it("returns empty string for empty input", () => {
    expect(prettifyPlainText("")).toBe("");
  });
});

describe("cleanJobDescriptionText", () => {
  it("removes source chrome icon tokens and escaped bold markers", () => {
    const raw =
      "Google \\_corporate\\_fare\\_ Google \\_place\\_ San Francisco, CA " +
      "\\_laptop\\_windows\\_ Remote eligible \\*\\*Mid\\*\\* role";

    expect(cleanJobDescriptionText(raw)).toBe(
      "Google Google San Francisco, CA Remote eligible Mid role",
    );
  });

  it("preserves real markdown bold", () => {
    expect(cleanJobDescriptionText("Build **payment** systems")).toBe(
      "Build **payment** systems",
    );
  });
});
