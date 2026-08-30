import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { applicationStatusLabel } from "./application-labels";
import type { RoleComparison } from "./use-role-comparison";
import { useTranslation } from "react-i18next";

type Item = RoleComparison["items"][number];

function companyEvidence(item: Item): string {
  const evidence = item.companyEvidence;
  if (evidence.state !== "ready") return "Not researched";
  const verification = evidence.strongestVerification?.replace("_", " ") ?? "no claims";
  const freshness = evidence.isStale ? "stale" : "current";
  return `${evidence.researchDepth ?? "unknown depth"} · ${evidence.sourceCount ?? 0} sources · ${verification} · ${freshness}`;
}

function sponsorship(status: Item["h1BStatus"]): string {
  if (status === "matched") return "Historical filing match";
  if (status === "no_match") return "No historical match";
  if (status === "unavailable") return "Research unavailable";
  return "Not checked";
}

export function RoleComparisonTable({ comparison }: { comparison: RoleComparison }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="role-comparison-title" className="space-y-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
          Stored evidence only
        </p>
        <h2 id="role-comparison-title" className="mt-1 text-lg font-semibold">
          Role comparison
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Missing values stay explicit; this table does not call a model or guess an answer.
        </p>
      </div>
      <div className="min-w-0 overflow-x-auto rounded-lg border bg-card shadow-card">
        <Table className="min-w-[980px]">
          <TableHeader>
            <TableRow>
              <TableHead>Role</TableHead>
              <TableHead>Fit</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Company evidence</TableHead>
              <TableHead>H-1B evidence</TableHead>
              <TableHead>Latest offer</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparison.items.map((item) => (
              <TableRow key={item.jobId}>
                <TableCell className="min-w-56">
                  <p className="font-medium">{item.company || "Unknown company"}</p>
                  <p className="text-sm text-muted-foreground">{item.title || "Unknown role"}</p>
                </TableCell>
                <TableCell className="tabular-nums">
                  {item.fitScore == null ? "Not scored" : `${item.fitScore}%`}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {applicationStatusLabel(t, item.applicationStatus)}
                  </Badge>
                </TableCell>
                <TableCell className="min-w-72 text-sm">{companyEvidence(item)}</TableCell>
                <TableCell className="min-w-44 text-sm">{sponsorship(item.h1BStatus)}</TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {item.offerTotal == null
                    ? "No structured offer"
                    : `${item.offerTotal.toLocaleString()} ${item.offerCurrency ?? ""}`.trim()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
