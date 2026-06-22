import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUpsertApplication } from "./use-job-mutations";
import type { components } from "@/lib/api/schema";

const STATUSES = ["ready", "submitted", "interview", "offer", "rejected"];

export function ApplicationEditor({
  jobId,
  application,
}: {
  jobId: number;
  application: components["schemas"]["ApplicationOut"] | null;
}) {
  const [status, setStatus] = useState(application?.status ?? "ready");
  const [notes, setNotes] = useState(application?.notes ?? "");
  const save = useUpsertApplication(jobId);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="app-status">Application status</Label>
        <Select value={status} onValueChange={(v) => setStatus(v ?? "ready")}>
          <SelectTrigger id="app-status" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="app-notes">Notes</Label>
        <Input
          id="app-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="e.g. applied via referral"
        />
      </div>
      <Button onClick={() => save.mutate({ status, notes: notes || null })}>Save</Button>
    </div>
  );
}
