/** Shared semantic palette and the permanent small-sample rule. */

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

export const STAGE_LABELS: Record<string, string> = {
  application_submitted: "Application submitted",
  recruiter_screen: "Recruiter screen",
  online_assessment: "Online assessment",
  questionnaire: "Questionnaire",
  technical_phone_screen: "Technical phone screen",
  technical_round: "Technical round",
  system_design: "System design",
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager",
  onsite_loop: "Onsite loop",
  team_match: "Team match",
  offer_received: "Offer received",
  rejected: "Rejected",
  no_response: "No response",
  withdrawn: "Withdrawn",
};

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
