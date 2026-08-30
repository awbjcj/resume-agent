import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTranslation } from "react-i18next";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { ConversionChart } from "./ConversionChart";
import { useAnalytics, useTimelineAnalytics } from "./use-analytics";
import { StageFlowChart } from "./StageFlowChart";
import { CycleTimeChart } from "./CycleTimeChart";
import { PipelineTimelineChart } from "./PipelineTimelineChart";
import { OfferComparisonChart } from "./OfferComparisonChart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { components } from "@/lib/api/schema";

type Cohort = components["schemas"]["CohortOut"];

function CohortTable({
  caption,
  header,
  rows,
}: {
  caption: string;
  header: string;
  rows: Cohort[];
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
      {/* `caption-top` overrides the shadcn default: this caption is the table's
          heading, and rendering it below the rows meant the reader met seven
          unexplained columns before learning what they were counting. */}
      <Table className="caption-top">
        <caption className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {caption}
        </caption>
        <TableHeader>
          <TableRow>
            <TableHead>{header}</TableHead>
            <TableHead>{t("analytics.table.applications")}</TableHead>
            <TableHead>{t("analytics.table.responses")}</TableHead>
            <TableHead>{t("analytics.table.interviews")}</TableHead>
            <TableHead>{t("analytics.table.offers")}</TableHead>
            <TableHead>{t("analytics.table.interviewRate")}</TableHead>
            <TableHead>{t("analytics.table.offerRate")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((c) => (
            <TableRow key={c.label}>
              <TableCell>{c.label}</TableCell>
              <TableCell>{c.applications}</TableCell>
              <TableCell>{c.responses}</TableCell>
              <TableCell>{c.interviews}</TableCell>
              <TableCell>{c.offers}</TableCell>
              <TableCell>{c.interviewRate}</TableCell>
              <TableCell>{c.offerRate}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function AnalyticsContainer() {
  const { t } = useTranslation();
  const { data, isLoading } = useAnalytics();
  const timeline = useTimelineAnalytics();
  if (isLoading || timeline.isLoading) return <BoardSkeleton />;

  const totalApps = data?.bySource.reduce((a, c) => a + c.applications, 0) ?? 0;
  const totalOffers = data?.bySource.reduce((a, c) => a + c.offers, 0) ?? 0;

  return (
    <>
      <PageHeader
        kicker={t("analytics.header.kicker")}
        title={t("analytics.header.title")}
        sub={t("analytics.header.description")}
      />
      <MetricRow
        items={[
          [t("analytics.metrics.submitted"), String(totalApps)],
          [t("analytics.metrics.offers"), String(totalOffers)],
          [t("analytics.metrics.sourcesTracked"), String(data?.bySource.length ?? 0)],
        ]}
      />
      <div className="grid min-w-0 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle><h2>{t("analytics.panels.stageFlow.title")}</h2></CardTitle><CardDescription>{t("analytics.panels.stageFlow.description")}</CardDescription></CardHeader>
          <CardContent><StageFlowChart flows={timeline.data?.flows ?? []} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle><h2>{t("analytics.panels.cycleTime.title")}</h2></CardTitle><CardDescription>{t("analytics.panels.cycleTime.description")}</CardDescription></CardHeader>
          <CardContent><CycleTimeChart cycleTimes={timeline.data?.cycleTimes ?? []} /></CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle><h2>{t("analytics.panels.activePipeline.title")}</h2></CardTitle><CardDescription>{t("analytics.panels.activePipeline.description")}</CardDescription></CardHeader>
          <CardContent><PipelineTimelineChart pipeline={timeline.data?.activePipeline ?? []} /></CardContent>
        </Card>
        {(timeline.data?.offers.length ?? 0) > 0 ? (
          <Card className="xl:col-span-2">
            <CardHeader><CardTitle><h2>{t("analytics.panels.offerComparison.title")}</h2></CardTitle><CardDescription>{t("analytics.panels.offerComparison.description")}</CardDescription></CardHeader>
            <CardContent><OfferComparisonChart offers={timeline.data!.offers} /></CardContent>
          </Card>
        ) : null}
      </div>
      {totalApps === 0 ? (
        <EmptyState
          title={t("analytics.empty.title")}
          body={t("analytics.empty.description")}
        />
      ) : (
        <div className="space-y-8">
          <ConversionChart rows={data!.bySource} />
          <CohortTable caption={t("analytics.table.bySource")} header={t("analytics.table.source")} rows={data!.bySource} />
          <CohortTable caption={t("analytics.table.byFitBand")} header={t("analytics.table.fitBand")} rows={data!.byBand} />
        </div>
      )}
    </>
  );
}
