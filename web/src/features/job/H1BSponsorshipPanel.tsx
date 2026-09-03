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
import { Bar, BarChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { components } from "@/lib/api/schema";
import { useCheckH1BSponsorship } from "./use-job-mutations";
import { ACTIVE_RUN_STATUSES, latestArtifactRun, useArtifactRunIndex } from "./artifact-runs";
import { ResearchNotice, ResearchPanelHeader, type NoticeTone } from "./ResearchPanel";
import type { JobDetail } from "./use-job-detail";

type SponsorshipResult = components["schemas"]["H1BSponsorshipOut"];
type Evidence = NonNullable<SponsorshipResult["evidence"]>;
type EvidenceStatus = Evidence["status"];
type PeriodStat = NonNullable<Evidence["periods"]>[number];

const filingChartConfig = {
  filingCount: {
    label: "H-1B filings",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

type StatusMeta = {
  label: string;
  description: string;
  icon: LucideIcon;
  tone: NoticeTone;
};

const STATUS_META: Record<EvidenceStatus, StatusMeta> = {
  matched: {
    label: "Historical filings found",
    description: "The H-1B history contains filings associated with this company.",
    icon: BadgeCheck,
    tone: "success",
  },
  no_match: {
    label: "No historical filings matched",
    description: "The research did not find a matching historical filing record.",
    icon: CircleX,
    tone: "danger",
  },
  unavailable: {
    label: "Research unavailable",
    description: "The H-1B source did not return usable evidence for this check.",
    icon: CircleAlert,
    tone: "warning",
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
  activePeriodLabel,
}: {
  evidence: Evidence;
  metrics: Pick<
    PeriodStat,
    "filingCount" | "certifiedCount" | "deniedCount" | "wageSummary"
  >;
  activePeriodLabel?: string;
}) {
  const wageSummary = Object.entries(metrics.wageSummary ?? {});
  const filingPeriods = activePeriodLabel
    ? [periodLabel(activePeriodLabel)]
    : evidence.periods?.length
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

function SponsorshipTrend({
  periods,
  selectedPeriod,
}: {
  periods: PeriodStat[];
  selectedPeriod: string;
}) {
  const chartData = periods
    .slice()
    .reverse()
    .map((entry) => ({
      period: entry.period,
      label: periodLabel(entry.period),
      shortLabel: periodLabel(entry.period).replace(/^FY\d{2}(\d{2})\s/, "$1 "),
      filingCount: entry.filingCount ?? 0,
    }));
  const selected = periods.find((entry) => entry.period === selectedPeriod);

  return (
    <div className="mt-5 rounded-lg border bg-muted/10 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">Three-year filing volume</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Quarterly H-1B filings in the server cache.
          </p>
        </div>
        <p className="text-xs font-medium text-foreground">
          {periodLabel(selectedPeriod)}: {selected?.filingCount ?? 0} filings
        </p>
      </div>
      <ChartContainer
        config={filingChartConfig}
        className="h-56 w-full"
        aria-hidden="true"
      >
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="shortLabel" tickLine={false} axisLine={false} minTickGap={12} />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={42} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ReferenceLine
            x={chartData.find((entry) => entry.period === selectedPeriod)?.shortLabel}
            stroke="var(--foreground)"
            strokeDasharray="3 3"
          />
          <Bar dataKey="filingCount" fill="var(--color-filingCount)" radius={4} />
        </BarChart>
      </ChartContainer>
      <ul className="sr-only">
        {chartData.map((entry) => (
          <li key={entry.period}>
            {entry.label}: {entry.filingCount} H-1B filings
          </li>
        ))}
      </ul>
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
  const runIndex = useArtifactRunIndex();
  const h1bRun = latestArtifactRun(runIndex, "h1bSponsorship", "jobId", jobId);
  const checking = h1bRun !== undefined && ACTIVE_RUN_STATUSES.includes(h1bRun.status);
  const failed = h1bRun?.status === "failed";
  const result = initialResult ?? null;
  const evidence = result?.evidence ?? null;
  const status = evidence?.status ?? null;
  const periods = evidence?.periods ?? [];
  const latestPeriod = periods[0]?.period ?? "";
  const [periodSelection, setPeriodSelection] = useState(() => ({
    jobId,
    period: latestPeriod,
  }));
  const selectedPeriod = periodSelection.jobId === jobId ? periodSelection.period : latestPeriod;
  const effectivePeriod = periods.some((entry) => entry.period === selectedPeriod)
    ? selectedPeriod
    : latestPeriod;
  const activePeriod = periods.find((entry) => entry.period === effectivePeriod);
  const metrics = activePeriod ?? {
    filingCount: evidence?.filingCount ?? null,
    certifiedCount: evidence?.certifiedCount ?? null,
    deniedCount: evidence?.deniedCount ?? null,
    wageSummary: evidence?.wageSummary ?? null,
  };
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
      className="space-y-5"
      aria-labelledby="h1b-sponsorship-title"
      aria-busy={checking}
    >
      <ResearchPanelHeader
        titleId="h1b-sponsorship-title"
        icon={<ShieldCheck className="size-5" aria-hidden="true" />}
        eyebrow="Research signal"
        title="Historical H-1B sponsorship"
        description="Check employer filing history without changing the posting’s current sponsorship signal."
        context={
          company?.trim()
            ? "Refreshing updates every job at this company."
            : undefined
        }
        action={
          <Button
            type="button"
            variant="outline"
            className="w-full sm:w-auto"
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
        }
      />

      <Card className="gap-0 p-5">
        <ResearchNotice
          icon={<StatusIcon className="size-4" />}
          tone={meta?.tone ?? "neutral"}
        >
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
        </ResearchNotice>

      {evidence && result?.stale && (
        <ResearchNotice
          icon={<CalendarClock className="size-4" />}
          className="mt-4" tone="warning"
        >
          Checked {formatDate(evidence.retrievedAt)} — may be out of date
        </ResearchNotice>
      )}

      {evidence && status !== "unavailable" && periods.length > 0 && (
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="h1b-period">Period</Label>
            <Select
              value={effectivePeriod}
              onValueChange={(value) => setPeriodSelection({ jobId, period: value ?? latestPeriod })}
            >
              <SelectTrigger id="h1b-period" className="w-full sm:w-64">
                <SelectValue>
                  {(value: string) => periodLabel(String(value))}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
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

      {evidence && status !== "unavailable" && periods.length > 0 && effectivePeriod && (
        <SponsorshipTrend periods={periods} selectedPeriod={effectivePeriod} />
      )}

      {evidence && status !== "unavailable" && (
        <EvidenceDetails
          evidence={evidence}
          metrics={metrics}
          activePeriodLabel={activePeriod?.period}
        />
      )}

      {evidence?.status === "unavailable" && message && (
        <ResearchNotice
          icon={<CircleAlert className="size-4" />}
          className="mt-4" tone="warning"
        >
          {message}
        </ResearchNotice>
      )}

      {failed && (
        <ResearchNotice
          icon={<CircleAlert className="size-4" />}
          className="mt-4" tone="danger"
          role="alert"
        >
          {errorMessage}
        </ResearchNotice>
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
      </Card>
    </section>
  );
}
