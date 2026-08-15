import { describe, expect, it } from "vitest";

import type { ScoutProposal } from "./use-scout";
import { canAddProposal, canManuallyConfirm, verificationLabel } from "./proposals";

const source = (
  check: ScoutProposal["check"],
  overrides: Partial<NonNullable<ScoutProposal["source"]>> = {},
): ScoutProposal => ({
  id: "p1",
  kind: "source",
  status: "pending",
  check,
  checkError: "",
  dismissReason: "",
  resolvedAt: null,
  manualConfirmation: null,
  citations: [],
  reason: "",
  fitScore: null,
  term: null,
  source: {
    company: "Acme",
    url: "https://jobs.lever.co/acme",
    requestedUrl: "https://acme.example/careers",
    canonicalBoardUrl: "https://jobs.lever.co/acme",
    ats: "lever",
    token: "acme",
    roleCount: 2,
    errorCode: null,
    resolutionStatus: check === "validated" ? "verified" : check === "conflict" ? "conflict" : "unverified",
    resolutionReason: "OWNERSHIP_NOT_PROVEN",
    evidence: [],
    searchedFamilies: [],
    unsearchedFamilies: [],
    ...overrides,
  },
});

const term = (): ScoutProposal => ({
  id: "t1",
  kind: "search_term",
  status: "pending",
  check: "new",
  checkError: "",
  dismissReason: "",
  resolvedAt: null,
  manualConfirmation: null,
  citations: [],
  reason: "",
  fitScore: null,
  source: null,
  term: { value: "platform engineering", termKind: "keyword" },
});

describe("Scout proposal verification policy", () => {
  it("allows normal add only for verified sources and eligible terms", () => {
    expect(canAddProposal(source("validated"))).toBe(true);
    expect(canAddProposal(source("unverified"))).toBe(false);
    expect(canAddProposal(source("conflict"))).toBe(false);
    expect(canAddProposal(term())).toBe(true);
  });

  it("allows the manual path only for pending unverified sources", () => {
    expect(canManuallyConfirm(source("unverified"), false)).toBe(true);
    expect(canManuallyConfirm(source("unverified", { ats: null }), false)).toBe(false);
    expect(canManuallyConfirm(source("unverified", { ats: null }), true)).toBe(true);
    expect(canManuallyConfirm(source("conflict"), true)).toBe(false);
    expect(canManuallyConfirm({ ...source("unverified"), status: "added" }, true)).toBe(false);
  });

  it("makes verification state explicit in compact UI labels", () => {
    expect(verificationLabel(source("validated"))).toBe("Verified");
    expect(verificationLabel(source("unverified"))).toBe("Unverified");
    expect(verificationLabel(source("conflict"))).toBe("Ownership conflict");
    expect(verificationLabel(term())).toBeNull();
  });
});
