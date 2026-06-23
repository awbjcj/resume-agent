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
import { useMatchGap } from "./use-match-gap";

export function MatchGapContainer() {
  const { data, isLoading } = useMatchGap();
  if (isLoading) return <BoardSkeleton />;

  return (
    <>
      <PageHeader
        kicker="Closed loop"
        title="Match / Gap"
        sub="Skills your target jobs demand that your profile does not show yet. Read-only."
      />
      <MetricRow
        items={[
          ["Target jobs", String(data?.targetTotal ?? 0)],
          ["Distinct gaps", String(data?.gaps.length ?? 0)],
        ]}
      />
      {!data || data.targetTotal === 0 ? (
        <EmptyState
          title="No target jobs yet"
          body="Shortlist or approve jobs to populate the gap report."
        />
      ) : data.gaps.length === 0 ? (
        <EmptyState
          title="No gaps"
          body="Your profile covers every required skill across your target jobs."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-[0_1px_2px_rgba(24,32,38,0.04)]">
          <Table>
            <caption className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Most-demanded missing skills
            </caption>
            <TableHeader>
              <TableRow>
                <TableHead>Skill</TableHead>
                <TableHead>Demanded by</TableHead>
                <TableHead>Share %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.gaps.map((g) => (
                <TableRow key={g.skill}>
                  <TableCell>{g.skill}</TableCell>
                  <TableCell>
                    {g.demandCount}/{g.targetTotal}
                  </TableCell>
                  <TableCell>{g.demandShare}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
