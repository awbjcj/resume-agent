import type { ReactNode } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { useDeleteJob } from "@/features/triage/use-triage-mutations";
import { ApplicationEditor } from "./ApplicationEditor";
import { StageManager } from "./StageManager";
import type { JobDetail } from "./use-job-detail";

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
      {children}
    </h3>
  );
}

/**
 * Where the job stands, in causal order: pipeline stage, then what you did
 * about it, then the destructive action fenced off at the bottom.
 */
export function TrackingTab({
  job,
  onDeleted,
}: {
  job: JobDetail;
  onDeleted: () => void;
}) {
  const del = useDeleteJob();

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <SectionHeading>Pipeline stage</SectionHeading>
        <StageManager job={job} />
      </section>

      <hr className="border-border" />

      <section className="space-y-3">
        <SectionHeading>Application &amp; timeline</SectionHeading>
        <ApplicationEditor jobId={job.id} application={job.application} />
      </section>

      <hr className="border-border" />

      <section className="space-y-3">
        <SectionHeading>Danger zone</SectionHeading>
        <div className="flex flex-wrap items-center gap-3">
          <ConfirmDialog
            trigger={
              <Button variant="destructive" disabled={job.hasProgress}>
                Delete job
              </Button>
            }
            title="Delete this job?"
            description="This cannot be undone."
            confirmLabel="Confirm delete"
            onConfirm={() => del.mutate(job.id, { onSuccess: onDeleted })}
          />
          {job.hasProgress && (
            <p className="text-xs text-muted-foreground">Has progress — delete disabled.</p>
          )}
        </div>
      </section>
    </div>
  );
}
