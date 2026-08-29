import { Link } from "react-router-dom";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { KIND_LABELS, MODALITY_LABELS, PLATFORM_LABELS, RESULT_LABELS } from "@/features/job/event-labels";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { ApplicationsTableData } from "./use-applications";

type PivotCell = ApplicationsTableData["rows"][number]["cells"][string];

const FIXED_STAGES = [
  ["application_submitted", "Submitted"],
  ["recruiter_screen", "Recruiter"],
  ["online_assessment", "OA"],
  ["questionnaire", "Questionnaire"],
  ["technical_phone_screen", "Phone screen"],
] as const;

const LATE_STAGES = [
  ["system_design", "Design"],
  ["behavioral", "Behavioral"],
  ["hiring_manager", "Hiring manager"],
  ["onsite_loop", "Onsite"],
  ["team_match", "Team match"],
  ["offer_received", "Offer"],
  ["rejected", "Rejected"],
  ["withdrawn", "Withdrawn"],
] as const;

function compactDate(value: string, allDay = false): string {
  return formatCalendarDate(value, allDay, { month: "short", day: "numeric" });
}

function metadata(cell: PivotCell): string {
  return [
    RESULT_LABELS[cell.result] ?? cell.result,
    cell.modality ? MODALITY_LABELS[cell.modality] ?? cell.modality : null,
    cell.platform ? PLATFORM_LABELS[cell.platform] ?? cell.platform : null,
    cell.platformOther,
    cell.interviewers,
  ].filter(Boolean).join(" · ");
}

function StageCell({ cell, label }: { cell?: PivotCell; label: string }) {
  const [open, setOpen] = useState(false);
  if (!cell?.occurredAt) return <span className="text-muted-foreground">—</span>;
  const detail = metadata(cell);
  return (
    <span className="relative block w-fit">
      <button
        type="button"
        aria-label={`${label} details`}
        aria-expanded={open}
        title={detail}
        className="cursor-pointer rounded px-1 py-0.5 tabular-nums outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen((value) => !value)}
      >
        {compactDate(cell.occurredAt, cell.allDay)}
      </button>
      {open ? (
        <span className="absolute left-0 top-full z-20 mt-1 w-max max-w-64 rounded-md border bg-popover px-2.5 py-2 text-xs leading-5 text-popover-foreground shadow-card-raised">
          {detail || "No additional details"}
        </span>
      ) : null}
    </span>
  );
}

export function ApplicationsTable({ table }: { table: ApplicationsTableData }) {
  if (table.rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/20 px-5 py-10 text-center text-sm text-muted-foreground">
        No applications tracked yet.
      </div>
    );
  }

  const technicalStages = Array.from(
    { length: table.technicalRoundColumns },
    (_, index) => [`technical_round_${index + 1}`, `Tech ${index + 1}`] as const,
  );
  const stages = [...FIXED_STAGES, ...technicalStages, ...LATE_STAGES];

  return (
    <div className="min-w-0 overflow-x-auto rounded-lg border bg-card shadow-card">
      <Table className="min-w-[1180px] caption-top">
        <caption className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Application timeline grid
        </caption>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 z-10 min-w-44 bg-card">Company</TableHead>
            <TableHead className="min-w-44">Role</TableHead>
            <TableHead>Status</TableHead>
            {stages.map(([key, label]) => <TableHead key={key}>{label}</TableHead>)}
            <TableHead>Deadline</TableHead>
            <TableHead>Total comp</TableHead>
            <TableHead>Other</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {table.rows.map((row) => (
            <TableRow key={row.jobId}>
              <TableCell className="sticky left-0 z-[1] max-w-52 bg-card font-medium">
                <Link
                  to={`/pipeline?job=${row.jobId}`}
                  className="block truncate text-primary underline-offset-4 hover:underline"
                >
                  {row.company || "Unknown company"}
                </Link>
              </TableCell>
              <TableCell className="max-w-56 truncate">{row.title || "—"}</TableCell>
              <TableCell><Badge variant="outline">{row.status}</Badge></TableCell>
              {stages.map(([key, label]) => {
                const isLastVisibleRound = key === `technical_round_${table.technicalRoundColumns}`;
                return (
                  <TableCell key={key} className="whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <StageCell
                        cell={row.cells[key]}
                        label={
                          key.startsWith("technical_round_")
                            ? `Technical round ${key.slice("technical_round_".length)}`
                            : KIND_LABELS[key] ?? label
                        }
                      />
                      {isLastVisibleRound && row.overflowRounds > 0 ? (
                        <Badge variant="secondary">+{row.overflowRounds}</Badge>
                      ) : null}
                    </div>
                  </TableCell>
                );
              })}
              <TableCell className="whitespace-nowrap">
                {row.offerDeadline
                  ? compactDate(row.offerDeadline, row.cells.offer_deadline?.allDay)
                  : "—"}
              </TableCell>
              <TableCell className="whitespace-nowrap tabular-nums">
                {row.totalComp != null
                  ? `${row.totalComp.toLocaleString()} ${row.compCurrency ?? ""}`.trim()
                  : "—"}
              </TableCell>
              <TableCell>{row.customCount ? `Other (${row.customCount})` : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
