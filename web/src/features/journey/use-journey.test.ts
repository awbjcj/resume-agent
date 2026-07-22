import { describe, expect, it } from "vitest";

import type { DashboardSummary } from "@/features/dashboard/use-dashboard-summary";
import type { SetupStatus } from "@/features/settings/use-setup-status";

import { deriveJourney, JOURNEY_STAGES, type JourneyStageId } from "./use-journey";

const emptyStatus: SetupStatus = {
  complete: false,
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false },
  sources: { enabledCount: 0 },
};

const emptySummary: DashboardSummary = {
  statusCounts: {},
  queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
  applied: 0,
  openErrorCount: 0,
  activeInterviews: [],
  activeCoachSession: null,
};

const stateById = (stages: ReturnType<typeof deriveJourney>["stages"]) =>
  Object.fromEntries(stages.map((s) => [s.id, s.state])) as Record<JourneyStageId, string>;

describe("deriveJourney", () => {
  it("puts a brand-new user at the profile step with nothing done", () => {
    const j = deriveJourney(emptyStatus, emptySummary);
    expect(j.currentStep).toBe("profile");
    expect(j.completedCount).toBe(0);
    expect(j.total).toBe(JOURNEY_STAGES.length);
    expect(j.complete).toBe(false);
    expect(stateById(j.stages)).toEqual({
      profile: "current",
      sources: "upcoming",
      pull: "upcoming",
      shortlist: "upcoming",
      tailor: "upcoming",
    });
  });

  it("advances to sources once a profile is built", () => {
    const j = deriveJourney(
      { ...emptyStatus, profile: { ...emptyStatus.profile, hasResume: true, factsBuiltAt: "2026-07-01T00:00:00Z" } },
      emptySummary,
    );
    expect(j.currentStep).toBe("sources");
    expect(stateById(j.stages).profile).toBe("done");
    expect(stateById(j.stages).sources).toBe("current");
  });

  it("requires both a search and an enabled source to clear the sources step", () => {
    const built = { ...emptyStatus, profile: { ...emptyStatus.profile, hasResume: true, factsBuiltAt: "x" } };
    // search configured but no sources → still on sources
    expect(deriveJourney({ ...built, search: { configured: true } }, emptySummary).currentStep).toBe("sources");
    // both present → advances to pull
    const ready = { ...built, search: { configured: true }, sources: { enabledCount: 2 } };
    expect(deriveJourney(ready, emptySummary).currentStep).toBe("pull");
  });

  it("treats a funnel of only rejected jobs as not yet pulled", () => {
    const ready = {
      ...emptyStatus,
      profile: { ...emptyStatus.profile, hasResume: true, factsBuiltAt: "x" },
      search: { configured: true },
      sources: { enabledCount: 1 },
    };
    const onlyRejected = { ...emptySummary, statusCounts: { rejected: 5 } };
    expect(deriveJourney(ready, onlyRejected).currentStep).toBe("pull");
  });

  it("moves through shortlist and tailor as jobs progress", () => {
    const ready = {
      ...emptyStatus,
      profile: { ...emptyStatus.profile, hasResume: true, factsBuiltAt: "x" },
      search: { configured: true },
      sources: { enabledCount: 1 },
    };
    // pulled but nothing shortlisted → shortlist is current
    const pulled = { ...emptySummary, statusCounts: { raw: 4, filtered: 2 } };
    expect(deriveJourney(ready, pulled).currentStep).toBe("shortlist");
    // shortlisted but not tailored → tailor is current
    const shortlisted = { ...emptySummary, statusCounts: { shortlisted: 3, approved: 1 } };
    expect(deriveJourney(ready, shortlisted).currentStep).toBe("tailor");
  });

  it("reports completion once something is tailored", () => {
    const ready = {
      ...emptyStatus,
      profile: { ...emptyStatus.profile, hasResume: true, factsBuiltAt: "x" },
      search: { configured: true },
      sources: { enabledCount: 1 },
    };
    const done = { ...emptySummary, statusCounts: { shortlisted: 2, tailored: 1, rendered: 1 } };
    const j = deriveJourney(ready, done);
    expect(j.currentStep).toBeNull();
    expect(j.complete).toBe(true);
    expect(j.completedCount).toBe(j.total);
    expect(j.stages.every((s) => s.state === "done")).toBe(true);
  });
});
