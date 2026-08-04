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
import { useSetStage } from "./use-job-mutations";
import type { JobDetail } from "./use-job-detail";

const STAGES = ["raw", "shortlisted", "approved", "tailored", "rendered", "rejected"];

export function StageManager({ job }: { job: JobDetail }) {
  const [stage, setStage] = useState(job.status);
  const setStageMut = useSetStage(job.id);

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
      </div>
      {(job.status === "filtered" || job.status === "rejected") &&
        stage !== "filtered" &&
        stage !== "rejected" && (
          <p className="text-xs text-muted-foreground">
            Moving this job forward overrides its discovery filter or rejection so it can be
            scored on the next discovery or shortlist re-score run.
          </p>
        )}
    </div>
  );
}
