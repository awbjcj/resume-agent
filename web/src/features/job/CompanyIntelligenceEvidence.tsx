import { AlertTriangle, CircleAlert, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";
import { ResearchNotice } from "./ResearchPanel";

type Evidence = components["schemas"]["CompanyIntelligenceEvidenceOut"];
type Insight = components["schemas"]["CompanyIntelligenceInsightOut"];
type Source = components["schemas"]["CompanyIntelligenceSourceOut"];

const AXIS_LABELS: Record<Insight["axis"], string> = {
  strategy: "Strategy",
  recent_moves: "Recent moves",
  engineering_culture: "Engineering culture",
  challenges: "Challenges",
  competitive_position: "Competitive position",
};

const VERIFICATION_LABELS: Record<Insight["verificationState"], string> = {
  corroborated: "Corroborated",
  single_source: "Single source",
  inferred: "Inference",
};

const SOURCE_TIER_LABELS: Record<Source["sourceTier"], string> = {
  company_official: "Company official",
  government_or_regulatory: "Government or regulatory",
  reputable_independent: "Reputable independent",
  employee_or_community: "Employee or community",
  other: "Other public source",
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function citationLabel(url: string, sources: readonly Source[]): string {
  return sources.find((source) => source.url === url)?.title || new URL(url).hostname;
}

function InsightCard({ insight, sources }: { insight: Insight; sources: readonly Source[] }) {
  return (
    <Card className="gap-0 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
          {AXIS_LABELS[insight.axis]}
        </h3>
        <Badge variant="outline">{VERIFICATION_LABELS[insight.verificationState]}</Badge>
      </div>
      <p className="mt-2 text-[15px] leading-7">{insight.summary}</p>
      {insight.whyItMatters && (
        <p className="mt-3 border-t pt-3 text-sm leading-6 text-muted-foreground">
          <span className="font-semibold text-foreground">Candidate lens: </span>
          {insight.whyItMatters}
        </p>
      )}
      {insight.conflictingEvidence && (
        <p className="mt-3 text-sm leading-6 text-amber-800 dark:text-amber-200">
          <span className="font-semibold">Conflicting evidence: </span>
          {insight.conflictingEvidence}
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2 border-t pt-3">
        {(insight.citations ?? []).map((url) => (
          <a
            key={url}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-full border bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground transition-[border-color,color,transform] duration-150 ease-out-strong hover:border-primary/40 hover:text-primary active:scale-[0.98] motion-reduce:transform-none"
          >
            {citationLabel(url, sources)}
            <ExternalLink className="size-3" aria-hidden="true" />
          </a>
        ))}
      </div>
    </Card>
  );
}

function SourceList({ sources }: { sources: readonly Source[] }) {
  return (
    <Card className="gap-0 p-5">
      <h3 id="company-intelligence-sources" className="font-heading text-lg font-semibold">
        Sources
      </h3>
      <ul className="mt-4 divide-y" aria-labelledby="company-intelligence-sources">
        {sources.map((source) => (
          <li
            key={source.url}
            className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <p className="font-medium">{source.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground capitalize">
                {source.publisher || new URL(source.url).hostname} · {SOURCE_TIER_LABELS[source.sourceTier]}
              </p>
              {source.publishedAt && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Published {formatDate(source.publishedAt)}
                </p>
              )}
            </div>
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-9 shrink-0 items-center gap-1.5 self-start rounded-lg px-2 text-sm font-semibold text-primary underline-offset-4 transition-[background-color,transform] duration-150 ease-out-strong hover:bg-primary/5 hover:underline active:scale-[0.98] motion-reduce:transform-none sm:self-auto"
            >
              Open source <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function CompanyIntelligenceEvidence({
  evidence,
  isStale,
  history,
  historyLoading,
}: {
  evidence: Evidence;
  isStale: boolean;
  history: readonly Evidence[];
  historyLoading: boolean;
}) {
  const sources = evidence.sources ?? [];
  const insights = evidence.insights ?? [];

  return (
    <div className="space-y-5">
      <Card className="gap-0 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{sources.length} sources</Badge>
          <Badge variant="outline">{evidence.researchDepth} research</Badge>
          <Badge variant="outline">Version {evidence.versionNumber}</Badge>
          {isStale && <Badge variant="outline">May be outdated</Badge>}
          <span className="text-xs text-muted-foreground">
            Researched {formatDate(evidence.retrievedAt)}
          </span>
        </div>
        {evidence.overview && (
          <p className="mt-4 max-w-4xl text-[15px] leading-7 text-foreground/85">
            {evidence.overview}
          </p>
        )}
      </Card>

      {isStale && (
        <ResearchNotice
          icon={<AlertTriangle className="size-4" />}
          className="border-amber-300/60 bg-amber-50/70 text-amber-950 dark:border-amber-800 dark:bg-amber-950/25 dark:text-amber-100"
        >
          This saved research is past its freshness window. It remains visible until you choose to refresh it.
        </ResearchNotice>
      )}

      {evidence.previousVersionId && (
        <Card className="gap-0 p-5">
          <h3 className="font-heading text-lg font-semibold">What changed</h3>
          {[
            ...(evidence.changes?.addedAxes ?? []).map((axis) => `Added ${AXIS_LABELS[axis]}`),
            ...(evidence.changes?.changedAxes ?? []).map((axis) => `Updated ${AXIS_LABELS[axis]}`),
            ...(evidence.changes?.removedAxes ?? []).map((axis) => `Removed ${AXIS_LABELS[axis]}`),
          ].length > 0 || (evidence.changes?.addedSourceUrls ?? []).length > 0 || (evidence.changes?.removedSourceUrls ?? []).length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2">
              {[
                ...(evidence.changes?.addedAxes ?? []).map((axis) => `Added ${AXIS_LABELS[axis]}`),
                ...(evidence.changes?.changedAxes ?? []).map((axis) => `Updated ${AXIS_LABELS[axis]}`),
                ...(evidence.changes?.removedAxes ?? []).map((axis) => `Removed ${AXIS_LABELS[axis]}`),
                ...((evidence.changes?.addedSourceUrls ?? []).length ? [`Added ${(evidence.changes?.addedSourceUrls ?? []).length} source(s)`] : []),
                ...((evidence.changes?.removedSourceUrls ?? []).length ? [`Removed ${(evidence.changes?.removedSourceUrls ?? []).length} source(s)`] : []),
              ].map((item) => <li key={item}><Badge variant="secondary">{item}</Badge></li>)}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">No material evidence changes were detected.</p>
          )}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {insights.map((insight) => (
          <InsightCard key={insight.axis} insight={insight} sources={sources} />
        ))}
      </div>

      <SourceList sources={sources} />

      <details className="rounded-lg border bg-card px-5 py-4">
        <summary className="cursor-pointer font-semibold">Research history</summary>
        {historyLoading ? (
          <p className="mt-3 text-sm text-muted-foreground">Loading history…</p>
        ) : (
          <ol className="mt-3 divide-y">
            {history.map((item) => (
              <li key={item.versionId ?? `${item.versionNumber}-${item.retrievedAt}`} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
                <span className="font-medium">Version {item.versionNumber} · {item.researchDepth}</span>
                <span className="text-xs text-muted-foreground">{formatDate(item.retrievedAt)}</span>
              </li>
            ))}
          </ol>
        )}
      </details>

      <ResearchNotice
        icon={<CircleAlert className="size-4" />}
        className="border-border bg-muted/40 text-muted-foreground"
      >
        {evidence.caveat}
      </ResearchNotice>
    </div>
  );
}
