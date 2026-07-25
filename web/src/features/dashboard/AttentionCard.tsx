import { useState } from "react";
import { CircleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  useDismissAllErrors,
  useDismissError,
  useErrorRecords,
  useResolveError,
  type ErrorRecord,
} from "@/features/errors/use-errors";
import { RedoDialog } from "@/features/runs/RedoDialog";
import { useRedoRun, type RedoStage } from "@/features/runs/use-redo-run";

import { JobFailureRow } from "./JobFailureRow";

const VISIBLE_LIMIT = 8;
const GROUPS: { kind: string; heading: string }[] = [
  { kind: "job", heading: "Jobs" },
  { kind: "source", heading: "Sources" },
  { kind: "run", heading: "Runs" },
];

interface RetryTarget {
  jobId: number;
  stage: RedoStage;
}

export function AttentionCard() {
  const records = useErrorRecords("open");
  const dismiss = useDismissError();
  const resolve = useResolveError();
  const clearAll = useDismissAllErrors();
  const redoRun = useRedoRun();
  const [showAll, setShowAll] = useState(false);
  const [retry, setRetry] = useState<RetryTarget | null>(null);

  const rows = records.data?.records ?? [];
  const visible = showAll ? rows : rows.slice(0, VISIBLE_LIMIT);
  const isBusy = dismiss.isPending || resolve.isPending;

  const grouped = GROUPS.map((group) => ({
    ...group,
    items: visible.filter((row) => row.kind === group.kind),
  })).filter((group) => group.items.length > 0);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <CircleAlert className="text-destructive" aria-hidden="true" />
          Attention needed
          {rows.length ? <Badge variant="destructive">{rows.length}</Badge> : null}
        </CardTitle>
        {rows.length ? (
          <Button
            size="sm"
            variant="outline"
            disabled={clearAll.isPending}
            onClick={() => clearAll.mutate()}
          >
            {clearAll.isPending ? <Spinner data-icon="inline-start" /> : null}
            Clear all
          </Button>
        ) : null}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {records.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            Loading errors…
          </div>
        ) : null}

        {records.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not load errors</AlertTitle>
            <AlertDescription className="flex items-center justify-between gap-3">
              <span>Recent failures are temporarily unavailable.</span>
              <Button size="sm" variant="outline" onClick={() => void records.refetch()}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {!records.isPending && !records.isError && !rows.length ? (
          <p className="text-sm text-muted-foreground">No open errors.</p>
        ) : null}

        {grouped.map((group) => (
          <section key={group.kind} className="flex flex-col gap-2">
            <h3 className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              {group.heading}
            </h3>
            <ul className="flex flex-col gap-3">
              {group.items.map((row) =>
                row.kind === "job" ? (
                  <JobFailureRow
                    key={row.id}
                    record={row}
                    isBusy={isBusy}
                    onRetry={() => openRetry(row, setRetry)}
                    onDismiss={() => dismiss.mutate({ id: row.id })}
                    onResolve={() => resolve.mutate({ id: row.id })}
                  />
                ) : (
                  <PlainErrorRow
                    key={row.id}
                    record={row}
                    isBusy={isBusy}
                    onDismiss={() => dismiss.mutate({ id: row.id })}
                    onResolve={() => resolve.mutate({ id: row.id })}
                  />
                ),
              )}
            </ul>
          </section>
        ))}

        {!showAll && rows.length > VISIBLE_LIMIT ? (
          <Button size="sm" variant="ghost" onClick={() => setShowAll(true)}>
            Show all {rows.length}
          </Button>
        ) : null}
      </CardContent>

      <RedoDialog
        open={retry !== null}
        jobIds={retry ? [retry.jobId] : []}
        initialStages={retry ? [retry.stage] : []}
        onOpenChange={(open) => {
          if (!open) setRetry(null);
        }}
        onLaunch={(jobIds, stages, deep) => redoRun.redo(jobIds, stages, deep)}
      />
    </Card>
  );
}

function openRetry(
  row: ErrorRecord,
  setRetry: (target: RetryTarget | null) => void,
): void {
  if (!row.jobDetails) return;
  setRetry({
    jobId: row.jobDetails.jobId,
    stage: row.jobDetails.stage as RedoStage,
  });
}

function PlainErrorRow({
  record,
  isBusy,
  onDismiss,
  onResolve,
}: {
  record: ErrorRecord;
  isBusy: boolean;
  onDismiss: () => void;
  onResolve: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{record.sourceLabel}</span>
        <span className="text-xs text-muted-foreground">
          {record.message}
          {record.count > 1 ? ` · seen ${record.count}×` : ""}
        </span>
      </div>
      <Button size="sm" variant="ghost" disabled={isBusy} onClick={onDismiss}>
        Dismiss
      </Button>
      <Button size="sm" variant="outline" disabled={isBusy} onClick={onResolve}>
        Resolve
      </Button>
    </li>
  );
}
