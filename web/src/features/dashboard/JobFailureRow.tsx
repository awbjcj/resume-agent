import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ErrorRecord } from "@/features/errors/use-errors";

import { timeAgo } from "./time-ago";

interface JobFailureRowProps {
  record: ErrorRecord;
  onRetry: () => void;
  onDismiss: () => void;
  onResolve: () => void;
  isBusy: boolean;
}

export function JobFailureRow({
  record,
  onRetry,
  onDismiss,
  onResolve,
  isBusy,
}: JobFailureRowProps) {
  const details = record.jobDetails;
  const [showTraceback, setShowTraceback] = useState(false);
  // A job record without details is a legacy or unparseable row; fall back to
  // the flat message rather than rendering an empty shell.
  const heading = details
    ? `${details.company ?? "Unknown company"} — ${details.title ?? "Untitled role"}`
    : record.sourceLabel;

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        {details ? (
          <a
            href={`/pipeline?job=${details.jobId}`}
            className="min-w-0 flex-1 truncate text-sm font-medium underline-offset-4 hover:underline"
          >
            {heading}
          </a>
        ) : (
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{heading}</span>
        )}
        {details && <Badge variant="secondary">{details.stage}</Badge>}
        {record.count > 1 && (
          <span className="text-xs text-muted-foreground">×{record.count}</span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{record.message}</p>
      <p className="text-xs text-muted-foreground">
        {details?.model ? `${details.model} · ` : ""}
        {timeAgo(Date.parse(record.lastSeenAt))}
      </p>

      {details?.tracebackTail && showTraceback && (
        <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-[0.7rem]">
          {details.tracebackTail}
        </pre>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {details?.tracebackTail ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="flex-1 justify-start px-0 text-xs text-muted-foreground hover:bg-transparent"
            onClick={() => setShowTraceback((current) => !current)}
          >
            Technical details
          </Button>
        ) : (
          <span className="flex-1" />
        )}
        {details && (
          <Button size="sm" variant="outline" disabled={isBusy} onClick={onRetry}>
            Retry
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={isBusy} onClick={onDismiss}>
          Dismiss
        </Button>
        <Button size="sm" variant="outline" disabled={isBusy} onClick={onResolve}>
          Resolve
        </Button>
      </div>
    </li>
  );
}
