import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BoardSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { ConversionChart } from "./ConversionChart";
import { useAnalytics } from "./use-analytics";
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
            <TableHead>Apps</TableHead>
            <TableHead>Responses</TableHead>
            <TableHead>Interviews</TableHead>
            <TableHead>Offers</TableHead>
            <TableHead>Interview %</TableHead>
            <TableHead>Offer %</TableHead>
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
  const { data, isLoading } = useAnalytics();
  if (isLoading) return <BoardSkeleton />;

  const totalApps = data?.bySource.reduce((a, c) => a + c.applications, 0) ?? 0;
  const totalOffers = data?.bySource.reduce((a, c) => a + c.offers, 0) ?? 0;

  return (
    <>
      <PageHeader
        kicker="Conversion"
        title="Analytics / Funnel"
        sub="Which sources and fit-score bands actually convert. Rates are share of submitted applications."
      />
      <MetricRow
        items={[
          ["Submitted", String(totalApps)],
          ["Offers", String(totalOffers)],
          ["Sources tracked", String(data?.bySource.length ?? 0)],
        ]}
      />
      {totalApps === 0 ? (
        <EmptyState
          title="No applications tracked yet"
          body="Mark applications as submitted in the Pipeline board to populate analytics."
        />
      ) : (
        <div className="space-y-8">
          <ConversionChart rows={data!.bySource} />
          <CohortTable caption="By source" header="Source" rows={data!.bySource} />
          <CohortTable caption="By fit-score band" header="Fit band" rows={data!.byBand} />
        </div>
      )}
    </>
  );
}
