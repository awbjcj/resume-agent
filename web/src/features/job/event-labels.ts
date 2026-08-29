export const KIND_LABELS: Record<string, string> = {
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
  offer_deadline: "Offer deadline",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  custom: "Other",
};

export const PLATFORM_LABELS: Record<string, string> = {
  zoom: "Zoom",
  teams: "Microsoft Teams",
  google_meet: "Google Meet",
  webex: "Webex",
  tencent_meeting: "Tencent Meeting",
  feishu: "Feishu",
  phone: "Phone",
  hackerrank: "HackerRank",
  codesignal: "CodeSignal",
  coderpad: "CoderPad",
  karat: "Karat",
  other: "Other",
};

export const MODALITY_LABELS: Record<string, string> = {
  onsite: "Onsite",
  virtual: "Virtual",
  phone: "Phone",
  async: "Async",
};

export const RESULT_LABELS: Record<string, string> = {
  pending: "Pending",
  advanced: "Advanced",
  rejected: "Rejected",
  no_response: "No response",
  cancelled: "Cancelled",
  withdrew: "Withdrew",
};

export const REPEATABLE_KINDS = new Set(["technical_round", "offer_received"]);
