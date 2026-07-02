import { describe, expect, it } from "vitest";

import { firstIncompleteStep, STEPS } from "./SetupWizard";

const status = (over: object) => ({
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false }, sources: { enabledCount: 0 }, complete: false,
  ...over,
});

describe("firstIncompleteStep", () => {
  it("starts at keys on a fresh install", () => {
    expect(firstIncompleteStep(status({}))).toBe("keys");
  });
  it("resumes at search when keys and documents are done", () => {
    expect(
      firstIncompleteStep(status({
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: null, githubUsername: null },
      })),
    ).toBe("search");
  });
  it("lands on finish when every step is done", () => {
    expect(
      firstIncompleteStep(status({
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: null, githubUsername: null },
        search: { configured: true }, sources: { enabledCount: 2 },
      })),
    ).toBe("finish");
  });
  it("exposes exactly four steps", () => {
    expect(STEPS.map((s) => s.slug)).toEqual(["keys", "documents", "search", "sources"]);
  });
});
