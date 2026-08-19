import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MatchGap } from "./use-match-gap";
import { UccmMatrixPanel } from "./UccmMatrixPanel";

const base = {
  uccmState: "ready",
  uccmErrorCode: null,
  matchingPolicyRevision: "match-v2",
  profileFactsRevision: "facts-7",
  assertionPolicyRevision: "assert-v1",
  profileProjection: {
    layers: [
      ["career_core", "Career core", "Communication"],
      ["foundational", "Foundational", "Data literacy"],
      ["transferable_function", "Transferable functions", "Program leadership"],
      ["domain_industry", "Domains & industries", "Fintech"],
      ["occupation_role", "Occupations & roles", "Platform engineering"],
      ["enabler", "Tools, languages & credentials", "Kubernetes"],
    ].map(([layer, , display], index) => ({
      layer,
      items: [{
        conceptId: `concept-${index}`,
        conceptType: "skill",
        display,
        assertionIds: [`assertion-${index}`],
        evidenceFactIds: [`fact-${index}`],
      }],
    })),
    evidenceQuality: { counts: { verified: 5, inferred: 1 }, assertionIds: ["assertion-0"] },
    developmentNeeds: [],
  },
  typedRequirements: [{
    id: "requirement-1",
    jobId: "42",
    sourceText: "Lead Kubernetes platform migrations",
    sourceStart: 0,
    sourceEnd: 35,
    provenance: "exact_span",
    parsedConceptId: "concept-5",
    parsedConceptLabel: "Kubernetes",
    conceptType: "skill",
    requirementKind: "must_have",
    strictness: "capability",
    minimumProficiency: 3,
    context: { occupation: "platform engineering" },
    importance: 1,
    evidenceExpectation: "candidate_evidence",
    recencyConstraint: null,
    extractionConfidence: 0.98,
    taxonomyRevision: "taxonomy-3",
    extractionPolicyRevision: "extract-v1",
    termDecisionId: "decision-1",
    legacySource: "must",
    legacyOrder: 0,
    exactNonSubstitutable: false,
    failureReason: null,
  }],
  matchResults: [{
    legacyCoverage: "adjacent",
    v2: {
      id: "match-1",
      requirementId: "requirement-1",
      status: "transferable",
      confidence: 0.81,
      requirementConceptId: "concept-5",
      requirementLabel: "Kubernetes",
      assertionId: "assertion-2",
      verifiedRequirementFactId: null,
      candidateConceptId: "concept-2",
      candidateLabel: "Program leadership",
      relationshipPath: null,
      features: {
        canonicalIdentity: false,
        approvedEquivalence: false,
        relationshipPredicates: [],
        relationshipDirection: null,
        taskOverlap: 0.75,
        knowledgeOverlap: 0.5,
        subskillCoverage: 0.5,
        toolFamilyCompatible: false,
        industryContextMatch: null,
        occupationContextMatch: true,
        audienceOrScaleMatch: null,
        proficiencySufficient: true,
        autonomySufficient: null,
        complexitySufficient: null,
        recencySufficient: null,
        evidenceDirectness: 0.8,
        evidenceConfidence: 0.9,
        requirementImportance: 1,
        strictness: "capability",
        lexicalSimilarity: 0.2,
        embeddingSimilarity: 0.6,
        learnedDomainMatch: false,
      },
      evidenceFactIds: ["fact-2"],
      explanationCode: "bounded_transfer",
      recommendedAction: "Validate Kubernetes-specific execution evidence.",
      matchingPolicyRevision: "match-v2",
      taxonomyRevision: "taxonomy-3",
      factsRevision: "facts-7",
      assertionPolicyRevision: "assert-v1",
      extractionPolicyRevision: "extract-v1",
      strictRequirementCredit: false,
    },
  }],
} as unknown as MatchGap;

describe("UccmMatrixPanel", () => {
  it("renders six profile layers and explains precise requirement matches", async () => {
    render(<UccmMatrixPanel data={base} />);

    expect(screen.getByRole("heading", { name: "Career capability matrix" })).toBeInTheDocument();
    for (const label of [
      "Career core",
      "Foundational",
      "Transferable functions",
      "Domains & industries",
      "Occupations & roles",
      "Tools, languages & credentials",
    ]) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }

    expect(screen.getByText("Transferable", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Legacy: adjacent")).toBeInTheDocument();
    expect(screen.getByText("Program leadership", { selector: "p" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /kubernetes/i }));
    expect(screen.getByText("Lead Kubernetes platform migrations")).toBeInTheDocument();
    expect(screen.getByText("Evidence: fact-2")).toBeInTheDocument();
    expect(screen.getByText("Validate Kubernetes-specific execution evidence.")).toBeInTheDocument();
  });

  it("keeps stale UCCM artifacts visibly separate from legacy results", () => {
    render(<UccmMatrixPanel data={{ ...base, uccmState: "stale", uccmErrorCode: "revision_mismatch" }} />);

    expect(screen.getByRole("status")).toHaveTextContent(/capability analysis is stale/i);
    expect(screen.getByRole("status")).toHaveTextContent("revision_mismatch");
    expect(screen.queryByText("Transferable", { selector: "span" })).not.toBeInTheDocument();
  });
});
