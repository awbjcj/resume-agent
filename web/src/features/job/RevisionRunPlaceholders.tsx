import { Spinner } from "@/components/ui/spinner";
import { useRunStore } from "@/lib/runs/store";
import { ACTIVE_RUN_STATUSES } from "./artifact-runs";

export function RevisionRunPlaceholders({
  jobId,
  kind,
  label,
}: {
  jobId: number;
  kind: "revise" | "coverLetterRevise";
  label: string;
}) {
  const runs = useRunStore((state) => state.runs);
  const pending = Object.values(runs).filter(
    (run) =>
      run.kind === kind &&
      run.meta?.jobId === jobId &&
      ACTIVE_RUN_STATUSES.includes(run.status),
  );

  return pending.map((run) => (
    <li
      key={run.runId}
      className="rounded-xl border border-dashed bg-muted/25 p-4"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 text-sm font-medium">
        <Spinner data-icon="inline-start" />
        {label} in progress
      </div>
      {run.meta?.instruction ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {run.meta.instruction}
        </p>
      ) : null}
    </li>
  ));
}
