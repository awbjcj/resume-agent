/** Shared semantic palette and the permanent small-sample rule. */

import type { TFunction } from "i18next";

import i18n from "@/i18n";

export const SUPPRESS_BELOW = 3;
export const GREY_BELOW = 10;

export type RateConfidence = "suppressed" | "low" | "ok";

export function rateConfidence(sampleSize: number): RateConfidence {
  if (sampleSize < SUPPRESS_BELOW) return "suppressed";
  if (sampleSize < GREY_BELOW) return "low";
  return "ok";
}

export const CHART_COLORS = {
  categorical: ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"],
  flow: "var(--chart-1)",
  rejected: "var(--destructive)",
  noResponse: "var(--chart-5)",
  withdrawn: "var(--muted-foreground)",
} as const;

const STAGE_LABEL_KEYS: Record<string, string> = {
  application_submitted: "applicationTimeline.stages.applicationSubmitted",
  recruiter_screen: "applicationTimeline.stages.recruiterScreen",
  online_assessment: "applicationTimeline.stages.onlineAssessment",
  questionnaire: "applicationTimeline.stages.questionnaire",
  technical_phone_screen: "applicationTimeline.stages.technicalPhoneScreen",
  technical_round: "applicationTimeline.stages.technicalRound",
  system_design: "applicationTimeline.stages.systemDesign",
  behavioral: "applicationTimeline.stages.behavioral",
  hiring_manager: "applicationTimeline.stages.hiringManager",
  onsite_loop: "applicationTimeline.stages.onsiteLoop",
  team_match: "applicationTimeline.stages.teamMatch",
  offer_received: "applicationTimeline.stages.offerReceived",
  rejected: "applicationTimeline.stages.rejected",
  no_response: "applicationTimeline.stages.noResponse",
  withdrawn: "applicationTimeline.stages.withdrawn",
};

export function stageLabel(kind: string, t?: TFunction): string {
  const key = STAGE_LABEL_KEYS[kind];
  if (!key) return kind;
  return t ? t(key) : i18n.t(key);
}

export const STAGE_ORDER = [
  "application_submitted",
  "recruiter_screen",
  "online_assessment",
  "questionnaire",
  "technical_phone_screen",
  "technical_round",
  "system_design",
  "behavioral",
  "hiring_manager",
  "onsite_loop",
  "team_match",
  "offer_received",
] as const;

export const axisProps = {
  tick: { fill: "var(--muted-foreground)", fontSize: 12 },
  axisLine: { stroke: "var(--border)" },
  tickLine: false,
};

export const tooltipProps = {
  contentStyle: {
    borderColor: "var(--border)",
    borderRadius: "var(--radius-md)",
    background: "var(--popover)",
    color: "var(--popover-foreground)",
  },
};
