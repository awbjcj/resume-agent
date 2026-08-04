import { useState } from "react";

import {
  BadgeCheck,
  CalendarClock,
  CircleAlert,
  CircleX,
  ExternalLink,
  FileCheck2,
  LoaderCircle,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/lib/runs/store";
import { useCheckH1BSponsorship } from "./use-job-mutations";
import { ACTIVE_RUN_STATUSES, latestArtifactRun } from "./artifact-runs";
import type { JobDetail } from "./use-job-detail";

type SponsorshipResult = components["schemas"]["H1BSponsorshipOut"];
type Evidence = NonNullable<SponsorshipResult["evidence"]>;
type EvidenceStatus = Evidence["status"];
type PeriodStat = NonNullable<Evidence["periods"]>[number];

const ROLLUP = "__rollup__";

type StatusMeta = {
  label: string;
  description: string;
  icon: LucideIcon;
  tone: string;
};

const STATUS_META: Record<EvidenceStatus, StatusMeta> = {
  matched: {
    label: "Historical filings found",
    description: "The H-1B history contains filings associated with this company.",
    icon: BadgeCheck,
    tone: "border-emerald-200/80 bg-emerald-50/80 text-emerald-950 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-100",
  },
  no_match: {
    label: "No historical filings matched",
    description: "The research did not find a matching historical filing record.",
    icon: CircleX,
    tone: "border-rose-200/80 bg-rose-50/80 text-rose-950 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-100",
  },
  unavailable: {
    label: "Research unavailable",
    description: "The H-1B source did not return usable evidence for this check.",
    icon: CircleAlert,
    tone: "border-amber-200/80 bg-amber-50/80 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100",
  },
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatMetricLabel(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** "FY2026-Q1" reads as "FY2026 Q1" -- provider labels are opaque, so only
 * separators are prettified, never reordered or reparsed. */
function periodLabel(period: string): string {
  return period.replace(/[-_]+/g, " ");
}

function formatWage(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border bg-muted/20 px-3 py-2.5">
      <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 truncate text-sm font-medium text-foreground" title={value}>
        {value}
      </dd>
    </div>
  );
}

function EvidenceDetails({
  evidence,
  metrics,
}: {
  evidence: Evidence;
  metrics: Pick<
    PeriodStat,
    "filingCount" | "certifiedCount" | "deniedCount" | "wageSummary"
  >;
}) {
  const wageSummary = Object.entries(metrics.wageSummary ?? {});
  const filingPeriods = evidence.periods?.length
    ? evidence.periods.map((entry) => periodLabel(entry.period))
    : evidence.fiscalPeriods;
  const details: Array<readonly [string, string]> = [
    ["Company", evidence.displayCompany ?? evidence.normalizedCompany],
    [
      "Filing periods",
      filingPeriods.length ? filingPeriods.join(", ") : "Not reported",
    ],
    ["Filings", metrics.filingCount == null ? "Not reported" : String(metrics.filingCount)],
    [
      "Certified filings",
      metrics.certifiedCount == null ? "Not reported" : String(metrics.certifiedCount),
    ],
    ...(evidence.periods?.length
      ? [
          [
            "Denied filings",
            metrics.deniedCount == null ? "Not reported" : String(metrics.deniedCount),
          ] as const,
        ]
      : []),
    ["Confidence", `${Math.round(evidence.confidence * 100)}%`],
    ["Retrieved", formatDate(evidence.retrievedAt)],
    ["Expires", formatDate(evidence.expiresAt)],
    ["Data version", evidence.dataVersion ?? "Not reported"],
  ];

  return (
    <div className="mt-5 space-y-4 border-t pt-5">
      <div className="flex items-center gap-2">
        <FileCheck2 className="size-4 text-muted-foreground" aria-hidden="true" />
        <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Evidence details
        </h4>
      </div>
      <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {details.map(([label, value]) => (
          <DetailItem key={label} label={label} value={value} />
        ))}
      </dl>
      {wageSummary.length > 0 && (
        <div>
          <h5 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Wage summary
          </h5>
          <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {wageSummary.map(([label, value]) => (
              <DetailItem
                key={label}
                label={formatMetricLabel(label)}
                value={formatWage(value)}
              />
            ))}
          </dl>
        </div>
      )}
      {evidence.sourceUrl && (
        <a
          href={evidence.sourceUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Open source record
          <ExternalLink className="size-3.5" aria-hidden="true" />
        </a>
      )}
      <p className="rounded-lg border border-dashed bg-muted/20 px-3 py-2.5 text-xs leading-5 text-muted-foreground">
        {evidence.caveat}
      </p>
    </div>
  );
}

export function H1BSponsorshipPanel({
  jobId,
  company,
  initialResult,
}: {
  jobId: number;
  company: string | null;
  initialResult?: JobDetail["h1BSponsorship"];
}) {
  const check = useCheckH1BSponsorship(jobId);
  const runs = useRunStore((state) => state.runs);
  const h1bRun = latestArtifactRun(runs, "h1bSponsorship", "jobId", jobId);
  const checking = h1bRun !== undefined && ACTIVE_RUN_STATUSES.includes(h1bRun.status);
  const failed = h1bRun?.status === "failed";
  const result = initialResult ?? null;
  const evidence = result?.evidence ?? null;
  const status = evidence?.status ?? null;
  const periods = evidence?.periods ?? [];
  const [periodSelection, setPeriodSelection] = useState(() => ({
    jobId,
    period: ROLLUP,
  }));
  const selectedPeriod = periodSelection.jobId === jobId ? periodSelection.period : ROLLUP;
  const effectivePeriod =
    selectedPeriod === ROLLUP || periods.some((entry) => entry.period === selectedPeriod)
      ? selectedPeriod
      : ROLLUP;
  const activePeriod =
    effectivePeriod === ROLLUP
      ? undefined
      : periods.find((entry) => entry.period === effectivePeriod);
  const metrics = activePeriod ?? {
    filingCount: evidence?.filingCount ?? null,
    certifiedCount: evidence?.certifiedCount ?? null,
    deniedCount: evidence?.deniedCount ?? null,
    wageSummary: evidence?.wageSummary ?? null,
  };
  const rollupLabel = `Last ${periods.length} quarter${periods.length === 1 ? "" : "s"} (total)`;
  const meta = status ? STATUS_META[status] : null;
  const disabled = !company?.trim() || checking || result?.capability === "disabled";
  const errorMessage = h1bRun?.error ?? "The manual H-1B check failed.";
  const message = result?.message ?? evidence?.unavailableReason ?? null;
  const StatusIcon = meta?.icon ?? (result?.capability === "disabled" ? CircleAlert : ShieldCheck);
  const buttonLabel = checking
    ? "Checking…"
    : result?.capability === "disabled"
      ? "H-1B disabled"
      : result?.stale
        ? "Refresh"
        : status === "unavailable"
          ? "Try again"
          : status
            ? "Refresh check"
            : "Check H-1B";

  return (
    <section
      className="rounded-xl border bg-card p-5 shadow-card"
      aria-labelledby="h1b-sponsorship-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <ShieldCheck className="size-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Research signal
            </p>
            <h3 id="h1b-sponsorship-title" className="mt-1 text-base font-semibold">
              Historical H-1B sponsorship
            </h3>
            <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">
              Check employer filing history without changing the posting’s current sponsorship signal.
            </p>
            {company?.trim() && (
              <p className="mt-1 text-xs text-muted-foreground">
                Refreshing updates every job at this company.
              </p>
            )}
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="w-full shrink-0 sm:w-auto"
          aria-label={`${buttonLabel} for H-1B sponsorship`}
          title={company ? `Check historical H-1B filings for ${company}` : "A company is required"}
          disabled={disabled}
          onClick={() => check.mutate()}
        >
          {checking ? (
            <LoaderCircle className="animate-spin" aria-hidden="true" />
          ) : (
            <StatusIcon aria-hidden="true" />
          )}
          {buttonLabel}
        </Button>
      </div>

      <div
        className={cn(
          "mt-5 flex items-start gap-3 rounded-lg border px-3.5 py-3",
          meta?.tone ?? "border-border bg-muted/20",
        )}
        role="status"
        aria-live="polite"
      >
        <StatusIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">
              {meta?.label ??
                (result?.capability === "disabled"
                  ? "Research disabled"
                  : result?.capability === "unavailable"
                    ? "No result yet"
                    : "Ready to check")}
            </p>
            {status && <Badge variant={status === "matched" ? "secondary" : status === "no_match" ? "destructive" : "outline"}>{status}</Badge>}
          </div>
          <p className="mt-1 text-sm leading-5 opacity-80">
            {meta?.description ??
              (message ||
                (!company?.trim()
                  ? "Add a company name before running a manual check."
                  : "Run a manual check to fetch historical employer evidence."))}
          </p>
        </div>
      </div>

      {evidence && result?.stale && (
        <p className="mt-4 text-xs text-amber-700 dark:text-amber-400">
          ⚠ Checked {formatDate(evidence.retrievedAt)} — may be out of date
        </p>
      )}

      {evidence && status !== "unavailable" && periods.length > 0 && (
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="h1b-period">Period</Label>
            <Select
              value={effectivePeriod}
              onValueChange={(value) => setPeriodSelection({ jobId, period: value ?? ROLLUP })}
            >
              <SelectTrigger id="h1b-period" className="w-full sm:w-64">
                <SelectValue>
                  {(value: string) =>
                    effectivePeriod === ROLLUP
                      ? rollupLabel
                      : periodLabel(String(value))
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ROLLUP}>{rollupLabel}</SelectItem>
                {periods.map((entry) => (
                  <SelectItem key={entry.period} value={entry.period}>
                    {periodLabel(entry.period)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      {evidence && status !== "unavailable" && (
        <EvidenceDetails evidence={evidence} metrics={metrics} />
      )}

      {evidence?.status === "unavailable" && message && (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50/70 px-3.5 py-3 text-sm leading-6 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
          {message}
        </p>
      )}

      {failed && (
        <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-sm leading-6 text-destructive">
          {errorMessage}
        </p>
      )}

      {evidence?.status === "unavailable" && (
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          The check is safe to retry. A failed provider lookup is not treated as a no-match.
        </p>
      )}
      {!company?.trim() && (
        <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <CalendarClock className="size-3.5" aria-hidden="true" />
          Add the employer name to enable this check.
        </p>
      )}
    </section>
  );
}
