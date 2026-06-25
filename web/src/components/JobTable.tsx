import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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
};

export function JobTable({
  rows,
  selection,
  onToggle,
  onOpen,
  onToggleAll,
  allChecked,
}: {
  rows: Row[];
  selection: { isSelected: (id: number) => boolean };
  onToggle: (id: number, index: number, shift: boolean, ordered: number[]) => void;
  onOpen: (id: number) => void;
  onToggleAll?: (checked: boolean) => void;
  allChecked?: boolean;
}) {
  const ordered = rows.map((row) => row.jobId);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">
            <Checkbox
              aria-label="Select all loaded jobs"
              checked={allChecked}
              onCheckedChange={(value) => onToggleAll?.(Boolean(value))}
            />
          </TableHead>
          <TableHead>Company · Title</TableHead>
          <TableHead className="text-right">Fit</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Location</TableHead>
          <TableHead>Status</TableHead>
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
            <TableCell onClick={() => onOpen(row.jobId)}>
              <span className="font-medium">{row.company ?? "—"}</span>
              <span className="text-muted-foreground"> · {row.title ?? "—"}</span>
            </TableCell>
            <TableCell className="text-right" onClick={() => onOpen(row.jobId)}>
              <Badge variant="secondary">{row.fitScore ?? "no score"}</Badge>
            </TableCell>
            <TableCell onClick={() => onOpen(row.jobId)}>{row.source ?? "—"}</TableCell>
            <TableCell onClick={() => onOpen(row.jobId)}>{row.location ?? "—"}</TableCell>
            <TableCell onClick={() => onOpen(row.jobId)}>{row.status ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
