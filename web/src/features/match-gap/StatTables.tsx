import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { StatRow } from "./aggregate";

function StatTable({ title, rows }: { title: string; rows: StatRow[] }) {
  return (
    <section aria-label={title} className="overflow-hidden border-y bg-card">
      <div className="border-b px-5 py-4">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {title}
        </h2>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Segment</TableHead>
            <TableHead>Top demand</TableHead>
            <TableHead className="text-right">Gaps</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell className="font-medium">{row.key}</TableCell>
              <TableCell className="max-w-64 truncate text-muted-foreground">
                {row.topSkills.map((skill) => skill.skill).join(", ")}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">{row.gapCount}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && (
        <p className="px-5 py-6 text-sm text-muted-foreground">No matching segments.</p>
      )}
    </section>
  );
}

export function StatTables({
  byCompany,
  byPosition,
}: {
  byCompany: StatRow[];
  byPosition: StatRow[];
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <StatTable title="By company" rows={byCompany} />
      <StatTable title="By position" rows={byPosition} />
    </div>
  );
}
