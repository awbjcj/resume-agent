import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useSetStage } from "./use-job-mutations";
import { useDeleteJob } from "@/features/triage/use-triage-mutations";
import type { JobDetail } from "./use-job-detail";

const STAGES = ["raw", "shortlisted", "approved", "tailored", "rendered", "rejected"];

export function StageManager({ job, onDeleted }: { job: JobDetail; onDeleted: () => void }) {
  const [stage, setStage] = useState(job.status);
  const setStageMut = useSetStage(job.id);
  const del = useDeleteJob();

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="mng-stage">Stage</Label>
        <Select value={stage} onValueChange={(v) => setStage(v ?? job.status)}>
          <SelectTrigger id="mng-stage" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STAGES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex gap-2">
        <Button onClick={() => setStageMut.mutate(stage)}>Set stage</Button>
        <ConfirmDialog
          trigger={
            <Button variant="destructive" disabled={job.hasProgress}>
              Delete
            </Button>
          }
          title="Delete this job?"
          description="This cannot be undone."
          confirmLabel="Confirm delete"
          onConfirm={() => {
            del.mutate(job.id);
            onDeleted();
          }}
        />
      </div>
      {job.hasProgress && (
        <p className="text-xs text-muted-foreground">Has progress — delete disabled.</p>
      )}
    </div>
  );
}
