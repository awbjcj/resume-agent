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

type Row = {
  jobId: number;
  company: string | null;
  title: string | null;
  fitScore: number | null;
  source?: string;
  location?: string | null;
  status?: string;
  postedAt?: string | null;
  url?: string | null;
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
}: {
  rows: Row[];
  selection: { isSelected: (id: number) => boolean };
  onToggle: (id: number, index: number, shift: boolean, ordered: number[]) => void;
  onOpen: (id: number) => void;
  onToggleAll?: (checked: boolean) => void;
  allChecked?: boolean;
  actions?: (row: Row) => ReactNode;
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
        <col className="w-36" />
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
          <TableHead>Status</TableHead>
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
              title={row.location ?? undefined}
              onClick={() => onOpen(row.jobId)}
            >
              {row.location ?? "—"}
            </TableCell>
            <TableCell onClick={() => onOpen(row.jobId)}>
              {row.status ? <StatusBadge status={row.status} /> : "—"}
            </TableCell>
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
