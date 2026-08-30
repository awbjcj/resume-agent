import type { TFunction } from "i18next";

const MODEL_TIER_KEYS = {
  cheap: "model.tiers.cheap",
  mid: "model.tiers.mid",
  premium: "model.tiers.premium",
} as const;

const REASONING_EFFORT_KEYS = {
  none: "model.reasoningEfforts.none",
  minimal: "model.reasoningEfforts.minimal",
  low: "model.reasoningEfforts.low",
  medium: "model.reasoningEfforts.medium",
  high: "model.reasoningEfforts.high",
  xhigh: "model.reasoningEfforts.xhigh",
  max: "model.reasoningEfforts.max",
  ultra: "model.reasoningEfforts.ultra",
} as const;

export function modelTierLabel(t: TFunction, tier: string): string {
  const key = MODEL_TIER_KEYS[tier as keyof typeof MODEL_TIER_KEYS];
  return key ? t(key) : tier;
}

export function reasoningEffortLabel(t: TFunction, effort: string): string {
  const key = REASONING_EFFORT_KEYS[effort as keyof typeof REASONING_EFFORT_KEYS];
  return key ? t(key) : effort;
}
