import { useState } from "react";
import { PencilLine } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import { ApplicationTimeline } from "./ApplicationTimeline";
import { useUpsertApplication } from "./use-job-mutations";

const STATUSES = ["ready", "submitted", "interview", "offer", "rejected", "closed"];

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function ApplicationEditor({
  jobId,
  application,
}: {
  jobId: number;
  application: components["schemas"]["ApplicationOut"] | null;
}) {
  return (
    <ApplicationEditorState
      key={`${application?.id ?? "new"}-${application?.updatedAt ?? ""}`}
      jobId={jobId}
      application={application}
    />
  );
}

function ApplicationEditorState({
  jobId,
  application,
}: {
  jobId: number;
  application: components["schemas"]["ApplicationOut"] | null;
}) {
  const [status, setStatus] = useState(application?.status ?? "ready");
  const [notes, setNotes] = useState(application?.notes ?? "");
  const [overriding, setOverriding] = useState(false);
  const save = useUpsertApplication(jobId);

  const submit = () => {
    save.mutate({ status, notes: notes || null });
    setOverriding(false);
  };

  return (
    <div className="space-y-5">
      <div className="rounded-xl border bg-card/60 p-4 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Current status
            </p>
            <Badge variant="secondary" className="mt-2">
              {statusLabel(application?.status ?? "ready")}
            </Badge>
          </div>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={overriding}
            onClick={() => setOverriding((value) => !value)}
          >
            <PencilLine aria-hidden="true" />
            Override
          </Button>
        </div>

        {overriding && (
          <div className="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <div className="space-y-1.5">
              <Label htmlFor="application-status-override">Override status</Label>
              <select
                id="application-status-override"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {statusLabel(value)}
                  </option>
                ))}
              </select>
            </div>
            <Button onClick={submit} disabled={save.isPending}>
              Save
            </Button>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="application-notes">Application notes</Label>
        <Textarea
          id="application-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          onBlur={() => {
            if (notes !== (application?.notes ?? "")) submit();
          }}
          placeholder="Referral context, recruiter preferences, or general notes"
          className="min-h-24 resize-y"
        />
        <p className="text-xs text-muted-foreground">
          General notes live here; stage-specific notes belong on each event.
        </p>
      </div>

      <ApplicationTimeline jobId={jobId} />
    </div>
  );
}
