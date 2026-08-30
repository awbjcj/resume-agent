import type { components } from "@/lib/api/schema";

export type LlmRate = components["schemas"]["LlmRateOut"];
export type RateCostBand = "economical" | "standard" | "premium";
export type RateSortKey = "model" | "context" | "input" | "cache" | "output" | "tool" | "hours" | "effective";
export type SortDirection = "asc" | "desc";
export type RateGroup = { key: string; provider: string; model: string; versions: LlmRate[] };

const ECONOMICAL_RATE_LIMIT_MICROS = 5_000_000;
const PREMIUM_RATE_LIMIT_MICROS = 20_000_000;

export const RATE_COST_BAND_STYLES: Record<RateCostBand, {
  rail: string;
  badge: string;
}> = {
  economical: {
    rail: "bg-chart-2",
    badge: "border-chart-2/30 bg-chart-2/10 text-chart-2",
  },
  standard: {
    rail: "bg-primary",
    badge: "border-primary/30 bg-primary/10 text-primary",
  },
  premium: {
    rail: "bg-ready",
    badge: "border-ready/30 bg-ready/10 text-ready",
  },
};

export const RATE_COST_BAND_LABEL_KEYS: Record<RateCostBand, string> = {
  economical: "adminQuota.rate.bands.economical.label",
  standard: "adminQuota.rate.bands.standard.label",
  premium: "adminQuota.rate.bands.premium.label",
};

export const RATE_COST_BAND_DETAIL_KEYS: Record<RateCostBand, string> = {
  economical: "adminQuota.rate.bands.economical.detail",
  standard: "adminQuota.rate.bands.standard.detail",
  premium: "adminQuota.rate.bands.premium.detail",
};

export const RATE_SORT_LABEL_KEYS: Record<RateSortKey, string> = {
  model: "adminQuota.rate.sort.model",
  context: "adminQuota.rate.sort.context",
  input: "adminQuota.rate.sort.input",
  cache: "adminQuota.rate.sort.cache",
  output: "adminQuota.rate.sort.output",
  tool: "adminQuota.rate.sort.tool",
  hours: "adminQuota.rate.sort.hours",
  effective: "adminQuota.rate.sort.effective",
};

export type RateVersionStatus = "active" | "scheduled" | "historical";

export function rateCostBand(rate: LlmRate): RateCostBand {
  const referenceMicros = rate.inputMicrosPerMillion + rate.outputMicrosPerMillion;
  if (referenceMicros <= ECONOMICAL_RATE_LIMIT_MICROS) return "economical";
  if (referenceMicros > PREMIUM_RATE_LIMIT_MICROS) return "premium";
  return "standard";
}

export function rateVersionStatus(rate: LlmRate, now = Date.now()): RateVersionStatus {
  if (new Date(rate.effectiveFrom).getTime() > now) return "scheduled";
  if (rate.effectiveTo && new Date(rate.effectiveTo).getTime() <= now) return "historical";
  return "active";
}

function compareNullable(a: number | null, b: number | null, direction: SortDirection): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return (a - b) * (direction === "asc" ? 1 : -1);
}

export function latestVersion(group: RateGroup): LlmRate {
  return group.versions[0];
}

export function compareRateGroups(a: RateGroup, b: RateGroup, key: RateSortKey, direction: SortDirection): number {
  const left = latestVersion(a);
  const right = latestVersion(b);
  const multiplier = direction === "asc" ? 1 : -1;
  let result = 0;

  if (key === "model") result = `${a.provider} ${a.model}`.localeCompare(`${b.provider} ${b.model}`);
  if (key === "context") result = left.contextMinTokens - right.contextMinTokens;
  if (key === "input") result = left.inputMicrosPerMillion - right.inputMicrosPerMillion;
  if (key === "cache") return compareNullable(left.cacheReadMicrosPerMillion, right.cacheReadMicrosPerMillion, direction) || a.model.localeCompare(b.model);
  if (key === "output") result = left.outputMicrosPerMillion - right.outputMicrosPerMillion;
  if (key === "tool") return compareNullable(left.toolMicrosPerUnit, right.toolMicrosPerUnit, direction) || a.model.localeCompare(b.model);
  if (key === "hours") result = (left.ratePeriod ?? "all").localeCompare(right.ratePeriod ?? "all");
  if (key === "effective") result = new Date(left.effectiveFrom).getTime() - new Date(right.effectiveFrom).getTime();

  return result * multiplier || a.model.localeCompare(b.model);
}

export function groupAndSortRates(rates: LlmRate[], sortKey: RateSortKey, direction: SortDirection): RateGroup[] {
  const grouped = new Map<string, RateGroup>();
  for (const rate of rates) {
    const key = `${rate.provider}\u0000${rate.model}`;
    const group = grouped.get(key) ?? { key, provider: rate.provider, model: rate.model, versions: [] };
    group.versions.push(rate);
    grouped.set(key, group);
  }
  return [...grouped.values()]
    .map((group) => ({
      ...group,
      versions: [...group.versions].sort(
        (a, b) => new Date(b.effectiveFrom).getTime() - new Date(a.effectiveFrom).getTime(),
      ),
    }))
    .sort((a, b) => compareRateGroups(a, b, sortKey, direction));
}
