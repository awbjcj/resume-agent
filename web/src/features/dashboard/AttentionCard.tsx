import { useState } from "react";
import { CircleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
const GROUPS = [
  { kind: "job", heading: "Jobs", headingKey: "dashboard.errorGroups.jobs" },
  { kind: "source", heading: "Sources", headingKey: "dashboard.errorGroups.sources" },
  { kind: "run", heading: "Runs", headingKey: "dashboard.errorGroups.runs" },
] as const;

interface RetryTarget {
  jobId: number;
  stage: RedoStage;
}

/**
 * Every non-empty group keeps its heading visible, even when collapsed: slicing
 * the flat row list to VISIBLE_LIMIT before grouping could zero out an entire
 * kind's section just because another kind is more numerous. Each group gets
 * at least one row (if it has any), then the remaining budget fills groups in
 * priority order, so the total shown still respects the limit.
 */
function distributeVisibleBudget<T extends { items: unknown[] }>(
  groups: T[],
  limit: number,
): T[] {
  const reserved = groups.map((group) => Math.min(1, group.items.length));
  let budget = limit - reserved.reduce((total, count) => total + count, 0);
  return groups.map((group, index) => {
    const extra = Math.max(0, Math.min(budget, group.items.length - reserved[index]));
    budget -= extra;
    return { ...group, items: group.items.slice(0, reserved[index] + extra) };
  });
}

export function AttentionCard() {
  const { t } = useTranslation();
  const records = useErrorRecords("open");
  const dismiss = useDismissError();
  const resolve = useResolveError();
  const clearAll = useDismissAllErrors();
  const redoRun = useRedoRun();
  const [showAll, setShowAll] = useState(false);
  const [retry, setRetry] = useState<RetryTarget | null>(null);

  const rows = records.data?.records ?? [];
  const isBusy = dismiss.isPending || resolve.isPending;

  const activeGroups = GROUPS.map((group) => ({
    ...group,
    items: rows.filter((row) => row.kind === group.kind),
  })).filter((group) => group.items.length > 0);
  const grouped = showAll
    ? activeGroups
    : distributeVisibleBudget(activeGroups, VISIBLE_LIMIT);

  return (
    <Card>
      {/* CardHeader is `display: grid`, so the `flex-row items-center
          justify-between` this used to carry was inert and dropped "Clear all"
          onto its own row. CardAction is the primitive's own affordance for a
          trailing control — it opts the header into `grid-cols-[1fr_auto]`. */}
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CircleAlert className="text-destructive" aria-hidden="true" />
          {t("dashboard.attentionNeeded")}
          {rows.length ? <Badge variant="destructive">{rows.length}</Badge> : null}
        </CardTitle>
        {rows.length ? (
          <CardAction>
            <Button
              size="sm"
              variant="outline"
              disabled={clearAll.isPending}
              onClick={() => clearAll.mutate()}
            >
              {clearAll.isPending ? <Spinner data-icon="inline-start" /> : null}
              {t("dashboard.clearAll")}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {records.isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner />
            {t("dashboard.loadingErrors")}
          </div>
        ) : null}

        {records.isError ? (
          <Alert variant="destructive">
            <AlertTitle>{t("dashboard.loadErrorsFailed")}</AlertTitle>
            <AlertDescription className="flex items-center justify-between gap-3">
              <span>{t("dashboard.errorsUnavailable")}</span>
              <Button size="sm" variant="outline" onClick={() => void records.refetch()}>
                {t("common.retry")}
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {!records.isPending && !records.isError && !rows.length ? (
          <p className="text-sm text-muted-foreground">{t("dashboard.noOpenErrors")}</p>
        ) : null}

        {grouped.map((group) => (
          <section key={group.kind} className="flex flex-col gap-2">
            <h3 className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              {t(group.headingKey)}
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
            {t("dashboard.showAll", { count: rows.length })}
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
  const { t } = useTranslation();
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{record.sourceLabel}</span>
        <span className="text-xs text-muted-foreground">
          {record.message}
          {record.count > 1 ? ` · ${t("dashboard.seenCount", { count: record.count })}` : ""}
        </span>
      </div>
      <Button size="sm" variant="ghost" disabled={isBusy} onClick={onDismiss}>
        {t("dashboard.dismiss")}
      </Button>
      <Button size="sm" variant="outline" disabled={isBusy} onClick={onResolve}>
        {t("dashboard.resolve")}
      </Button>
    </li>
  );
}
