import type { TFunction } from "i18next";

export enum ApplicationTimelineStage {
  ApplicationSubmitted = "application_submitted",
  RecruiterScreen = "recruiter_screen",
  OnlineAssessment = "online_assessment",
  Questionnaire = "questionnaire",
  TechnicalPhoneScreen = "technical_phone_screen",
  TechnicalRound = "technical_round",
  SystemDesign = "system_design",
  Behavioral = "behavioral",
  HiringManager = "hiring_manager",
  OnsiteLoop = "onsite_loop",
  TeamMatch = "team_match",
  OfferReceived = "offer_received",
  OfferDeadline = "offer_deadline",
  Rejected = "rejected",
  NoResponse = "no_response",
  Withdrawn = "withdrawn",
  Custom = "custom",
}

const STATUS_LABEL_KEYS: Record<string, string> = {
  ready: "application.statuses.ready",
  submitted: "application.statuses.submitted",
  interview: "application.statuses.interview",
  offer: "application.statuses.offer",
  rejected: "application.statuses.rejected",
  closed: "application.statuses.closed",
};

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
  offer_deadline: "applicationTimeline.stages.offerDeadline",
  rejected: "applicationTimeline.stages.rejected",
  no_response: "applicationTimeline.stages.noResponse",
  withdrawn: "applicationTimeline.stages.withdrawn",
  custom: "applicationTimeline.stages.custom",
};

const RESULT_LABEL_KEYS: Record<string, string> = {
  pending: "applicationTimeline.results.pending",
  advanced: "applicationTimeline.results.advanced",
  rejected: "applicationTimeline.results.rejected",
  no_response: "applicationTimeline.results.noResponse",
  cancelled: "applicationTimeline.results.cancelled",
  withdrew: "applicationTimeline.results.withdrew",
};

const MODALITY_LABEL_KEYS: Record<string, string> = {
  onsite: "applicationTimeline.modalities.onsite",
  virtual: "applicationTimeline.modalities.virtual",
  phone: "applicationTimeline.modalities.phone",
  async: "applicationTimeline.modalities.async",
};

const PLATFORM_LABEL_KEYS: Record<string, string> = {
  zoom: "applicationTimeline.platforms.zoom",
  teams: "applicationTimeline.platforms.teams",
  google_meet: "applicationTimeline.platforms.googleMeet",
  webex: "applicationTimeline.platforms.webex",
  tencent_meeting: "applicationTimeline.platforms.tencentMeeting",
  feishu: "applicationTimeline.platforms.feishu",
  phone: "applicationTimeline.platforms.phone",
  hackerrank: "applicationTimeline.platforms.hackerrank",
  codesignal: "applicationTimeline.platforms.codesignal",
  coderpad: "applicationTimeline.platforms.coderpad",
  karat: "applicationTimeline.platforms.karat",
  other: "applicationTimeline.platforms.other",
};

function labelFor(t: TFunction, keys: Record<string, string>, value: string): string {
  const key = keys[value];
  return key ? t(key) : value;
}

export function applicationStatusLabel(t: TFunction, value: string): string {
  return labelFor(t, STATUS_LABEL_KEYS, value);
}

export function applicationStageLabel(t: TFunction, value: string): string {
  return labelFor(t, STAGE_LABEL_KEYS, value);
}

export function applicationResultLabel(t: TFunction, value: string): string {
  return labelFor(t, RESULT_LABEL_KEYS, value);
}

export function applicationModalityLabel(t: TFunction, value: string): string {
  return labelFor(t, MODALITY_LABEL_KEYS, value);
}

export function applicationPlatformLabel(t: TFunction, value: string): string {
  return labelFor(t, PLATFORM_LABEL_KEYS, value);
}
