import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { locationLabel } from "@/lib/format";

type Row = {
  jobId: number;
  company: string | null;
  title: string | null;
  fitScore: number | null;
  source?: string;
  location?: string | null;
  locationCountry?: string | null;
  locationRegion?: string | null;
  locationCity?: string | null;
  status?: string;
  postedAt?: string | null;
  url?: string | null;
  salaryMin?: number | null;
  salaryMax?: number | null;
  salaryCurrency?: string | null;
  seniority?: string | null;
  employmentType?: string | null;
  industry?: string | null;
  rejectReason?: string | null;
};

type ExtraColumn = {
  header: string;
  render: (row: Row) => ReactNode;
};

function sourceLabel(source: string | undefined): string {
  if (!source) return "—";
  return source
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function JobTable({
  rows,
  selection,
  onToggle,
  onOpen,
  onToggleAll,
  allChecked,
  actions,
  statusColumn = true,
  extraColumn,
}: {
  rows: Row[];
  selection: { isSelected: (id: number) => boolean };
  onToggle: (id: number, index: number, shift: boolean, ordered: number[]) => void;
  onOpen: (id: number) => void;
  onToggleAll?: (checked: boolean) => void;
  allChecked?: boolean;
  actions?: (row: Row) => ReactNode;
  /** Set false when the caller's rows all share one implicit status (e.g. the
   * shortlist and triage boards) — the column would otherwise be redundant. */
  statusColumn?: boolean;
  /** Replaces the space freed by hiding the status column with board-specific
   * detail (salary/seniority for the shortlist, reject reason for triage). */
  extraColumn?: ExtraColumn;
}) {
  const ordered = rows.map((row) => row.jobId);
  return (
    <Table className="min-w-[64rem] table-fixed">
      <colgroup>
        <col className="w-11" />
        <col className="w-72" />
        <col className="w-20" />
        <col className="w-32" />
        <col className="w-52" />
        {statusColumn && <col className="w-36" />}
        {extraColumn && <col className="w-64" />}
        {actions && <col className="w-40" />}
      </colgroup>
      <TableHeader>
        <TableRow>
          <TableHead>
            <Checkbox
              aria-label="Select all loaded jobs"
              checked={allChecked}
              onCheckedChange={(value) => onToggleAll?.(Boolean(value))}
            />
          </TableHead>
          <TableHead>Role</TableHead>
          <TableHead className="text-center">Fit</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Location</TableHead>
          {statusColumn && <TableHead>Status</TableHead>}
          {extraColumn && <TableHead>{extraColumn.header}</TableHead>}
          {actions && <TableHead className="text-right">Actions</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow
            key={row.jobId}
            data-selected={selection.isSelected(row.jobId)}
            className="cursor-pointer data-[selected=true]:bg-secondary/60"
          >
            <TableCell onClick={(event) => event.stopPropagation()}>
              <Checkbox
                aria-label={`Select ${row.company ?? "job"} ${row.title ?? ""}`.trim()}
                checked={selection.isSelected(row.jobId)}
                onClick={(event) => {
                  event.stopPropagation();
                }}
                onCheckedChange={(checked, details) => {
                  const nextChecked = Boolean(checked);
                  if (nextChecked === selection.isSelected(row.jobId)) return;
                  const event = details.event as Event & { shiftKey?: boolean };
                  const shift = Boolean(event.shiftKey);
                  onToggle(row.jobId, index, shift, ordered);
                }}
              />
            </TableCell>
            <TableCell className="min-w-0">
              <button
                type="button"
                className="block w-full min-w-0 rounded-sm text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
                onClick={() => onOpen(row.jobId)}
              >
                <div className="truncate font-medium" title={row.title ?? undefined}>
                  {row.title ?? "Untitled role"}
                </div>
                <div
                  className="truncate text-xs text-muted-foreground"
                  title={row.company ?? undefined}
                >
                  {row.company ?? "Unknown company"}
                </div>
              </button>
            </TableCell>
            <TableCell className="text-center" onClick={() => onOpen(row.jobId)}>
              <Badge variant="secondary" className="min-w-9 justify-center tabular-nums">
                {row.fitScore ?? "—"}
              </Badge>
            </TableCell>
            <TableCell className="min-w-0" onClick={() => onOpen(row.jobId)}>
              <Badge
                variant="outline"
                className="max-w-full font-normal"
                title={row.source ?? undefined}
              >
                <span className="truncate">{sourceLabel(row.source)}</span>
              </Badge>
            </TableCell>
            <TableCell
              className="min-w-0 truncate text-muted-foreground"
              title={locationLabel(row) ?? undefined}
              onClick={() => onOpen(row.jobId)}
            >
              {locationLabel(row) ?? "—"}
            </TableCell>
            {statusColumn && (
              <TableCell onClick={() => onOpen(row.jobId)}>
                {row.status ? <StatusBadge status={row.status} /> : "—"}
              </TableCell>
            )}
            {extraColumn && (
              <TableCell
                className="min-w-0 truncate text-muted-foreground"
                onClick={() => onOpen(row.jobId)}
              >
                {extraColumn.render(row) ?? "—"}
              </TableCell>
            )}
            {actions && (
              <TableCell className="text-right" onClick={(event) => event.stopPropagation()}>
                <div className="flex justify-end gap-1">{actions(row)}</div>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
