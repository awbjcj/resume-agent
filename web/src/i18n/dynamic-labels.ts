import zhCN from "./dynamic-zh-CN.json";

import { runLabel, runLabelKey, type RunLabelKey } from "@/lib/runs/labels";

type Translate = (key: RunLabelKey) => string;

const PLACEHOLDER = "{{value}}";

function isChinese(language: string | null | undefined): boolean {
  return language?.toLowerCase().startsWith("zh") ?? false;
}

function translateTemplate(table: Record<string, string>, value: string): string | null {
  if (table[value]) return table[value];

  let bestMatch: { sourceLength: number; translation: string } | null = null;
  for (const [source, translation] of Object.entries(table)) {
    const marker = source.indexOf(PLACEHOLDER);
    if (marker === -1) continue;
    const prefix = source.slice(0, marker);
    const suffix = source.slice(marker + PLACEHOLDER.length);
    if (value.startsWith(prefix) && value.endsWith(suffix)) {
      const sourceLength = prefix.length + suffix.length;
      if (!bestMatch || sourceLength > bestMatch.sourceLength) {
        bestMatch = {
          sourceLength,
          translation: translation.replace(PLACEHOLDER, value.slice(prefix.length, value.length - suffix.length)),
        };
      }
    }
  }
  return bestMatch?.translation ?? null;
}

export function localizeRunKind(kind: string, language: string | null | undefined, t: Translate): string {
  const key = runLabelKey(kind);
  if (key) return t(key);
  return isChinese(language) ? zhCN.fallbacks.unknownRun : runLabel(kind);
}

export function localizeRunPhase(phase: string, language: string | null | undefined): string {
  if (!phase || !isChinese(language)) return phase;
  return translateTemplate(zhCN.runPhases, phase) ?? zhCN.fallbacks.working;
}

export function localizeRunError(error: string | null | undefined, language: string | null | undefined): string | null {
  if (!error) return null;
  if (!isChinese(language)) return error;
  return zhCN.runErrors[error as keyof typeof zhCN.runErrors]
    ?? (error.startsWith("GmailNotConnected:")
      ? zhCN.runErrors["GmailNotConnected: Gmail is not connected for this workspace"]
      : zhCN.fallbacks.operationFailed);
}

export function localizeSourceMode(mode: string, language: string | null | undefined): string {
  if (!isChinese(language)) return mode;
  return zhCN.sourceModes[mode as keyof typeof zhCN.sourceModes] ?? zhCN.fallbacks.unknownMode;
}

export function localizeSourceFragmentStatus(status: string, language: string | null | undefined): string {
  if (!isChinese(language)) return status;
  return zhCN.sourceFragmentStatuses[status as keyof typeof zhCN.sourceFragmentStatuses]
    ?? zhCN.fallbacks.unknownStatus;
}

const EN_RUN_STATUSES: Record<string, string> = {
  queued: "queued",
  cancelling: "cancelling",
  succeeded: "done",
  failed: "failed",
  cancelled: "cancelled",
};

export function localizeRunStatus(status: string, language: string | null | undefined): string {
  if (!isChinese(language)) return EN_RUN_STATUSES[status] ?? status;
  return zhCN.runStatuses[status as keyof typeof zhCN.runStatuses] ?? zhCN.fallbacks.unknownStatus;
}

const ETA_UNIT_LABELS: Record<string, string> = {
  h: "小时",
  m: "分",
  s: "秒",
};

/**
 * Formats the compact ETA emitted by the run API without exposing its English
 * units in Chinese mode. The API currently emits forms such as `10m 14s`.
 */
export function localizeRunEta(etaText: string | null | undefined, language: string | null | undefined): string | null {
  if (!etaText) return null;
  if (!isChinese(language)) return `~${etaText} left`;

  const parts = Array.from(etaText.matchAll(/(\d+)\s*([hms])/gi));
  const remainder = etaText.replace(/(\d+)\s*([hms])/gi, "").replace(/[~\s]/g, "");
  if (parts.length === 0 || remainder) return zhCN.fallbacks.etaUnknown;

  const duration = parts
    .map(([, amount, unit]) => `${amount} ${ETA_UNIT_LABELS[unit.toLowerCase()]}`)
    .join(" ");
  return `约剩 ${duration}`;
}
